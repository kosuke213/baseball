from argparse import Namespace
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

import pytest

from data_collection import stage5 as st, warehouse as w, warehouse_store as s
from data_collection.fetch import CollectionError, digest, write_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures/stage5'


def research_payloads():
    return {p.name: p.read_bytes() for p in FIXTURES.iterdir() if p.name.startswith('zenodo_')}


def research_db():
    db = sqlite3.connect(':memory:')
    db.executescript(s.SCHEMA.read_text())
    db.executescript(st.SCHEMA.read_text())
    for key, data in research_payloads().items():
        db.execute('INSERT INTO artifacts VALUES(?,?,?,?)', (key, digest(data), len(data), '{}'))
    return db


def test_actual_tryout_preserves_56_people_and_leaves_undocumented_units_unknown():
    with closing(research_db()) as db:
        st.load_tryout(db, research_payloads())
        assert db.execute('SELECT reported_participants,observed_identifiable_participants FROM research_datasets').fetchone() == (64, 56)
        assert db.execute('SELECT count(*) FROM research_measurements').fetchone()[0] == 616
        values = db.execute("SELECT value,source_unit,normalized_value,statistic FROM research_measurements WHERE metric='velocity'").fetchall()
        assert len(values) == 56 and all(r[1:] == (None, None, 'individual') for r in values)
        assert all(r[0] > 100 for r in values)
        assert db.execute('SELECT count(*) FROM research_confirmed_speeds').fetchone()[0] == 0
        assert db.execute("SELECT participant_id FROM research_participants ORDER BY source_id LIMIT 1").fetchone()[0].startswith('zenodo_5796004:participant:')
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_actual_docx_keeps_participant_summaries_correlations_and_phase_separate():
    with closing(research_db()) as db:
        st.load_wada(db, research_payloads())
        counts = dict(db.execute('SELECT statistic,count(*) FROM research_measurements GROUP BY statistic'))
        assert counts == {'participant_summary': 192, 'cohort_summary': 12, 'correlation': 12, 'pitch_cycle_summary': 12}
        assert db.execute('SELECT count(*) FROM research_participants').fetchone()[0] == 16
        assert db.execute('SELECT country FROM research_datasets').fetchone()[0] is None
        assert db.execute("SELECT value,sd,source_unit FROM research_measurements WHERE participant_id LIKE '%:S1' AND metric='angle:Extension (+)'").fetchone() == (23.1, 0.9, 'deg')
        assert db.execute("SELECT value,sd,source_unit FROM research_measurements WHERE participant_id LIKE '%:S1' AND metric='angular_velocity:Extension (+)'").fetchone() == (675.1, 28.6, 'deg/s')
        assert db.execute('SELECT count(*) FROM research_measurements WHERE reported_n IS NOT NULL').fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM research_measurements WHERE metric='velocity'").fetchone()[0] == 0


def test_actual_pdf_table_transcription_and_conversion_dont_generate_raw_hits():
    transcription = json.loads((ROOT / 'data_sources/stage5/murdock_table1.json').read_text())
    with closing(research_db()) as db:
        st.load_murdock(db, research_payloads(), transcription)
        rows = db.execute("SELECT value,sd,reported_n,normalized_value,normalized_sd,statistic,n_unit FROM research_measurements WHERE metric='exit_velocity' ORDER BY condition").fetchall()
        assert [r[:3] for r in rows] == [(148.7, 12.1, 40), (151.4, 9.8, 41)]
        assert rows[1][3] == pytest.approx(151.4 / 3.6)
        assert rows[1][4] == pytest.approx(9.8 / 3.6)
        assert all(r[5] == 'cohort_summary' and 'ambiguous' in r[6] for r in rows)
        assert db.execute('SELECT count(*) FROM research_confirmed_speeds').fetchone()[0] == 4
        assert db.execute('SELECT count(*) FROM research_participants').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM research_measurements').fetchone()[0] == 12
        broken = research_payloads(); broken['zenodo_16050919_data'] += b'changed'
        with pytest.raises(CollectionError, match='original PDF'):
            st.load_murdock(db, broken, transcription)


@pytest.mark.parametrize('field,value', [('access_right', 'restricted'), ('license', {'id': 'cc-by-nc-sa-4.0'})])
def test_source_metadata_gates_reject_restricted_and_noncommercial_data(field, value):
    plan = json.loads((ROOT / 'data_sources/stage5/plan.json').read_text())
    spec = next(v for v in plan['artifacts'] if v['id'] == 'zenodo_5796004_data')
    metadata = json.loads(research_payloads()['zenodo_5796004_metadata'])
    st.verify_zenodo(json.dumps(metadata).encode(), spec)
    metadata['metadata'][field] = value
    with pytest.raises(CollectionError, match='license is unconfirmed'):
        st.verify_zenodo(json.dumps(metadata).encode(), spec)


def test_mismatched_file_and_record_version_are_rejected():
    plan = json.loads((ROOT / 'data_sources/stage5/plan.json').read_text())
    spec = next(v for v in plan['artifacts'] if v['id'] == 'zenodo_5796004_data')
    metadata = research_payloads()['zenodo_5796004_metadata']
    for field, value in [('original_filename', 'another.csv'), ('expected_md5', '0' * 32), ('upstream_version', 'different')]:
        changed = dict(spec, **{field: value})
        with pytest.raises(CollectionError):
            st.verify_zenodo(metadata, changed)


def test_failed_evidence_skips_dependent_network_requests_and_does_not_write_lock(tmp_path, monkeypatch):
    payloads = research_payloads()
    specs = json.loads((ROOT / 'data_sources/stage5/plan.json').read_text())
    specs['artifacts'] = [v for v in specs['artifacts'] if v['id'].startswith('zenodo_5796004')]
    args = Namespace(plan=tmp_path / 'plan.json', cache=tmp_path / 'cache', output=tmp_path / 'out', record_lock=True, offline=False)
    write_json(args.plan, specs); args.output.mkdir()
    calls = []
    class Collector:
        cache_hits = 0
        network_requests = 0
        def __init__(self, *args, **kwargs): pass
        def fetch(self, spec):
            calls.append(spec['id'])
            raise CollectionError('evidence offline')
    monkeypatch.setattr(st, 'Collector', Collector)
    ledger = w.Ledger(args.output); run = ledger.start(w.file_sha(args.plan))
    with pytest.raises(CollectionError, match='acquisition failed'):
        st.acquire(args, specs, ledger, run)
    assert calls == ['zenodo_5796004_metadata']
    assert not args.plan.with_name('lock.json').exists()
    assert len(json.loads((args.output / 'last_acquisition.json').read_text())['failures']) == 2


def test_quality_never_equates_integrity_with_model_readiness():
    with closing(research_db()) as db:
        payloads = research_payloads()
        st.load_tryout(db, payloads)
        st.load_wada(db, payloads)
        st.load_murdock(db, payloads, json.loads((ROOT / 'data_sources/stage5/murdock_table1.json').read_text()))
        report = st.quality(db)
        assert report['data_validation'] == 'pass'
        assert report['simulation_readiness'] == 'partial_research_only'
        states = {v['requirement']: v['status'] for v in report['readiness']}
        assert states['pitch_movement_spin_location'] == 'unavailable'
        assert states['japanese_professional_representativeness'] == 'unresolved'


def fixture_run(tmp_path, monkeypatch):
    from test_warehouse import fixture_data
    g, _, base_payload, base_metas = fixture_data()
    plan = json.loads((ROOT / 'data_sources/stage5/plan.json').read_text())
    plan['years'] = [2019]
    plan['artifacts'] = [v for v in plan['artifacts'] if not v['id'].startswith('retro_gl_') or v['id'] == 'retro_gl_2019']
    root = tmp_path / 'base'; base_dir = root / 'snapshots' / plan['base']['snapshot_id']; base_dir.mkdir(parents=True)
    s.build(base_dir / 'warehouse.sqlite3', {'years': [2024]}, base_payload, base_metas, {}, lambda _: None)
    write_json(base_dir / 'policy.json', {'test': 'fixtures only'})
    plan['base']['database_sha256'] = w.file_sha(base_dir / 'warehouse.sqlite3')
    cache = tmp_path / 'cache'; (cache / 'blobs').mkdir(parents=True)
    for meta in base_metas:
        (cache / 'blobs' / meta['sha256']).write_bytes(base_payload[meta['id']])
    payloads = research_payloads()
    import csv, io
    g['field_001'] = '20190401'
    out = io.StringIO(newline=''); csv.writer(out).writerow(list(g.values()))
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, 'w') as archive: archive.writestr('gl2019.txt', out.getvalue())
    payloads.update(retro_gl_2019=zipped.getvalue(), retro_notice=b'fixture notice', retro_csv_docs=b'fixture docs', retro_gamelog_docs=b'fixture fields')
    metas = {spec['id']: {**spec, 'sha256': digest(payloads[spec['id']]), 'bytes': len(payloads[spec['id']])} for spec in plan['artifacts']}
    for key, data in payloads.items():
        (cache / 'blobs' / digest(data)).write_bytes(data)
    path = tmp_path / 'plan.json'; write_json(path, plan)
    for name in ['murdock_table1.json', 'source_review.json']:
        shutil.copyfile(ROOT / 'data_sources/stage5' / name, tmp_path / name)
    reports = tmp_path / 'reports'; reports.mkdir()
    for name in ['README.md', 'ATTRIBUTIONS.md']: (reports / name).write_text('Test fixtures only')
    class Collector:
        network_requests = 0
        def __init__(self, *args, **kwargs): self.cache_hits = 0
        def fetch(self, spec):
            self.cache_hits += 1
            data = payloads[spec['id']]
            if spec.get('expected_sha256') and digest(data) != spec['expected_sha256']:
                raise CollectionError('Fixture pin mismatch')
            return data, metas[spec['id']]
    monkeypatch.setattr(st, 'Collector', Collector)
    return Namespace(plan=path, cache=cache, output=tmp_path / 'out', base_root=root, report_dir=reports, offline=True, record_lock=True)


def test_integration_preserves_base_and_old_plays_scopes_historical_logs_and_backs_up_originals(tmp_path, monkeypatch):
    args = fixture_run(tmp_path, monkeypatch)
    assert st.run(args) == 0
    pointer = json.loads((args.output / 'current.json').read_text())
    folder = args.output / 'snapshots' / pointer['snapshot_id']
    with closing(sqlite3.connect(folder / 'warehouse.sqlite3')) as db:
        assert db.execute('SELECT count(*) FROM games').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM plays').fetchone()[0] == 18
        assert db.execute("SELECT count(*) FROM game_checks").fetchone()[0] == 1
        assert dict(db.execute('SELECT coverage,count(*) FROM stage5_game_coverage GROUP BY coverage')) == {'game_log_only': 1, 'validated_plays': 1}
        assert db.execute('SELECT count(*) FROM research_measurements').fetchone()[0] == 856
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        originals = db.execute('SELECT artifact_id,sha256 FROM artifacts').fetchall()
    with zipfile.ZipFile(args.report_dir / 'originals_bundle.zip') as archive:
        for artifact, sha in originals:
            assert digest(archive.read('originals/blobs/' + sha)) == sha
            assert json.loads(archive.read('originals/index/' + artifact + '.json'))['sha256'] == sha
    with zipfile.ZipFile(args.report_dir / 'database_bundle.zip') as archive:
        assert digest(archive.read('warehouse.sqlite3')) == pointer['database_sha256']
        assert any(n.startswith('originals/index/zenodo_') for n in archive.namelist())
    old_bundle = w.file_sha(args.report_dir / 'database_bundle.zip')
    old_originals = w.file_sha(args.report_dir / 'originals_bundle.zip')
    assert st.run(args) == 0
    assert w.file_sha(args.report_dir / 'database_bundle.zip') == old_bundle
    assert w.file_sha(args.report_dir / 'originals_bundle.zip') == old_originals
    assert json.loads((args.output / 'current.json').read_text()) == pointer
    original_quality = (folder / 'quality.json').read_bytes()
    (folder / 'quality.json').write_bytes(original_quality + b'\n')
    with pytest.raises(CollectionError, match='snapshot is corrupt'):
        st.run(args)
    assert json.loads((args.output / 'current.json').read_text()) == pointer
    (folder / 'quality.json').write_bytes(original_quality)
    # A failure after acquisition cannot replace the published snapshot or modify the base.
    path = args.plan.with_name('murdock_table1.json'); path.write_text(path.read_text() + '\n')
    def fail(*args, **kwargs): raise CollectionError('simulated parser failure')
    monkeypatch.setattr(st, 'build_database', fail)
    with pytest.raises(CollectionError, match='simulated parser failure'): st.run(args)
    assert json.loads((args.output / 'current.json').read_text()) == pointer
    assert not list((args.output / 'snapshots').glob('.building-*'))
    plan = json.loads(args.plan.read_text())
    assert w.file_sha(args.base_root / 'snapshots' / plan['base']['snapshot_id'] / 'warehouse.sqlite3') == plan['base']['database_sha256']


def test_plan_cannot_silently_expand_hosts_years_or_disallowed_rights():
    plan = json.loads((ROOT / 'data_sources/stage5/plan.json').read_text()); st.validate_plan(plan)
    changed = copy.deepcopy(plan); changed['years'].append(2023)
    with pytest.raises(CollectionError): st.validate_plan(changed)
    changed = copy.deepcopy(plan); changed['artifacts'][0]['url'] = 'https://unreviewed.example/data'
    with pytest.raises(CollectionError): st.validate_plan(changed)
    changed = copy.deepcopy(plan); changed['rights']['zenodo_5796004']['warehouse_collection_allowed'] = False
    with pytest.raises(CollectionError): st.validate_plan(changed)
