from argparse import Namespace
from contextlib import closing
from dataclasses import replace
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

from data_collection.fetch import digest, write_json
from baseball_simulation_lab.empirical import extract as ex, fit
from baseball_simulation_lab.calibrated import calibration, evaluation, identity, pipeline
from baseball_simulation_lab.calibrated.api import CalibratedModel, WindowResult, calibrate
from baseball_simulation_lab.calibrated.replay import Journal
from baseball_simulation_lab.calibrated.rules import UnsupportedRule, apply_plan, conservative_plan

ROOT = Path(__file__).resolve().parents[1]


def sources(tmp_path):
    from test_empirical import raw
    cache = tmp_path / 'cache'; (cache / 'blobs').mkdir(parents=True)
    s5, s6 = tmp_path / 's5.sqlite3', tmp_path / 's6.sqlite3'
    with sqlite3.connect(s5) as src, sqlite3.connect(s6) as derived:
        src.executescript('CREATE TABLE plays(game_id TEXT,event_date TEXT); CREATE TABLE artifacts(artifact_id TEXT,metadata_json TEXT);')
        derived.executescript(ex.SCHEMA)
        for year in (2023, 2024, 2025):
            all_rows = []
            for month in (4, 8):
                game = f'retrosheet:game:TST{year}{month:02}010'
                rows = [raw('W', pa=1, outcome='walk', after=('a0', '', '')),
                        raw('SB2', before=('a0', '', ''), after=('', 'a0', '')),
                        raw('S8.2-H', pa=1, outcome='single', before=('', 'a0', ''), after=('a1', '', ''), runs=1),
                        raw('63/G6', pa=1, outcome='othout', post=1, before=('a1', '', ''), after=('a1', '', '')),
                        raw('64(1)3/GDP', pa=1, outcome='othout', pre=1, post=3, before=('a1', '', ''))]
                batters = ['a0', 'a1', 'a1', 'a2', 'a3']
                for index, row in enumerate(rows, 1):
                    row.update(gid=game.removeprefix('retrosheet:game:'), pn=str(index), batter=batters[index - 1], pitcher='P',
                               date=f'{year}{month:02}01', score_v='1' if index >= 4 else '0',
                               gdp='1' if index == 5 else '0', run_b='', run1='', run2='a0' if index == 3 else '', run3='',
                               lob_id1='', lob_id2='', lob_id3='', k_safe='0')
                    number = len(all_rows) + 2
                    outcome, kind = ex.classify(row)
                    pre = int(row['outs_pre']) * 8 + sum(1 << (i - 1) for i in (1, 2, 3) if row[f'br{i}_pre'])
                    post = 24 if row['outs_post'] == '3' else int(row['outs_post']) * 8 + sum(1 << (i - 1) for i in (1, 2, 3) if row[f'br{i}_post'])
                    derived.execute('INSERT INTO plays VALUES(' + ','.join('?' for _ in range(21)) + ')',
                        (game, index, year, 1, 0, pre, post, int(row['runs']), int(row['pa']), outcome, kind, row['event'],
                         row['batter'], 'P', 'R', 'L', int(row['score_v']), 0, 0, f'retro_plays_{year}', number))
                    all_rows.append(row)
                    src.execute('INSERT INTO plays VALUES(?,?)', (game, f'{year}-{month:02}-01'))
            content = io.StringIO(newline=''); writer = csv.DictWriter(content, fieldnames=list(all_rows[0]))
            writer.writeheader(); writer.writerows(all_rows)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr(f'{year}plays.csv', content.getvalue())
            payload = archive.getvalue(); sha = digest(payload)
            (cache / 'blobs' / sha).write_bytes(payload)
            src.execute('INSERT INTO artifacts VALUES(?,?)', (f'retro_plays_{year}', json.dumps({'id': f'retro_plays_{year}', 'sha256': sha, 'bytes': len(payload), 'url': 'https://example.test/fixture'})))
        derived.row_factory = sqlite3.Row
        assert ex.make_windows(derived)['support_exception_count'] == 0
    return s5, s6, cache


def experiment_config():
    return {'temperatures': [0.8, 1, 1.2], 'league_weights': [0, 0.5], 'ece_guard_tolerance': 0.0005,
            'seed': 726, 'bootstrap_repetitions': 10, 'simulation_halves': 2}


def prepared(tmp_path):
    s5, s6, cache = sources(tmp_path)
    path = tmp_path / 'identity.sqlite3'
    audit = identity.collect(path, s6, s5, cache)
    assert audit['supported_windows'] == 24 and audit['reconstructed_windows'] == 24
    return s5, s6, cache, path


def test_identity_templates_and_calibration_never_fit_reference_labels(tmp_path):
    _, s6, _, ids = prepared(tmp_path)
    one, two = tmp_path / 'one', tmp_path / 'two'; one.mkdir(); two.mkdir()
    with sqlite3.connect(ids) as d, sqlite3.connect(s6) as source:
        dates = {g: (f, l) for g, f, l in d.execute('SELECT game_id,min(first_date),max(last_date) FROM windows GROUP BY game_id')}
        batch = fit.load_batch(source)
        calibration.run_calibration(batch, dates, one, experiment_config())
        original = identity.fit_templates(d, [2023, 2024])
        with pytest.raises(ValueError): identity.fit_templates(d, [2023, 2025])
        d.execute("UPDATE windows SET pattern_sha=NULL,supported=0 WHERE season=2025")
        assert original == identity.fit_templates(d, [2023, 2024])
        batch.target[(batch.season == 2025) & (batch.target < 14)] = 3  # future HR labels
        calibration.run_calibration(batch, dates, two, experiment_config())
        assert (one / 'calibration.json').read_bytes() == (two / 'calibration.json').read_bytes()
        assert (one / 'base_model.json').read_bytes() == (two / 'base_model.json').read_bytes()
        assert (one / 'calibration_fit_grid.csv').read_bytes() == (two / 'calibration_fit_grid.csv').read_bytes()


def test_resumed_game_crossing_cutoff_is_not_calibration_or_selection(tmp_path):
    _, s6, _, ids = prepared(tmp_path)
    with sqlite3.connect(ids) as d, sqlite3.connect(s6) as source:
        dates = {g: (f, l) for g, f, l in d.execute('SELECT game_id,min(first_date),max(last_date) FROM windows GROUP BY game_id')}
        batch = fit.load_batch(source)
        selected = next(g for g in dates if '202404' in g)
        dates[selected] = ('2024-06-30', '2024-08-01')
        a, b = calibration.date_splits(batch, dates)
        assert not any(a[i] or b[i] for i, g in enumerate(batch.games) if g == selected)
        assert not np.any(a & b)


def test_numpy_and_standard_library_calibration_and_rule_masks_agree():
    p = np.array([[0.1, 0.2, 0.7, 0.0], [0.0, 0.3, 0.4, 0.3]])
    q = np.array([[0.2, 0.3, 0.5, 0.0], [0.0, 0.4, 0.2, 0.4]])
    settings = {'temperature': 1.2, 'league_weight': 0.25}
    result = calibration.adjust(p, q, settings)
    assert np.allclose(result, [calibrate(list(a), settings, list(b)) for a, b in zip(p, q)])
    assert result[0, -1] == 0 and result[1, 0] == 0
    probabilities = np.full((2, 15), 1 / 15)
    adjusted = evaluation.identity_rule_mask(probabilities, np.array([0, 1]))
    assert adjusted[0, 11] == 0 and adjusted[1, 11] > 0
    assert np.allclose(adjusted.sum(axis=1), 1) and adjusted[0, -1] == probabilities[0, -1]


def test_zero_probability_and_abstention_are_exposed_instead_of_clipped():
    templates = {'groups': {}, 'fallback_prior_count': 10}
    matrix = evaluation.projection_matrix(templates, 17, False)
    assert np.allclose(matrix.sum(axis=1), 1)
    assert matrix[14, 125] == 1  # unknown runner-only choice is not fabricated
    result = evaluation.summarize(np.array([1.0, np.inf]), np.array([0.5, 1.0]))
    assert result['log_loss'] is None and result['infinite_log_loss'] and result['zero_probability_targets'] == 1


def test_api_unknown_actors_explicit_assumptions_seed_and_no_hidden_resampling(tmp_path):
    _, s6, _, ids = prepared(tmp_path)
    out = tmp_path / 'cal'; out.mkdir()
    with sqlite3.connect(ids) as d, sqlite3.connect(s6) as source:
        dates = {g: (f, l) for g, f, l in d.execute('SELECT game_id,min(first_date),max(last_date) FROM windows GROUP BY game_id')}
        batch = fit.load_batch(source)
        base, record = calibration.run_calibration(batch, dates, out, experiment_config())
        templates = identity.fit_templates(d, [2023, 2024])
        kernels = fit.fit_kernels(batch.subset(batch.season < 2025), 100)
    model = CalibratedModel(base, kernels, templates, record, 'test-model')
    frame = identity.example_frame(0)
    assert model.predict_pa(frame)['fielders_choice'] == 0
    assert sum(model.predict_pa(frame, batter_model_id='unknown').values()) == pytest.approx(1)
    assert sum(model.predict_step(frame).values()) == pytest.approx(1)
    with pytest.raises(UnsupportedRule): model.resolve_outcome(frame, 'triple', random.Random(1))
    before = frame
    a = model.resolve_outcome(frame, 'triple', random.Random(1), allow_assumptions=True)
    b = model.resolve_outcome(frame, 'triple', random.Random(1), allow_assumptions=True)
    assert a == b and frame == before and a.transitions[0].plan.source == 'assumption'
    with pytest.raises(UnsupportedRule): model.resolve_outcome(frame, 'other_pa', random.Random(1), allow_assumptions=True)
    assert any(r['empirical_n'] == 0 for r in model.support_report(frame))
    journal = Journal(tmp_path / 'j.jsonl', frame, 'another-model')
    original = journal.path.read_bytes()
    with pytest.raises(ValueError, match='version'): journal.record_window(a)
    assert journal.path.read_bytes() == original
    # Offline density and live API apply the same mask/aborted-PA convention.
    test = batch.subset(batch.season == 2025)
    pp = evaluation.identity_rule_mask(evaluation.calibrated_step(test, base, record['parameters']), test.pre)
    live = model.predict_step(frame, batter_hand='R', pitcher_hand='L', batter_model_id='a0', pitcher_model_id='P')
    assert np.allclose(pp[0], list(live.values()))


def test_pipeline_immutable_reuse_bundle_and_standalone_api(tmp_path, monkeypatch):
    s5, s6, cache = sources(tmp_path)
    config = json.loads((ROOT / 'data_sources/stage7/config.json').read_text())
    from baseball_simulation_lab.empirical.common import sha_file
    config.update(experiment_config(), stage5_database_sha256=sha_file(s5), stage6_observations_sha256=sha_file(s6))
    path = tmp_path / 'config.json'; write_json(path, config)
    reports = tmp_path / 'reports'; reports.mkdir()
    for name in ('README.md', 'ATTRIBUTIONS.md', 'TRANSITIONS.md', 'STAGE8.md'):
        (reports / name).write_text('Test fixtures only')
    args = Namespace(config=path, source5=s5, source6=s6, cache=cache, output=tmp_path / 'out', report_dir=reports)
    before = (sha_file(s5), sha_file(s6))
    assert pipeline.run(args) == 0
    pointer = (args.output / 'current.json').read_bytes(); archive_sha = sha_file(reports / 'stage7_bundle.zip')
    assert pipeline.run(args) == 0
    assert (args.output / 'current.json').read_bytes() == pointer and sha_file(reports / 'stage7_bundle.zip') == archive_sha
    assert before == (sha_file(s5), sha_file(s6))
    unpacked = tmp_path / 'unpacked'
    with zipfile.ZipFile(reports / 'stage7_bundle.zip') as z:
        assert z.testzip() is None
        z.extractall(unpacked)
        manifest = json.loads(z.read('manifest.json'))
        for name, sha in manifest['files'].items(): assert digest(z.read(name)) == sha
    subprocess.run([sys.executable, '-S', 'example.py', '--model-dir', '.', '--allow-assumptions'], cwd=unpacked, check=True, capture_output=True)
    model = CalibratedModel.load(reports)
    assert sum(model.predict_pa(identity.example_frame(0)).values()) == pytest.approx(1)
    (reports / 'calibration.json').write_text('{}')
    with pytest.raises(ValueError, match='checksum'): CalibratedModel.load(reports)
    (reports / 'README.md').write_text('Changed documentation')
    monkeypatch.setattr(pipeline, 'collect', lambda *a: (_ for _ in ()).throw(ValueError('simulated failure')))
    with pytest.raises(ValueError, match='simulated failure'): pipeline.run(args)
    assert (args.output / 'current.json').read_bytes() == pointer
    assert not list((args.output / 'snapshots').glob('.building-*'))


def test_previous_output_directories_and_invalid_protocol_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='protected'):
        pipeline.protected(ROOT / 'data/research/stage6', tmp_path, ())
    config = json.loads((ROOT / 'data_sources/stage7/config.json').read_text()); config['base_training_year'] = 2025
    with pytest.raises(ValueError): pipeline.validate_config(config)
