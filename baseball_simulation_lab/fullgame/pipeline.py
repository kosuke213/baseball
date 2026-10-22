"""Immutable Stage 8 artifacts and staged validation, independent of earlier outputs."""
from __future__ import annotations

from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile

from data_collection import warehouse as w
from data_collection.fetch import write_json
from data_collection.stage5 import write_archive
from ..calibrated.rules import canonical
from .engine import ENGINE_VERSION
from .model import GameModel
from .paths import ROOT, new_output
from .rules import GameRules, RULES_VERSION
from .sources import build, input_paths, sha
from .validation import audit_stage7, run_validation

MANUALS = ('README.md', 'TRANSITIONS.md', 'STAGE9.md', 'ATTRIBUTIONS.md')


def validate_config(c):
    if (c['milestones'] != [100, 1000, 10000] or c['strict_milestones'] != [100, 1000]
            or c['allow_assumptions'] is not True or c['seed_start'] != 8000
            or not 1 <= c['sample_histories'] <= 20):
        raise ValueError('Fixed staged experiment protocol required')
    GameRules(**c['rules']).validate()


def publish(target, reports):
    reports = new_output(reports); reports.mkdir(parents=True, exist_ok=True)
    files = {p.relative_to(target).as_posix(): p for p in sorted(target.rglob('*')) if p.is_file()}
    for name, path in files.items():
        if '/' not in name and path.suffix not in ('.sqlite3',): shutil.copyfile(path, reports / name)
    archive = reports / 'stage8_bundle.zip'; write_archive(archive, files)
    write_json(reports / 'bundle.json', {'file': archive.name, 'bytes': archive.stat().st_size,
               'sha256': sha(archive), 'snapshot_id': target.name})


def run(config_path, output, reports):
    output, reports = new_output(output), new_output(reports)
    c = json.loads(Path(config_path).read_text()); validate_config(c)
    source5, source6, cache, pins = input_paths()
    for path, expected in [(source5, pins['stage5_database_sha256']), (source6, pins['stage6_observations_sha256'])]:
        if sha(path) != expected: raise ValueError('Immutable input database mismatch')
    code = sorted(p for package in ('baseball_simulation_lab', 'data_collection') for p in (ROOT / package).rglob('*')
                  if p.suffix in ('.py', '.sql') and '__pycache__' not in p.parts)
    provenance = {'stage7_snapshot': json.loads((ROOT / 'data_sources/stage7/manifest.json').read_text())['snapshot_id'],
        'code_sha256': hashlib.sha256(b''.join(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() for p in code)).hexdigest(),
        'config_sha256': sha(config_path), 'manuals': {n: sha(reports / n) for n in MANUALS},
        'stage5_sha256': sha(source5), 'stage6_sha256': sha(source6), 'engine_version': ENGINE_VERSION,
        'rules_version': RULES_VERSION, 'runtime': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version}}
    key = hashlib.sha256(canonical(provenance).encode()).hexdigest()[:24]
    with w.run_lock(output):
        ledger = w.Ledger(output); run_id = ledger.start(provenance['config_sha256'])
        temporary = None
        try:
            parent = output / 'snapshots'; parent.mkdir(exist_ok=True)
            target = parent / key
            if target.exists():
                record = json.loads((target / 'snapshot.json').read_text())
                if any(sha(target / n) != h for n, h in record['files'].items()):
                    raise ValueError('Committed Stage 8 snapshot is corrupt')
                status = 'reused'
            else:
                temporary = Path(tempfile.mkdtemp(prefix='.building-', dir=parent))
                build(temporary / 'source')
                shutil.copyfile(temporary / 'source/source_audit.json', temporary / 'source_audit.json')
                (temporary / 'routes.json.gz').write_bytes(gzip.compress((temporary / 'source/routes.json').read_bytes(), mtime=0))
                shutil.rmtree(temporary / 'source')
                model_dir = temporary / 'stage7_model'; model_dir.mkdir()
                for name in ('base_model.json', 'kernels.json', 'identity_model.json', 'calibration.json', 'manifest.json', 'ATTRIBUTIONS.md'):
                    shutil.copyfile(ROOT / 'data_sources/stage7' / name, model_dir / name)
                model = GameModel.load(model_dir, temporary / 'routes.json.gz')
                print('Reproducing and classifying the old eight failures', flush=True)
                audit_stage7(model, temporary)
                print('Primary experiment: explicit assumptions enabled', flush=True)
                final = run_validation(model, temporary, c, lambda s: print(s, flush=True))
                strict = {**c, 'milestones': c['strict_milestones'], 'allow_assumptions': False, 'sample_histories': 2}
                print('Control experiment: empirical routes only', flush=True)
                control = run_validation(model, temporary / 'empirical_only', strict, lambda s: print(s, flush=True))
                write_json(temporary / 'summary.json', {'snapshot_id': key, **provenance,
                    'model_version': model.version, 'primary': final, 'empirical_only': control,
                    'network_play_data_requests': 0, 'fully_official_scoring': False,
                    'remaining_constraints': ['no unseen independent evaluation period', 'source route timing is certified, not reconstructed',
                         'no full earned runs / saves / holds / discretionary relief winning-pitcher decisions',
                         'historical records are experimental and immutable; legacy histories are untouched']})
                for name in MANUALS: shutil.copyfile(reports / name, temporary / name)
                if (hashlib.sha256(b''.join(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() for p in code)).hexdigest() != provenance['code_sha256']
                        or any(sha(reports / n) != h for n, h in provenance['manuals'].items())):
                    raise ValueError('Code or manuals changed during build; previous snapshot retained')
                shutil.copyfile(config_path, temporary / 'config.json')
                shutil.copyfile(Path(__file__).with_name('example.py'), temporary / 'example.py')
                for p in code:
                    destination = temporary / 'code' / p.relative_to(ROOT); destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, destination)
                files = {p.relative_to(temporary).as_posix(): sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}
                write_json(temporary / 'manifest.json', {'snapshot_id': key, **provenance, 'model_version': model.version,
                    'files': files, 'reproducibility': 'game events/counts deterministic; measured wall times are environment dependent'})
                write_json(temporary / 'snapshot.json', {'snapshot_id': key, 'files': {p.relative_to(temporary).as_posix(): sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}})
                os.replace(temporary, target); temporary = None; status = 'committed'
            if sha(source5) != pins['stage5_database_sha256'] or sha(source6) != pins['stage6_observations_sha256']:
                raise ValueError('Prior-stage source unexpectedly changed')
            publish(target, reports)
            write_json(output / 'current.json', {'snapshot_id': key, 'manifest_sha256': sha(target / 'manifest.json')})
            ledger.finish(run_id, status, key)
            print(canonical({'status': status, 'snapshot_id': key}), flush=True)
            return target
        except BaseException as exc:
            ledger.finish(run_id, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', message=type(exc).__name__)
            if temporary:
                write_json(temporary / 'build_failure.json', {'exception': type(exc).__name__, 'message': str(exc),
                           'previous_snapshot_preserved': True})
            raise
