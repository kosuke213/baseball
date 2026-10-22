import csv
import gzip
import io
import json
import random
import sqlite3
import zipfile

import pytest

from baseball_simulation_lab.calibrated.api import CalibratedModel
from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.rules import canonical
from baseball_simulation_lab.fullgame import sources
from baseball_simulation_lab.fullgame.model import GameModel, NoRoute


def fixture_sources(tmp_path):
    from test_calibrated_model import sources as old_sources
    s5, s6, cache = old_sources(tmp_path)
    with sqlite3.connect(s5) as db:
        for year in (2023, 2024, 2025):
            artifact = f'retro_plays_{year}'
            meta = json.loads(db.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?', (artifact,)).fetchone()[0])
            with zipfile.ZipFile(cache / 'blobs' / meta['sha256']) as z:
                rows = list(csv.DictReader(io.TextIOWrapper(z.open(f'{year}plays.csv'))))
            for r in rows:
                r.update(ab=str(int(r['pa'] == '1' and r['walk'] == '0')), rbi_b='0', rbi1='0',
                         rbi2='1' if r['run2'] else '0', rbi3='0', rbi=r['runs'], sh='0', sf='0')
            content = io.StringIO(newline=''); writer = csv.DictWriter(content, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr(f'{year}plays.csv', content.getvalue())
            raw = payload.getvalue(); from hashlib import sha256
            meta['sha256'] = sha256(raw).hexdigest(); meta['bytes'] = len(raw)
            (cache / 'blobs' / meta['sha256']).write_bytes(raw)
            db.execute('UPDATE artifacts SET metadata_json=? WHERE artifact_id=?', (json.dumps(meta), artifact))
    config = {'stage5_database_sha256': sources.sha(s5), 'stage6_observations_sha256': sources.sha(s6)}
    return s5, s6, cache, config


def test_source_scoring_fit_excludes_future_and_retains_raw_rbi(tmp_path):
    s5, s6, cache, config = fixture_sources(tmp_path)
    a = sources.build(tmp_path / 'a', source5=s5, source6=s6, cache=cache, config=config, progress=lambda _: None)
    assert a['training_seasons'] == [2023, 2024]
    assert all('2025' not in r['artifact_id'] for r in a['sources'].values())
    actions = [p for group in a['groups'].values() for route in group for p in route['actions']]
    assert any(p['credit']['rbi_roles'] == ['1'] for p in actions)
    assert any(p['outcome'] == 'stolen_base' and not p['completed_pa'] for p in actions)
    with sqlite3.connect(s6) as db: db.execute("UPDATE windows SET outcome='home_run' WHERE season=2025")
    config['stage6_observations_sha256'] = sources.sha(s6)
    b = sources.build(tmp_path / 'b', source5=s5, source6=s6, cache=cache, config=config, progress=lambda _: None)
    assert canonical(a) == canonical(b)
    with pytest.raises(FileExistsError): sources.build(tmp_path / 'a')
    with pytest.raises(ValueError): sources.build(tmp_path / 'bad', source5=s5, source6=s6, cache=cache,
                                               config={**config, 'stage5_database_sha256': 'bad'})


def test_live_sampling_preserves_probabilities_and_seed_without_route_resampling(tmp_path):
    s5, s6, cache, config = fixture_sources(tmp_path)
    routes = sources.build(tmp_path / 'routes', source5=s5, source6=s6, cache=cache, config=config, progress=lambda _: None)
    from pathlib import Path
    base = CalibratedModel.load(Path(__file__).resolve().parents[1] / 'data_sources/stage7')
    m = GameModel(base, routes); frame = example_frame(0)
    assert m.predict_pa(frame) == base.predict_pa(frame)
    assert sum(m.predict_step(frame).values()) == pytest.approx(1)
    with pytest.raises(NoRoute): m.resolve_outcome(frame, 'triple', random.Random(2))
    a = m.resolve_outcome(frame, 'triple', random.Random(2), allow_assumptions=True)
    b = m.resolve_outcome(frame, 'triple', random.Random(2), allow_assumptions=True)
    assert a == b and a.plays[0].plan.source == 'assumption'
    assert any(r['empirical_n'] == 0 and r['probability'] > 0 for r in m.support_report(frame))
    with pytest.raises(NoRoute): m.resolve_outcome(example_frame(11), 'runner_only_end', random.Random(2), allow_assumptions=True)
    with pytest.raises(ValueError): GameModel(base, {**routes, 'training_seasons': [2023, 2025]})
    p = tmp_path / 'routes/routes.json.gz'; p.write_bytes(gzip.compress((tmp_path / 'routes/routes.json').read_bytes(), mtime=0))
    assert GameModel.load(Path(__file__).resolve().parents[1] / 'data_sources/stage7', p).version == m.version


def test_explicit_force_out_recovers_omitted_lob_without_guessing_base():
    from test_empirical import raw
    from baseball_simulation_lab.calibrated.identity import recover
    row = raw('5(2)/FO/G5.B-1', pa=1, outcome='fc', pre=2, post=3, before=('R1', 'R2', ''))
    row.update(run_b='', run1='', run2='', run3='', lob_id1='b1', lob_id2='', lob_id3='', k_safe='0')
    with pytest.raises(ValueError): recover(row)
    a = sources.recover_with_evidence(row)
    assert a['source_out_ids'] == ['R2']
    assert {m['role']: m['destination'] for m in a['moves']} == {'B': 'LOB', '1': 'LOB', '2': 'OUT'}
    assert a['recovery_note'] and row['lob_id2'] == ''  # immutable original mapping
    for change in ({'event': '5(2)/G5.B-1'}, {'runs': '1'}, {'outs_pre': '1', 'outs_post': '2'}):
        with pytest.raises(ValueError): sources.recover_with_evidence({**row, **change})
