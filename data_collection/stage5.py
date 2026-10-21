"""Stage 5: independently scoped research measurements and historical Game Logs.

Run with --record-lock for a reviewed first acquisition; later runs are pinned.
Base snapshots and current simulation data are never modified.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from . import adapters, warehouse as w, warehouse_store as s
from .fetch import Collector, CollectionError, digest, write_json
from .__main__ import export_csv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = Path(__file__).with_name('stage5_schema.sql')
RESEARCH_IDS = ('5796004', '17502529', '16050919')


def verify_zenodo(metadata, spec):
    """A permissive plan alone cannot authorize a restricted/NC record."""
    record = json.loads(metadata)
    details = record['metadata']
    key = spec['rights'].removeprefix('zenodo_')
    if (str(record['id']) != key or details.get('access_right') != 'open'
            or details.get('license', {}).get('id') != 'cc-by-4.0'
            or record.get('doi') != spec['upstream_version']):
        raise CollectionError('Zenodo access, record version or license is unconfirmed')
    files = [f for f in record['files'] if f['key'] == spec['original_filename']]
    if len(files) != 1 or files[0]['checksum'] != 'md5:' + spec['expected_md5']:
        raise CollectionError('Zenodo file is not covered by the reviewed record')
    return files[0]


def validate_plan(plan):
    years = plan['years']
    if (years != sorted(set(years)) or not 1 <= len(years) <= 5
            or any(type(y) is not int or not 1990 <= y <= 2022 for y in years)):
        raise CollectionError('Stage 5 supports at most five modern historical Game Log years')
    if not 1 <= plan['budget_bytes'] <= 30_000_000:
        raise CollectionError('Stage 5 byte budget exceeds reviewed scope')
    artifacts = {v['id']: v for v in plan['artifacts']}
    expected = {f'zenodo_{key}_{kind}' for key in RESEARCH_IDS for kind in ('metadata', 'data')}
    expected |= {'retro_notice', 'retro_csv_docs', 'retro_gamelog_docs'}
    expected |= {f'retro_gl_{y}' for y in years}
    if set(artifacts) != expected or len(artifacts) != len(plan['artifacts']):
        raise CollectionError('Artifact membership differs from reviewed Stage 5 scope')
    for spec in artifacts.values():
        host = w.safe_url(spec['url'])
        if host not in ('zenodo.org', 'www.retrosheet.org') or not 1 <= spec['max_bytes'] <= 2_000_000:
            raise CollectionError('Stage 5 host or size is outside reviewed scope')
        rights = plan['rights'][spec['rights']]
        if not rights.get('attribution') or not rights.get('evidence_artifacts'):
            raise CollectionError('Missing rights attribution/evidence')
        if any(k not in artifacts or artifacts[k]['purpose'] != 'evidence' for k in rights['evidence_artifacts']):
            raise CollectionError('Missing rights evidence dependency')
        if spec['purpose'] == 'data' and not rights.get('warehouse_collection_allowed'):
            raise CollectionError('Rights decision defers collection')


def acquire(args, plan, ledger, run):
    path = args.plan.with_name('lock.json')
    lock = json.loads(path.read_text()) if path.exists() else None
    if not lock and not args.record_lock:
        raise CollectionError('First acquisition requires --record-lock')
    if lock and (lock['plan_sha256'] != w.file_sha(args.plan)
                 or set(lock['artifacts']) != {a['id'] for a in plan['artifacts']}):
        raise CollectionError('Plan differs from immutable lock; use a new plan directory')
    collector = Collector(args.cache, plan['rights'], offline=args.offline, budget=plan['budget_bytes'])
    payloads, metas, failures = {}, [], []
    for original in sorted(plan['artifacts'], key=lambda a: a['purpose'] == 'data'):
        spec = dict(original)
        try:
            if spec['purpose'] == 'data':
                evidence = plan['rights'][spec['rights']]['evidence_artifacts']
                if any(k not in payloads for k in evidence):
                    raise CollectionError('Evidence unavailable; dependent data skipped')
                if spec['rights'].startswith('zenodo_'):
                    verify_zenodo(payloads[spec['rights'] + '_metadata'], spec)
            if lock:
                pin = lock['artifacts'][spec['id']]
                if pin['url'] != spec['url']:
                    raise CollectionError('URL differs from pinned artifact')
                spec['expected_sha256'] = pin['sha256']
            before = collector.cache_hits
            data, meta = collector.fetch(spec)
            if lock and len(data) != pin['bytes']:
                raise CollectionError('Artifact length differs from lock')
            if spec.get('expected_md5'):
                if hashlib.md5(data, usedforsecurity=False).hexdigest() != spec['expected_md5']:
                    raise CollectionError('Author file checksum mismatch')
                file = verify_zenodo(payloads[spec['rights'] + '_metadata'], spec)
                if len(data) != file['size']:
                    raise CollectionError('Author file length mismatch')
            payloads[spec['id']] = data
            metas.append(meta)
            ledger.job(run, spec['id'], 'cached' if collector.cache_hits > before else 'downloaded', meta['sha256'])
        except (CollectionError, KeyError, ValueError) as exc:
            error = str(exc) if isinstance(exc, CollectionError) else 'Invalid source metadata/schema'
            failures.append({'artifact_id': spec['id'], 'error': error})
            ledger.job(run, spec['id'], 'failed', error=error)
    write_json(args.output / 'last_acquisition.json', {'failures': failures, 'network_requests': collector.network_requests,
               'cache_hits': collector.cache_hits, 'run_id': run, 'checked_at': w.now()})
    if failures:
        raise CollectionError('Stage 5 acquisition failed; verified artifacts retained for resume')
    if not lock:
        lock = {'schema_version': 1, 'plan_sha256': w.file_sha(args.plan),
                'artifacts': {m['id']: {k: m[k] for k in ('url', 'sha256', 'bytes')} for m in metas}}
        write_json(path, lock)
    return payloads, metas


def measurement(db, dataset, participant, metric, condition, statistic, value, sd,
                n, n_unit, unit, artifact, location, raw):
    if value is not None and not math.isfinite(value):
        raise CollectionError('Non-finite research measurement')
    if sd is not None and (not math.isfinite(sd) or sd < 0):
        raise CollectionError('Invalid research standard deviation')
    # Only an explicitly documented speed unit supports conversion.
    factor = {'km/h': 1 / 3.6, 'm/s': 1, 'mph': 0.44704}.get(unit)
    normalized = value * factor if factor is not None and value is not None else None
    normalized_sd = sd * factor if normalized is not None and sd is not None else None
    db.execute('''INSERT INTO research_measurements
      (dataset_id,participant_id,metric,condition,statistic,value,sd,reported_n,n_unit,
       source_unit,normalized_value,normalized_sd,normalized_unit,artifact_id,source_location,raw_text)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (dataset, participant, metric, condition, statistic, value, sd, n, n_unit, unit,
       normalized, normalized_sd, 'm/s' if normalized is not None else None, artifact, location, raw))


def dataset(db, key, metadata, scope, country, reported, observed, limitations):
    record = json.loads(metadata)
    db.execute('INSERT INTO research_datasets VALUES(?,?,?,?,?,?,?,?,?)',
               (key, key + '_data', record['metadata']['title'], record['doi'], scope, country,
                reported, observed, limitations))


def load_tryout(db, payloads):
    key = 'zenodo_5796004'
    data = payloads[key + '_data']
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    expected = ['id', 'height', 'irrom', 'errom', 'lthorax', 'rthorax', 'cmjnw', 'cmjw', 'sprint10', 'sprint30', 'velocity', 'handedness']
    if reader.fieldnames != expected:
        raise CollectionError('Taiwan tryout CSV schema changed')
    rows = list(reader)
    if len(rows) != 56 or len({r['id'] for r in rows}) != 56:
        raise CollectionError('Taiwan tryout cohort changed')
    dataset(db, key, payloads[key + '_metadata'], '2019 adult amateur male professional-team tryout', 'Taiwan', 64, 56,
            'Metadata says 64; actual CSV contains 56. Selection discrepancy unexplained. '
            'Units are absent from headers; all units remain unconfirmed. No age or mass columns. '
            'Per-participant velocity measurement is not a pitch-by-pitch stream. No player linkage.')
    for row_number, row in enumerate(rows, 2):
        participant = key + ':participant:' + row['id']
        db.execute('INSERT INTO research_participants VALUES(?,?,?)', (participant, key, row['id']))
        for field in expected[1:]:
            raw = row[field]
            if raw is None or not raw.strip():
                raise CollectionError('Unexpected missing tryout value')
            categorical = field == 'handedness'
            measurement(db, key, participant, field, 'tryout', 'categorical' if categorical else 'individual',
                        None if categorical else float(raw), None, None, None, None,
                        key + '_data', f'CSV:row={row_number}:column={field}', raw)
    s.remember_schema(db, key + '_data', 'baseball__Dataset.csv', expected, len(rows))


def docx_tables(data):
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = archive.getinfo('word/document.xml')
        if member.file_size > 2_000_000:
            raise CollectionError('DOCX XML exceeds size limit')
        root = ET.fromstring(archive.read(member))
    return [[[''.join(t.text or '' for t in cell.findall('.//w:t', ns)).strip()
              for cell in row.findall('w:tc', ns)] for row in table.findall('w:tr', ns)]
            for table in root.findall('.//w:tbl', ns)]


def mean_sd(text):
    match = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)', text)
    if not match:
        raise CollectionError('Unrecognized mean/SD cell; no inferred values')
    return float(match[1]), float(match[2])


def load_wada(db, payloads):
    key = 'zenodo_17502529'
    tables = docx_tables(payloads[key + '_data'])
    if len(tables) != 3 or [len(t) for t in tables] != [15, 18, 18]:
        raise CollectionError('Wada DOCX table layout changed')
    dataset(db, key, payloads[key + '_metadata'], 'collegiate male pitchers; laboratory trunk kinematics summaries',
            None, 16, 16, 'No raw pitches or measured ball-speed column in acquired tables. '
            'Country and per-cell N not explicit in the tables. Country not inferred from author names. '
            'Table 1 header uses degrees globally; angular velocity section explicitly uses deg/s. '
            'Table 2 says lateral plane; Table 3 says frontal plane; original headers retained.')
    labels = [row[0] for row in tables[0][2:8]]
    expected_labels = ['Extension (+)', 'Flexion (–)', 'Throwing-arm side lateral bend (+)',
                       'Glove side lateral bend (–)', 'Throwing-arm side twist (+)', 'Glove side twist (–)']
    if (labels != expected_labels or tables[0][1][0] != 'Angle, deg'
            or tables[0][8][0] != 'Angular Velocity, deg/s'
            or tables[0][0] != ['', 'Mean ± SD (º)', 'ρ', 'Pitching Cycle (%)']):
        raise CollectionError('Wada labels or unit definitions changed')
    for table_number, table in enumerate(tables[1:], 2):
        if table[1] != ['', 'Extension (+)', 'Flexion (–)', 'Throwing-arm side (+)', 'Glove side (–)', 'Throwing-arm side (+)', 'Glove side (–)']:
            raise CollectionError('Wada multi-column headers changed')
        for row_number, row in enumerate(table[2:], 3):
            if len(row) != 7 or row[0] != f'S{row_number - 2}':
                raise CollectionError('Wada participant rows changed')
            participant = key + ':participant:' + row[0]
            if table_number == 2:
                db.execute('INSERT INTO research_participants VALUES(?,?,?)', (participant, key, row[0]))
            for col, label in enumerate(labels, 1):
                value, sd = mean_sd(row[col])
                measurement(db, key, participant, ('angle:' if table_number == 2 else 'angular_velocity:') + label,
                            'maximum_effort_pitching', 'participant_summary', value, sd, None, None,
                            'deg' if table_number == 2 else 'deg/s', key + '_data',
                            f'DOCX:table={table_number}:row={row_number}:column={col + 1}', row[col])
    for start, prefix, unit in [(2, 'angle:', 'deg'), (9, 'angular_velocity:', 'deg/s')]:
        for offset, row in enumerate(tables[0][start:start + 6]):
            if len(row) != 4 or row[0] != labels[offset]:
                raise CollectionError('Wada cohort labels changed')
            location = f'DOCX:table=1:row={start + offset + 1}'
            value, sd = mean_sd(row[1])
            measurement(db, key, None, prefix + labels[offset], 'maximum_effort_pitching', 'cohort_summary',
                        value, sd, None, None, unit, key + '_data', location + ':column=2', row[1])
            rho = float(row[2])
            if not -1 <= rho <= 1:
                raise CollectionError('Correlation outside [-1,1]')
            measurement(db, key, None, prefix + labels[offset], 'association_with_ball_speed', 'correlation',
                        rho, None, None, None, 'dimensionless', key + '_data', location + ':column=3', row[2])
            value, sd = mean_sd(row[3])
            measurement(db, key, None, prefix + labels[offset], 'maximum_effort_pitching', 'pitch_cycle_summary',
                        value, sd, None, None, 'percent', key + '_data', location + ':column=4', row[3])
    s.remember_schema(db, key + '_data', 'word/document.xml', tables, sum(len(t) for t in tables))


def load_murdock(db, payloads, transcription):
    key = 'zenodo_16050919'
    if (digest(payloads[key + '_data']) != transcription['source_sha256']
            or transcription['artifact_id'] != key + '_data' or len(transcription['rows']) != 12):
        raise CollectionError('Reviewed transcription does not match the original PDF')
    dataset(db, key, payloads[key + '_metadata'], 'NCAA Division I men; metal bats; pitching machine; selected good hits',
            'United States', 16, 0, transcription['limitations'])
    seen = set()
    for number, row in enumerate(transcription['rows'], 1):
        identity = (row['condition'], row['metric'])
        if identity in seen or row['n'] not in (39, 40, 41):
            raise CollectionError('Duplicate or inconsistent thesis transcription row')
        seen.add(identity)
        measurement(db, key, None, row['metric'], row['condition'] + '_in_zone', 'cohort_summary', row['mean'],
                    row['sd'], row['n'], row['n_unit'], row['unit'], key + '_data',
                    f'PDF:page=14:printed_page=10:table=1:row={number}', s.js(row))
    s.remember_schema(db, key + '_data', 'PDF page 14 / printed page 10 / Table 1',
                      ['condition', 'metric', 'mean', 'sd', 'N'], 12)


def build_database(path, base_path, plan, payloads, metas, cache, transcription, reviews, metadata):
    shutil.copyfile(base_path, path)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        for meta in metas:
            old = db.execute('SELECT sha256 FROM artifacts WHERE artifact_id=?', (meta['id'],)).fetchone()
            if old and old[0] != meta['sha256']:
                raise CollectionError('Shared artifact differs from base snapshot')
            if not old:
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?)', (meta['id'], meta['sha256'], meta['bytes'], s.js(meta)))
        db.execute("INSERT INTO stage5_game_coverage SELECT game_id,'validated_plays','Stage 3/4 play consistency checks' FROM games")
        needed = {r[0] for r in db.execute('SELECT retrosheet_id FROM player_matches')}
        historical_checks = []
        for year in plan['years']:
            logs = s.load_games(db, payloads[f'retro_gl_{year}'], year, needed)
            checks = adapters.validate_games(list(logs.values()))
            historical_checks.append({'year': year, **checks})
            if checks['line_score_failures']:
                raise CollectionError('Historical Game Log line-score validation failed')
            db.execute("INSERT INTO stage5_game_coverage SELECT game_id,'game_log_only',"
                       "'Game Log line-score check only; no play-by-play acquired' FROM games WHERE season=?", (year,))
        # Use the exact reference shards already recorded in the base, not a mutable latest register.
        for artifact, sha in db.execute("SELECT artifact_id,sha256 FROM artifacts WHERE artifact_id GLOB 'register_[0-9a-f]'"):
            blob = cache / 'blobs' / sha
            if not blob.exists() or w.file_sha(blob) != sha:
                raise CollectionError('Pinned base register shard missing or corrupt')
            payloads[artifact] = blob.read_bytes()
        db.execute('DELETE FROM player_matches')
        db.execute('DELETE FROM identifiers')
        db.execute('DELETE FROM people')
        db.execute("DELETE FROM source_schemas WHERE artifact_id GLOB 'register_[0-9a-f]'")
        s.load_people(db, payloads, needed)
        load_tryout(db, payloads)
        load_wada(db, payloads)
        load_murdock(db, payloads, transcription)
        for row in reviews['sources']:
            db.execute('INSERT INTO stage5_source_review VALUES(?,?,?,?,?)',
                       (row['source'], row['status'], row['evidence_url'], row.get('evidence_sha256'), row['finding']))
        for key, value in metadata.items():
            db.execute('INSERT INTO metadata VALUES(?,?)', ('stage5_' + key, s.js(value)))
        report = quality(db)
        report['historical_log_checks'] = historical_checks
        if report['integrity_check'] != 'ok' or report['foreign_key_errors'] or report['validation_failures']:
            raise CollectionError('Stage 5 integrity or coverage validation failed')
        return report


def quality(db):
    tables = ['games', 'plays', 'analysis_plays', 'people', 'identifiers', 'research_datasets',
              'research_participants', 'research_measurements', 'research_confirmed_speeds']
    failures = []
    expected_research = {'research_datasets': 3, 'research_participants': 72,
                         'research_measurements': 856, 'research_confirmed_speeds': 4}
    for table, expected in expected_research.items():
        if db.execute('SELECT count(*) FROM ' + table).fetchone()[0] != expected:
            failures.append('unexpected_count:' + table)
    if db.execute('SELECT count(*) FROM games g LEFT JOIN stage5_game_coverage c USING(game_id) WHERE c.game_id IS NULL').fetchone()[0]:
        failures.append('game_missing_coverage')
    if db.execute("SELECT count(*) FROM stage5_game_coverage c LEFT JOIN game_checks q USING(game_id) WHERE c.coverage='validated_plays' AND (q.game_id IS NULL OR q.status!='pass')").fetchone()[0]:
        failures.append('invalid_validated_play_claim')
    if db.execute("SELECT count(*) FROM plays p JOIN stage5_game_coverage c USING(game_id) WHERE c.coverage='game_log_only'").fetchone()[0]:
        failures.append('unexpected_historical_plays')
    if db.execute("SELECT count(*) FROM identifiers GROUP BY namespace,identifier HAVING count(DISTINCT person_id)>1 LIMIT 1").fetchone():
        failures.append('ambiguous_reference_identifiers')
    return {
        'stage': 5, 'data_validation': 'pass' if not failures else 'fail',
        'simulation_readiness': 'partial_research_only',
        'counts': {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in tables},
        'by_year': [dict(zip(['season', 'coverage', 'games', 'play_rows'], r)) for r in db.execute(
            'SELECT g.season,c.coverage,count(*),coalesce(sum(q.play_rows),0) FROM games g JOIN stage5_game_coverage c USING(game_id) '
            'LEFT JOIN game_checks q USING(game_id) GROUP BY g.season,c.coverage ORDER BY g.season')],
        'research_statistics': dict(db.execute('SELECT statistic,count(*) FROM research_measurements GROUP BY statistic')),
        'confirmed_speed_statistics': dict(db.execute("SELECT statistic,count(*) FROM research_confirmed_speeds GROUP BY statistic")),
        'identity_status_all_roles': dict(db.execute('SELECT status,count(*) FROM player_matches GROUP BY status')),
        'unresolved_park_codes': [r[0] for r in db.execute("SELECT source_code FROM parks WHERE metadata_status='unresolved' ORDER BY source_code")],
        'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
        'foreign_key_errors': db.execute('PRAGMA foreign_key_check').fetchall(), 'validation_failures': failures,
        'readiness': [
            {'requirement': 'pitch_speed', 'status': 'unit_unconfirmed', 'detail': '56 tryout participant values preserved; no verified unit or individual professional pitches.'},
            {'requirement': 'batted_ball_exit_velocity', 'status': 'aggregate_only', 'detail': 'Two condition means/SDs, repeated selected good hits from 16 college men; N unit ambiguous.'},
            {'requirement': 'bat_speed', 'status': 'aggregate_only', 'detail': 'Two condition means/SDs; metal bats and pitching machine.'},
            {'requirement': 'pitch_movement_spin_location', 'status': 'unavailable', 'detail': 'No authorized competitive pitch-tracking stream obtained.'},
            {'requirement': 'launch_angle_spin_trajectory', 'status': 'unavailable', 'detail': 'No raw batted-ball launch-angle, spin or trajectory observations obtained.'},
            {'requirement': 'japanese_professional_representativeness', 'status': 'unresolved', 'detail': 'No NPB competitive sensor observations. Author names do not establish a cohort country.'},
            {'requirement': 'historical_comparison', 'status': 'selected_years_only', 'detail': 'Five historical MLB Game Log seasons, with era/rule and coverage differences explicit.'},
        ],
        'limits': ['Research participants are pseudonymous and not linked to professional-player IDs.',
                   'No synthetic pitches, inferred units, inferred Japanese nationality or reconstructed individual values.',
                   'Data validation passing does not establish simulation fidelity or external representativeness.',
                   'Historical Game Logs and recent plays are different coverage levels; do not pool blindly.',
                   'Source metadata and small research originals are preserved; automatic update promotion is disabled.'],
    }


def write_archive(path, files):
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.zip')
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, source in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with source.open('rb') as src, archive.open(info, 'w', force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        if Path(temporary).stat().st_size >= 100_000_000:
            raise CollectionError('Archive exceeds distribution limit; split before publication')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish(folder, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    names = ['quality.json', 'manifest.json', 'snapshot.json', 'plan.json', 'lock.json', 'policy.json',
             'source_review.json', 'murdock_table1.json']
    for name in names:
        shutil.copyfile(folder / name, report_dir / name)
    with closing(sqlite3.connect(folder / 'warehouse.sqlite3')) as db:
        db.row_factory = sqlite3.Row
        for filename, query in {
            'research_measurements.csv': 'SELECT * FROM research_measurements ORDER BY measurement_id',
            'research_datasets.csv': 'SELECT * FROM research_datasets ORDER BY dataset_id',
            'coverage.csv': 'SELECT g.season,c.coverage,count(*) games,coalesce(sum(q.play_rows),0) play_rows FROM games g JOIN stage5_game_coverage c USING(game_id) LEFT JOIN game_checks q USING(game_id) GROUP BY g.season,c.coverage ORDER BY g.season',
            'historical_comparison.csv': '''SELECT g.season,count(*) team_games,avg(g.visiting_runs+g.home_runs)/2 runs_per_team_game,
               sum(t.home_runs)*100.0/sum(t.at_bats) home_runs_per_100_at_bats,
               sum(t.strikeouts)*100.0/sum(t.at_bats) strikeouts_per_100_at_bats,
               avg(t.walks) walks_per_team_game,
               sum(CASE WHEN t.at_bats IS NULL OR t.home_runs IS NULL OR t.strikeouts IS NULL OR t.walks IS NULL THEN 1 ELSE 0 END) missing_stat_rows
               FROM games g JOIN game_team_stats t USING(game_id) GROUP BY g.season ORDER BY g.season''',
        }.items():
            export_csv(report_dir / filename, [dict(row) for row in db.execute(query)])
    docs = ['README.md', 'ATTRIBUTIONS.md']
    if any(not (report_dir / n).exists() for n in docs):
        raise CollectionError('Download documentation missing')
    files = {n: report_dir / n for n in [*names, *docs, 'research_measurements.csv', 'research_datasets.csv', 'coverage.csv', 'historical_comparison.csv']}
    files['warehouse.sqlite3'] = folder / 'warehouse.sqlite3'
    originals = {n: report_dir / n for n in [*names, *docs]}
    with closing(sqlite3.connect(folder / 'warehouse.sqlite3')) as db:
        research_hashes = {r[0] for r in db.execute("SELECT sha256 FROM artifacts WHERE artifact_id LIKE 'zenodo_%'")}
    for path in sorted((folder / 'originals').rglob('*')):
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            originals[name] = path
            # Small research originals accompany the DB for immediate inspection.
            # All original stages are preserved in the separate portable backup.
            if path.name in research_hashes or path.name.startswith('zenodo_'):
                files[name] = path
    bundle = report_dir / 'database_bundle.zip'
    original_bundle = report_dir / 'originals_bundle.zip'
    write_archive(bundle, files)
    write_archive(original_bundle, originals)
    write_json(report_dir / 'bundle.json', {'file': bundle.name, 'bytes': bundle.stat().st_size,
               'sha256': w.file_sha(bundle), 'database_sha256': w.file_sha(folder / 'warehouse.sqlite3'),
               'originals': {'file': original_bundle.name, 'bytes': original_bundle.stat().st_size,
                             'sha256': w.file_sha(original_bundle)}})


def run(args):
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    base = args.base_root / 'snapshots' / plan['base']['snapshot_id'] / 'warehouse.sqlite3'
    if not base.exists() or w.file_sha(base) != plan['base']['database_sha256']:
        raise CollectionError('Pinned Stage 3/4 base database missing or corrupt')
    transcription_path = args.plan.with_name('murdock_table1.json')
    review_path = args.plan.with_name('source_review.json')
    with w.run_lock(args.output):
        ledger = w.Ledger(args.output)
        run_id = ledger.start(w.file_sha(args.plan))
        temporary = None
        try:
            payloads, metas = acquire(args, plan, ledger, run_id)
            code = [Path(__file__), SCHEMA, Path(s.__file__), s.SCHEMA, Path(adapters.__file__),
                    Path(w.__file__), Path(__file__).with_name('fetch.py'), Path(__file__).with_name('__main__.py')]
            metadata = {'base': plan['base'], 'plan_sha256': w.file_sha(args.plan),
                        'lock_sha256': w.file_sha(args.plan.with_name('lock.json')),
                        'transform_sha256': digest(b''.join(p.name.encode() + b'\0' + p.read_bytes() for p in code)),
                        'transcription_sha256': w.file_sha(transcription_path), 'review_sha256': w.file_sha(review_path),
                        'runtime': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version}}
            key = digest(s.js(metadata).encode())[:24]
            parent = args.output / 'snapshots'
            parent.mkdir(exist_ok=True)
            target = parent / key
            if target.exists():
                info = json.loads((target / 'snapshot.json').read_text())
                if info['snapshot_id'] != key or any(w.file_sha(target / n) != sha for n, sha in info['files'].items()):
                    raise CollectionError('Committed Stage 5 snapshot is corrupt')
                report = json.loads((target / 'quality.json').read_text())
                state = 'reused'
            else:
                temporary = Path(tempfile.mkdtemp(dir=parent, prefix='.building-'))
                report = build_database(temporary / 'warehouse.sqlite3', base, plan, payloads, metas, args.cache,
                                        json.loads(transcription_path.read_text()), json.loads(review_path.read_text()), metadata)
                report.update(metadata, snapshot_id=key)
                write_json(temporary / 'quality.json', report)
                with closing(sqlite3.connect(temporary / 'warehouse.sqlite3')) as db:
                    all_metas = [json.loads(r[0]) for r in db.execute('SELECT metadata_json FROM artifacts ORDER BY artifact_id')]
                write_json(temporary / 'manifest.json', {'snapshot_id': key, **metadata, 'artifacts': all_metas})
                # Keep the base's licenses alongside the new ones.
                base_policy = json.loads((base.parent / 'policy.json').read_text())
                write_json(temporary / 'policy.json', {'base': base_policy, 'stage5': plan['rights']})
                for source, name in [(args.plan, 'plan.json'), (args.plan.with_name('lock.json'), 'lock.json'),
                                     (transcription_path, 'murdock_table1.json'), (review_path, 'source_review.json')]:
                    shutil.copyfile(source, temporary / name)
                # Preserve every source artifact, including all prior stages, for an actual portable backup.
                for meta in all_metas:
                    blob = args.cache / 'blobs' / meta['sha256']
                    if not blob.exists() or w.file_sha(blob) != meta['sha256']:
                        raise CollectionError('Original artifact missing or corrupt; portable backup incomplete')
                    dest = temporary / 'originals' / 'blobs' / meta['sha256']
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copyfile(blob, dest)
                    write_json(temporary / 'originals' / 'index' / (meta['id'] + '.json'), meta)
                files = {p.relative_to(temporary).as_posix(): w.file_sha(p) for p in sorted(temporary.rglob('*')) if p.is_file()}
                info = {'snapshot_id': key, 'files': files, **metadata}
                write_json(temporary / 'snapshot.json', info)
                os.replace(temporary, target)
                temporary = None
                state = 'committed'
            if w.file_sha(base) != plan['base']['database_sha256']:
                raise CollectionError('Base database unexpectedly changed')
            publish(target, args.report_dir)
            write_json(args.output / 'current.json', {'snapshot_id': key, 'database_sha256': info['files']['warehouse.sqlite3']})
            ledger.finish(run_id, state, key)
            print(s.js({'status': state, 'snapshot_id': key, 'counts': report['counts'],
                        'simulation_readiness': report['simulation_readiness']}))
            return 0
        except BaseException as exc:
            ledger.finish(run_id, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', message=type(exc).__name__)
            if temporary:
                shutil.rmtree(temporary)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'data_sources/stage5/plan.json')
    parser.add_argument('--base-root', type=Path, default=ROOT / 'data/research/warehouse')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/research/stage5')
    parser.add_argument('--cache', type=Path, default=ROOT / 'data/research/pilot/raw')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'data_sources/stage5')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--record-lock', action='store_true')
    args = parser.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print('Stage 5 interrupted; verified cache retained for resume', file=sys.stderr)
        return 130
    except Exception as exc:
        message = str(exc) if isinstance(exc, CollectionError) else 'Check schema, source metadata, cache and ledger'
        print(f'Stage 5 failed ({type(exc).__name__}): {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
