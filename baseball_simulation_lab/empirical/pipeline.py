"""Immutable stage-6 outputs; all source data are opened read-only."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile

import numpy as np

from data_collection import adapters, fetch, warehouse as w
from data_collection.fetch import digest, write_json
from data_collection.stage5 import write_archive
from .analysis import analyze, csv_file, descriptive_exports
from .api import EmpiricalModel
from .common import OUTCOMES, canonical, sha_file
from .demo import simulate
from .extract import extract

ROOT = Path(__file__).resolve().parents[2]


def validate_config(config):
    if config['training_seasons'] != [2023, 2024] or config['test_seasons'] != [2025]:
        raise ValueError('Stage 6 requires a fixed 2023/2024 -> 2025 temporal split')
    if (not config['context_alphas'] or any(a <= 0 for a in config['context_alphas'])
            or not config['kernel_alphas'] or any(a <= 0 for a in config['kernel_alphas'])
            or any(not 0 <= v <= 1 for v in config['player_weights']) or not config['player_weights']):
        raise ValueError('Invalid smoothing grid')


def protect_paths(output, reports, source):
    protected = [ROOT / prefix / name for prefix in ('data_sources', 'data/research')
                 for name in ('pilot', 'warehouse', 'stage5')]
    for candidate in (output, reports):
        resolved = candidate.resolve()
        if resolved == source.resolve() or resolved in source.resolve().parents:
            raise ValueError('Output would overlap the source database')
        if any(resolved == p.resolve() or resolved.is_relative_to(p.resolve()) or p.resolve().is_relative_to(resolved) for p in protected):
            raise ValueError('Stage 3-5 output directories are protected')


def publish(folder, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        files[path.name] = path
        if path.name != 'observations.sqlite3':
            shutil.copyfile(path, report_dir / path.name)
    archive = report_dir / 'stage6_bundle.zip'
    write_archive(archive, files)
    write_json(report_dir / 'bundle.json', {'file': archive.name, 'bytes': archive.stat().st_size,
               'sha256': sha_file(archive), 'snapshot_id': folder.name,
               'model_sha256': sha_file(folder / 'model.json'), 'observations_sha256': sha_file(folder / 'observations.sqlite3')})


def run(args):
    config = json.loads(args.config.read_text())
    validate_config(config)
    source = args.source or ROOT / 'data/research/stage5/snapshots' / config['input_snapshot'] / 'warehouse.sqlite3'
    protect_paths(args.output, args.report_dir, source)
    if not source.exists() or sha_file(source) != config['input_database_sha256']:
        raise ValueError('Pinned Stage 5 database missing/corrupt; restore it from the Stage 5 distribution')
    paths = [*sorted(Path(__file__).parent.glob('*.py')), Path(adapters.__file__), Path(fetch.__file__), Path(w.__file__),
             Path(__file__).resolve().parents[2] / 'data_collection/stage5.py']
    provenance = {'config_sha256': sha_file(args.config), 'source_database_sha256': config['input_database_sha256'],
                  'source_snapshot': config['input_snapshot'],
                  'code_sha256': digest(b''.join(p.name.encode() + b'\0' + p.read_bytes() for p in paths)),
                  'documentation': {n: sha_file(args.report_dir / n) for n in ('README.md', 'ATTRIBUTIONS.md')},
                  'runtime': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'numpy': np.__version__}}
    key = digest(canonical(provenance).encode())[:24]
    with w.run_lock(args.output):
        ledger = w.Ledger(args.output)
        run_id = ledger.start(provenance['config_sha256'])
        temporary = None
        try:
            parent = args.output / 'snapshots'; parent.mkdir(exist_ok=True)
            target = parent / key
            if target.exists():
                snapshot = json.loads((target / 'snapshot.json').read_text())
                if any(sha_file(target / name) != sha for name, sha in snapshot['files'].items()):
                    raise ValueError('Existing Stage 6 snapshot is corrupt')
                status = 'reused'
            else:
                temporary = Path(tempfile.mkdtemp(dir=parent, prefix='.building-'))
                print('Extracting original flags and observed windows (offline)', flush=True)
                audit = extract(temporary / 'observations.sqlite3', source, args.cache, config['input_database_sha256'])
                if audit['support_exception_count']:
                    raise ValueError('Unresolved non-censored transition exceptions; inspect extraction audit')
                write_json(temporary / 'input_audit.json', audit)
                with closing(sqlite3.connect(temporary / 'observations.sqlite3')) as db:
                    evaluation = analyze(db, temporary, config, lambda value: print(value, flush=True))
                    half_counts = descriptive_exports(db, temporary)
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                        raise ValueError('Derived database integrity validation failed')
                model = json.loads((temporary / 'model.json').read_text())
                kernels = json.loads((temporary / 'kernels.json').read_text())
                counts = {name: len(model['tables'][name]) for name in ('hands', 'context', 'batter', 'pitcher')}
                counts['league'] = 1
                summary = {'snapshot_id': key, 'input': provenance, 'observations': audit['derived_counts'],
                           'outcome_classes': len(OUTCOMES) - 1, 'observed_outcome_classes': len(audit['outcome_counts']),
                           'component_groups': counts, 'component_probability_cells': sum(counts.values()) * len(OUTCOMES),
                           'conditional_transition_groups': len(kernels['conditional']),
                           'conditional_transition_cells': sum(len(t['p']) for t in kernels['conditional'].values()),
                           'prior_only_transition_cells': sum(sum(v == 0 for v in t['counts']) for t in kernels['conditional'].values()),
                           **half_counts, 'training_completed_pa': evaluation['training_completed_pa'],
                           'test_completed_pa': evaluation['test_completed_pa'], 'status': 'statistical_baseline_not_full_game_rules'}
                write_json(temporary / 'summary.json', summary)
                api = EmpiricalModel(model, kernels)
                demo = simulate(api, seed=config['seed'])
                csv_file(temporary / 'demo_steps.csv', demo.pop('steps'))
                write_json(temporary / 'demo_result.json', demo)
                shutil.copyfile(args.config, temporary / 'config.json')
                for name in ('README.md', 'ATTRIBUTIONS.md'):
                    shutil.copyfile(args.report_dir / name, temporary / name)
                files = {p.name: sha_file(p) for p in sorted(temporary.iterdir()) if p.is_file()}
                write_json(temporary / 'manifest.json', {'snapshot_id': key, **provenance, 'files': files,
                           'sources': audit['raw_artifacts'], 'network_requests': 0})
                write_json(temporary / 'snapshot.json', {'snapshot_id': key, 'files': {p.name: sha_file(p) for p in sorted(temporary.iterdir()) if p.is_file()}})
                os.replace(temporary, target)
                temporary = None
                status = 'committed'
            publish(target, args.report_dir)
            write_json(args.output / 'current.json', {'snapshot_id': key, 'model_sha256': sha_file(target / 'model.json')})
            ledger.finish(run_id, status, key)
            print(canonical({'status': status, 'snapshot_id': key, 'report_dir': str(args.report_dir)}))
            return 0
        except BaseException as exc:
            ledger.finish(run_id, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', message=type(exc).__name__)
            if temporary:
                shutil.rmtree(temporary)
            raise
