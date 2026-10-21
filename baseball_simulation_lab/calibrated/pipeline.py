"""Stage 7 offline, immutable processing; no previous data is modified."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile

import numpy as np

from data_collection import warehouse as w
from data_collection.fetch import digest, write_json
from data_collection.stage5 import write_archive
from ..empirical import fit
from ..empirical.analysis import csv_file
from .calibration import run_calibration
from .evaluation import compare_transitions, simulations
from .identity import collect
from .rules import RULES_VERSION, canonical

ROOT = Path(__file__).resolve().parents[2]


def protected(output, reports, inputs):
    roots = [ROOT / prefix / name for prefix in ('data/research', 'data_sources')
             for name in ('pilot', 'warehouse', 'stage5', 'stage6')]
    for candidate in (output.resolve(), reports.resolve()):
        if any(candidate == p.resolve() or candidate.is_relative_to(p.resolve()) or p.resolve().is_relative_to(candidate) for p in roots):
            raise ValueError('Previous stage output directories are protected')
        if any(candidate == p.resolve() or candidate in p.resolve().parents for p in inputs):
            raise ValueError('Output overlaps an immutable source')


def source_paths(args, config):
    source5 = args.source5 or ROOT / 'data/research/stage5/snapshots' / config['input_stage5_snapshot'] / 'warehouse.sqlite3'
    source6 = args.source6 or ROOT / 'data/research/stage6/snapshots' / config['input_stage6_snapshot'] / 'observations.sqlite3'
    for path, sha in [(source5, config['stage5_database_sha256']), (source6, config['stage6_observations_sha256'])]:
        if not path.exists() or w.file_sha(path) != sha:
            raise ValueError('Pinned Stage 5/6 input missing/corrupt; restore the published bundle')
    return source5, source6


def validate_config(config):
    if config['base_training_year'] != 2023 or config['calibration_cutoff'] != '2024-07-01' or config['reference_year'] != 2025:
        raise ValueError('Fixed temporal protocol required')
    if (not config['temperatures'] or any(not 0.1 <= v <= 5 for v in config['temperatures'])
            or not config['league_weights'] or any(not 0 <= v <= 1 for v in config['league_weights'])
            or not 1 <= config['simulation_halves'] <= 50000 or not 1 <= config['bootstrap_repetitions'] <= 5000):
        raise ValueError('Invalid bounded experiment configuration')


def copy_source_snapshot(folder):
    paths = []
    for package in ('baseball_simulation_lab', 'data_collection'):
        paths.extend(p for p in (ROOT / package).rglob('*') if p.suffix in ('.py', '.sql') and '__pycache__' not in p.parts)
    for p in paths:
        target = folder / 'code' / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)


def publish(folder, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    files = {p.relative_to(folder).as_posix(): p for p in sorted(folder.rglob('*')) if p.is_file()}
    for name, path in files.items():
        if '/' not in name and name != 'identity.sqlite3':
            shutil.copyfile(path, report_dir / name)
    archive = report_dir / 'stage7_bundle.zip'
    write_archive(archive, files)
    write_json(report_dir / 'bundle.json', {'file': archive.name, 'bytes': archive.stat().st_size,
               'sha256': w.file_sha(archive), 'snapshot_id': folder.name,
               'identity_database_sha256': w.file_sha(folder / 'identity.sqlite3')})


def run(args):
    config = json.loads(args.config.read_text())
    validate_config(config)
    source5, source6 = source_paths(args, config)
    protected(args.output, args.report_dir, (source5, source6))
    code = []
    for package in ('baseball_simulation_lab', 'data_collection'):
        code.extend(p for p in (ROOT / package).rglob('*') if p.suffix in ('.py', '.sql') and '__pycache__' not in p.parts)
    provenance = {'source5_sha256': config['stage5_database_sha256'], 'source6_sha256': config['stage6_observations_sha256'],
        'config_sha256': w.file_sha(args.config), 'rules_version': RULES_VERSION,
        'code_sha256': digest(b''.join(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() for p in sorted(code))),
        'documentation': {n: w.file_sha(args.report_dir / n) for n in ('README.md', 'ATTRIBUTIONS.md', 'TRANSITIONS.md', 'STAGE8.md')},
        'runtime': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'numpy': np.__version__},
        'evaluation': '2024 re-split exploratory, 2025 known reference; no independent final test available'}
    key = digest(canonical(provenance).encode())[:24]
    with w.run_lock(args.output):
        ledger = w.Ledger(args.output); run_id = ledger.start(provenance['config_sha256'])
        temporary = None
        try:
            parent = args.output / 'snapshots'; parent.mkdir(exist_ok=True)
            target = parent / key
            if target.exists():
                record = json.loads((target / 'snapshot.json').read_text())
                if any(w.file_sha(target / n) != sha for n, sha in record['files'].items()):
                    raise ValueError('Stage 7 committed snapshot is corrupt')
                status = 'reused'
            else:
                temporary = Path(tempfile.mkdtemp(dir=parent, prefix='.building-'))
                print('Recovering participant identities from immutable originals', flush=True)
                audit = collect(temporary / 'identity.sqlite3', source6, source5, args.cache)
                write_json(temporary / 'identity_audit.json', audit)
                with closing(sqlite3.connect('file:' + str(source6) + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(temporary / 'identity.sqlite3')) as ids:
                    dates = {g: (first, last) for g, first, last in ids.execute('SELECT game_id,min(first_date),max(last_date) FROM windows GROUP BY game_id')}
                    batch = fit.load_batch(src)
                    print('Fitting calibration on 2024-H1; choosing on disjoint 2024-H2', flush=True)
                    model, calibration = run_calibration(batch, dates, temporary, config)
                    templates, comparison = compare_transitions(batch, dates, ids, model, calibration, temporary, config)
                    kernels = json.loads((temporary / 'kernels.json').read_text())
                    summaries = simulations(model, kernels, templates, calibration, src, temporary, config,
                                             lambda value: print(value, flush=True))
                    csv_file(temporary / 'unsupported_windows.csv', (
                        dict(zip(['game_id', 'first_pn', 'last_pn', 'season', 'reason', 'artifact_id', 'first_source_row', 'last_source_row'], r))
                        for r in ids.execute('SELECT game_id,first_pn,last_pn,season,reason,artifact_id,first_source_row,last_source_row FROM windows WHERE supported=0 ORDER BY game_id,first_pn')))
                    ns = sorted(t['n'] for t in model['tables']['context'].values())
                    uncertainty = {'context_groups': len(ns), 'median_n': ns[len(ns) // 2], 'n_below_30': sum(n < 30 for n in ns),
                                   'identity_groups': len(templates['groups']),
                                   'identity_groups_below_30': sum(v['n'] < 30 for v in templates['groups'].values()),
                                   'limits': 'group counts and game bootstrap quantify different uncertainties; no season-transfer guarantee'}
                    write_json(temporary / 'uncertainty.json', uncertainty)
                    if ids.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or ids.execute('PRAGMA foreign_key_check').fetchall():
                        raise ValueError('Identity database integrity failed')
                write_json(temporary / 'summary.json', {'snapshot_id': key, **provenance,
                    'windows': audit['windows'], 'reconstructed': audit['reconstructed_windows'], 'supported': audit['supported_windows'],
                    'calibration_method': calibration['selected_method'], 'identity_groups': len(templates['groups']),
                    'identity_patterns': len(templates['sources']), 'simulation_halves_per_model': config['simulation_halves'],
                    'simulation_identity_failures': next(r['failed_halves'] for r in summaries if r['model'] == 'identity_rules'),
                    'network_data_requests': 0, 'full_engine_integration_ready': False})
                for name in ('README.md', 'ATTRIBUTIONS.md', 'TRANSITIONS.md', 'STAGE8.md'):
                    shutil.copyfile(args.report_dir / name, temporary / name)
                shutil.copyfile(args.config, temporary / 'config.json')
                shutil.copyfile(Path(__file__).with_name('example.py'), temporary / 'example.py')
                copy_source_snapshot(temporary)
                files = {p.relative_to(temporary).as_posix(): w.file_sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}
                write_json(temporary / 'manifest.json', {'snapshot_id': key, **provenance, 'files': files,
                    'raw_source_artifacts': audit['raw_artifacts'],
                    'raw_source_note': 'full author URLs and SHA256 are in Stage 5/6 manifests; no new data acquisition'})
                write_json(temporary / 'snapshot.json', {'snapshot_id': key, 'files': {p.relative_to(temporary).as_posix(): w.file_sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}})
                os.replace(temporary, target); temporary = None
                status = 'committed'
            if w.file_sha(source5) != config['stage5_database_sha256'] or w.file_sha(source6) != config['stage6_observations_sha256']:
                raise ValueError('Source database unexpectedly changed')
            publish(target, args.report_dir)
            write_json(args.output / 'current.json', {'snapshot_id': key, 'calibration_sha256': w.file_sha(target / 'calibration.json')})
            ledger.finish(run_id, status, key)
            print(canonical({'status': status, 'snapshot_id': key}))
            return 0
        except BaseException as exc:
            ledger.finish(run_id, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', message=type(exc).__name__)
            if temporary:
                shutil.rmtree(temporary)
            raise
