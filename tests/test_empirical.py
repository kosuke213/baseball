from argparse import Namespace
from contextlib import closing
import copy
import csv
import io
import json
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
import zipfile

import numpy as np
import pytest

from baseball_simulation_lab.empirical import EmpiricalModel
from baseball_simulation_lab.empirical import analysis, common as c, extract as ex, fit, pipeline
from data_collection.fetch import digest, write_json


ROOT = Path(__file__).resolve().parents[1]


def raw(event, *, pa=0, outcome=None, pre=0, post=0, before=('', '', ''), after=('', '', ''), runs=0):
    row = {k: '0' for k in [*c.RAW_OUTCOMES, 'pa', 'iw', 'k_safe']}
    row.update(event=event, gid='TST202304010', pn='1', inning='1', top_bot='0', vis_home='0',
               batter='b1', pitcher='p1', bathand='R', pithand='L', score_v='0', score_h='0',
               outs_pre=str(pre), outs_post=str(post), runs=str(runs), pa=str(pa))
    if outcome:
        row[outcome] = '1'
    row.update({f'br{i}_pre': v for i, v in enumerate(before, 1)})
    row.update({f'br{i}_post': v for i, v in enumerate(after, 1)})
    return row


def source_fixture(tmp_path):
    source = tmp_path / 'source.sqlite3'
    cache = tmp_path / 'cache'; (cache / 'blobs').mkdir(parents=True)
    with sqlite3.connect(source) as db:
        db.executescript('''
          CREATE TABLE artifacts(artifact_id TEXT,metadata_json TEXT);
          CREATE TABLE games(game_id TEXT PRIMARY KEY,season INTEGER);
          CREATE TABLE game_checks(game_id TEXT,status TEXT);
          CREATE TABLE player_matches(retrosheet_id TEXT,status TEXT);
          CREATE TABLE plays(game_id TEXT,play_number INTEGER,artifact_id TEXT,source_row INTEGER,
            pbp_type TEXT,plate_appearance INTEGER,strikeout INTEGER,home_run INTEGER,runs INTEGER,
            outs_pre INTEGER,outs_post INTEGER,balls INTEGER,strikes INTEGER,pitch_count INTEGER,
            pitches_raw TEXT,batter_hand TEXT,pitcher_hand TEXT,batter_retro_id TEXT,pitcher_retro_id TEXT);
          CREATE VIEW analysis_plays AS SELECT * FROM plays;
        ''')
        db.executemany('INSERT INTO player_matches VALUES(?,?)', [('b1', 'matched'), ('p1', 'matched')])
        for year in (2023, 2024, 2025):
            rows = [raw('NP'), raw('W', pa=1, outcome='walk', after=('r1', '', '')),
                    raw('SB2', before=('r1', '', ''), after=('', 'r1', '')),
                    raw('S8.2-H', pa=1, outcome='single', before=('', 'r1', ''), after=('b1', '', ''), runs=1),
                    raw('63/G6', pa=1, outcome='othout', pre=0, post=1, before=('b1', '', ''), after=('b1', '', '')),
                    raw('64(1)3/GDP', pa=1, outcome='othout', pre=1, post=3, before=('b1', '', ''))]
            artifact = f'retro_plays_{year}'
            game = f'retrosheet:game:TST{year}04010'
            db.execute('INSERT INTO games VALUES(?,?)', (game, year))
            db.execute('INSERT INTO game_checks VALUES(?,?)', (game, 'pass'))
            for index, row in enumerate(rows, 1):
                row.update(gid=game.removeprefix('retrosheet:game:'), pn=str(index), score_v='1' if index >= 5 else '0')
                db.execute('INSERT INTO plays VALUES(' + ','.join('?' for _ in range(19)) + ')',
                           (game, index, artifact, index + 1, 'full', int(row['pa']), int(row['k']), int(row['hr']), int(row['runs']),
                            int(row['outs_pre']), int(row['outs_post']), 0, 0, None if index == 1 else 1,
                            '' if index == 1 else 'X', 'R', 'L', 'b1', 'p1'))
            content = io.StringIO(newline=''); writer = csv.DictWriter(content, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f'{year}plays.csv', content.getvalue())
            data = payload.getvalue(); sha = digest(data)
            (cache / 'blobs' / sha).write_bytes(data)
            meta = {'id': artifact, 'sha256': sha, 'bytes': len(data), 'url': 'https://example.test/' + artifact,
                    'purpose': 'data', 'rights_snapshot': {'attribution': 'Test fixtures only'}}
            db.execute('INSERT INTO artifacts VALUES(?,?)', (artifact, json.dumps(meta)))
    return source, cache


def test_classification_uses_exhaustive_indicators_not_event_string_guessing():
    row = raw('K+WP.B-1', pa=1, outcome='k')
    assert ex.classify(row) == ('strikeout', 'completed_pa')
    assert ex.classify(raw('CS2(26)')) == (None, 'caught_stealing')
    assert ex.classify(raw('NP')) == (None, 'non_play')
    for bad in [dict(row, single='1'), dict(row, k='0'), dict(row, k='2')]:
        with pytest.raises(ValueError): ex.classify(bad)


def test_real_play_and_window_units_are_distinct_and_source_rows_are_preserved(tmp_path):
    source, cache = source_fixture(tmp_path)
    original = c.sha_file(source)
    path = tmp_path / 'derived.sqlite3'
    audit = ex.extract(path, source, cache, original)
    assert c.sha_file(source) == original
    assert audit['derived_counts'] == {'plays': 15, 'windows': 12, 'exclusions': 3}
    assert audit['support_exception_count'] == 0
    assert audit['windows_with_intermediate_runner_events'] == 3
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT first_pn,last_pn,pre_state,post_state,runs,play_rows,first_source_row,last_source_row FROM windows WHERE first_pn=3 ORDER BY season LIMIT 1').fetchone() == (3, 4, 1, 1, 1, 2, 4, 5)
        assert db.execute('SELECT count(*) FROM plays WHERE pa=1').fetchone()[0] == 12
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    bad = cache / 'blobs' / audit['raw_artifacts'][0]['sha256']
    bad.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='original missing/corrupt'):
        ex.extract(tmp_path / 'bad.sqlite3', source, cache, original)


def add_play(db, pn, pre, post, runs, pa, outcome, *, inning=1, half=0, game='g', diff=0, batter='b'):
    db.execute('INSERT INTO plays VALUES(' + ','.join('?' for _ in range(21)) + ')',
               (game, pn, 2023, inning, half, pre, post, runs, pa, outcome, 'completed_pa' if pa else 'stolen_base',
                'test', batter, 'p', 'B', 'R', diff, 0, 0, 'source', pn + 1))


def test_automatic_runner_is_a_start_state_and_third_out_does_not_complete_a_pa():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(ex.SCHEMA); db.row_factory = sqlite3.Row
        add_play(db, 2, 2, 4, 0, 0, None, inning=10)
        add_play(db, 3, 4, 0, 2, 1, 'home_run', inning=10)
        add_play(db, 4, 17, 24, 0, 0, None, inning=10, half=1)
        audit = ex.make_windows(db)
        assert audit['extra_half_starts_runner_on_second'] == 1
        assert audit['runner_only_end_windows'] == 1
        assert db.execute('SELECT pre_state,runs,outcome,completed_pa FROM windows ORDER BY first_pn').fetchall()[0][:] == (2, 2, 'home_run', 1)
        last = db.execute('SELECT outcome,completed_pa FROM windows ORDER BY first_pn DESC').fetchone()
        assert tuple(last) == ('runner_only_end', 0)


def test_walkoff_disappearing_runners_are_censored_not_corrected_or_trained():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(ex.SCHEMA); db.row_factory = sqlite3.Row
        # Source has erased both surviving runners at a walkoff single.
        add_play(db, 1, 23, 16, 1, 1, 'single', inning=9, half=1)
        audit = ex.make_windows(db)
        assert audit['censored_walkoff'] == 1 and audit['support_exception_count'] == 0
        assert tuple(db.execute('SELECT post_state,transition_observed,censor_reason FROM windows').fetchone()) == (16, 0, 'walkoff')
        batch = fit.load_batch(db)
        assert len(batch.target) == 1 and not batch.transition_valid[0]
        kernels = fit.fit_kernels(batch, 10)
        assert all(row['n'] == 0 for row in kernels['conditional'].values())


def test_unexplained_state_discontinuities_are_rejected():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(ex.SCHEMA); db.row_factory = sqlite3.Row
        add_play(db, 1, 1, 2, 0, 0, None)
        add_play(db, 2, 0, 0, 1, 1, 'home_run')
        with pytest.raises(ValueError, match='discontinuity'):
            ex.make_windows(db)


def prepared(tmp_path):
    source, cache = source_fixture(tmp_path)
    path = tmp_path / 'derived.sqlite3'
    ex.extract(path, source, cache, c.sha_file(source))
    return source, cache, path


def test_future_labels_cannot_enter_fit_and_changed_2025_labels_do_not_change_tables(tmp_path):
    _, _, path = prepared(tmp_path)
    config = {'context_alphas': [25, 100], 'player_weights': [0, 0.5], 'kernel_alphas': [1, 10],
              'seed': 626, 'bootstrap_repetitions': 10}
    one, two = tmp_path / 'one', tmp_path / 'two'; one.mkdir(); two.mkdir()
    with closing(sqlite3.connect(path)) as db:
        batch = fit.load_batch(db)
        with pytest.raises(ValueError, match='evaluation seasons'): fit.count_tables(batch)
        with pytest.raises(ValueError, match='evaluation seasons'): fit.fit_kernels(batch, 10)
        analysis.analyze(db, one, config, lambda _: None)
        db.execute("UPDATE windows SET outcome='home_run' WHERE season=2025 AND completed_pa=1")
        analysis.analyze(db, two, config, lambda _: None)
    assert (one / 'model.json').read_bytes() == (two / 'model.json').read_bytes()
    assert (one / 'kernels.json').read_bytes() == (two / 'kernels.json').read_bytes()
    assert (one / 'validation_grid.csv').read_bytes() == (two / 'validation_grid.csv').read_bytes()
    assert (one / 'transition_validation_grid.csv').read_bytes() == (two / 'transition_validation_grid.csv').read_bytes()


def test_scoring_definitions_are_proper_and_no_realized_outcome_is_used_for_transitions():
    p = np.array([[0.75, 0.25], [0.25, 0.75]])
    ll, brier = fit.score(np.array([0, 1]), p)
    assert np.allclose(ll, -np.log(0.75))
    assert np.allclose(brier, 0.125)
    with pytest.raises(ValueError): fit.score(np.array([0]), np.array([[0.0, 1.0]]))
    a = fit.bootstrap_difference(['a', 'a', 'b'], np.array([1., 2., 3.]), np.ones(3), repetitions=10)
    assert a == fit.bootstrap_difference(['a', 'a', 'b'], np.array([1., 2., 3.]), np.ones(3), repetitions=10)


def test_api_matches_offline_predictions_and_joint_scoring_does_not_consume_outcome_labels(tmp_path):
    _, _, path = prepared(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        batch = fit.load_batch(db)
    train = batch.subset(batch.season < 2025)
    test = batch.subset(batch.season == 2025)
    model = fit.fit_tables(fit.count_tables(train), context_alpha=25, player_weight=0.5, training_seasons=[2023, 2024])
    kernels = fit.fit_kernels(train, 10)
    api = EmpiricalModel(model, kernels)
    p = fit.predict(test, model)
    # The first test window is a walk with a known pre-window actor.
    live = api.predict_step(outs=0, bases=0, batter_hand='R', pitcher_hand='L', inning=1,
                            batting_score_diff=0, half=0, batter_id='b1', pitcher_id='p1')
    assert np.allclose(p[0], list(live.values()))
    original = fit.transition_scores(test, p, kernels)
    test.target[:] = c.OUTCOMES.index('home_run')
    changed = fit.transition_scores(test, p, kernels)
    assert np.array_equal(original['joint'][0], changed['joint'][0])
    assert np.array_equal(original['runs'][1], changed['runs'][1])


def test_pipeline_api_archive_reuse_integrity_and_failure_preserve_prior(tmp_path, monkeypatch):
    source, cache = source_fixture(tmp_path)
    config = json.loads((ROOT / 'data_sources/stage6/config.json').read_text())
    config.update(input_database_sha256=c.sha_file(source), context_alphas=[25], player_weights=[0.5], kernel_alphas=[10], bootstrap_repetitions=10)
    config_path = tmp_path / 'config.json'; write_json(config_path, config)
    reports = tmp_path / 'reports'; reports.mkdir()
    for name in ('README.md', 'ATTRIBUTIONS.md'): (reports / name).write_text('Test fixtures only')
    args = Namespace(source=source, cache=cache, config=config_path, output=tmp_path / 'out', report_dir=reports)
    before = c.sha_file(source)
    assert pipeline.run(args) == 0
    pointer = (args.output / 'current.json').read_bytes()
    bundle = c.sha_file(reports / 'stage6_bundle.zip')
    assert pipeline.run(args) == 0
    assert c.sha_file(reports / 'stage6_bundle.zip') == bundle
    assert c.sha_file(source) == before
    model = EmpiricalModel.load(reports)
    features = dict(outs=1, bases=1, inning=5, half=0, batting_score_diff=0, batter_hand='B', pitcher_hand='R', batter_id='unseen')
    assert sum(model.predict_pa(**features).values()) == pytest.approx(1)
    assert sum(row['probability'] for row in model.predict_next_state_runs(**features)) == pytest.approx(1)
    assert sum(row['probability'] for row in model.predict_state_baseline(outs=1, bases=1)) == pytest.approx(1)
    assert model.sample_step(random.Random(1), **features) == model.sample_step(random.Random(1), **features)
    for pre in range(24):
        outs, bases = divmod(pre, 8)
        for _ in range(20):
            result = model.sample_step(random.Random(pre * 100 + _), outs=outs, bases=bases)
            post = 24 if result.half_ended else result.outs_after * 8 + result.bases_after
            assert (post, result.runs) in c.legal_targets(pre, result.outcome)
    with zipfile.ZipFile(reports / 'stage6_bundle.zip') as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read('manifest.json'))
        for name, sha in manifest['files'].items(): assert digest(archive.read(name)) == sha
    # The API still imports and predicts with site packages (including NumPy) disabled.
    command = 'from baseball_simulation_lab.empirical import EmpiricalModel; m=EmpiricalModel.load(' + repr(str(reports)) + '); assert abs(sum(m.predict_pa(outs=0,bases=0).values())-1)<1e-10'
    subprocess.run([sys.executable, '-S', '-c', command], cwd=ROOT, check=True)
    original = (reports / 'model.json').read_bytes(); (reports / 'model.json').write_bytes(original + b'\n')
    with pytest.raises(ValueError, match='checksum'): EmpiricalModel.load(reports)
    (reports / 'model.json').write_bytes(original)
    # A code-independent document change requires a new snapshot; simulated build failure keeps the old pointer.
    (reports / 'README.md').write_text('Changed documentation')
    monkeypatch.setattr(pipeline, 'extract', lambda *a, **k: (_ for _ in ()).throw(ValueError('simulated failure')))
    with pytest.raises(ValueError, match='simulated failure'): pipeline.run(args)
    assert (args.output / 'current.json').read_bytes() == pointer
    assert not list((args.output / 'snapshots').glob('.building-*'))


def test_paths_and_feature_contract_reject_dangerous_outputs_or_terminal_features(tmp_path):
    with pytest.raises(ValueError, match='protected'):
        pipeline.protect_paths(ROOT / 'data/research/stage5', tmp_path, tmp_path / 'source')
    with pytest.raises(TypeError):
        c.feature_keys(outs=0, bases=0, inning=1, half=0, batting_score_diff=0, batter_hand='R', pitcher_hand='R', terminal_count='02')
    assert c.feature_keys(outs=0, bases=0, inning=1, half=0, batting_score_diff=0, batter_hand='B', pitcher_hand='R')['hands'] == '["B","R"]'
    for outs, bases in [(-1, 0), (3, 0), (0, 8), (True, 0)]:
        with pytest.raises(ValueError): c.state(outs, bases)
