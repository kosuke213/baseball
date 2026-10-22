import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

import pytest

from baseball_simulation_lab.fullgame import pipeline, sources, validation
from baseball_simulation_lab.fullgame.paths import ROOT, new_output


def test_small_pipeline_preserves_inputs_reuses_and_bundles_exact_sources(tmp_path, monkeypatch):
    from test_fullgame_model import fixture_sources
    s5, s6, cache, pins = fixture_sources(tmp_path)
    monkeypatch.setattr(pipeline, 'input_paths', lambda: (s5, s6, cache, pins))
    monkeypatch.setattr(pipeline, 'build', lambda output: sources.build(output, source5=s5, source6=s6, cache=cache, config=pins, progress=lambda _: None))
    monkeypatch.setattr(validation, 'observed_reference', lambda output: None)
    monkeypatch.setattr(pipeline, 'audit_stage7', lambda model, output: None)
    original_validation = validation.run_validation
    monkeypatch.setattr(pipeline, 'run_validation', lambda model, output, config, progress: original_validation(
        model, output, {**config, 'milestones': [2], 'sample_histories': 1}, progress=lambda _: None))
    reports = tmp_path / 'reports'; reports.mkdir()
    for n in pipeline.MANUALS: shutil.copyfile(ROOT / 'data_sources/stage8' / n, reports / n)
    config = ROOT / 'data_sources/stage8/config.json'; out = tmp_path / 'out'
    target = pipeline.run(config, out, reports)
    pointer = (out / 'current.json').read_bytes(); bundle_sha = sources.sha(reports / 'stage8_bundle.zip')
    assert pipeline.run(config, out, reports) == target
    assert (out / 'current.json').read_bytes() == pointer and sources.sha(reports / 'stage8_bundle.zip') == bundle_sha
    assert sources.sha(s5) == pins['stage5_database_sha256'] and sources.sha(s6) == pins['stage6_observations_sha256']
    with zipfile.ZipFile(reports / 'stage8_bundle.zip') as z:
        assert z.testzip() is None
        manifest = json.loads(z.read('manifest.json'))
        from hashlib import sha256
        for path, expected in manifest['files'].items(): assert sha256(z.read(path)).hexdigest() == expected
        assert 'code/baseball_simulation_lab/fullgame/engine.py' in z.namelist()
        assert 'sample_history.sqlite3' in z.namelist()
    (reports / 'README.md').write_text('New docs; intentionally failed rebuild')
    monkeypatch.setattr(pipeline, 'build', lambda _: (_ for _ in ()).throw(ValueError('fixture failure')))
    with pytest.raises(ValueError, match='fixture failure'): pipeline.run(config, out, reports)
    assert (out / 'current.json').read_bytes() == pointer
    assert sources.sha(reports / 'stage8_bundle.zip') == bundle_sha
    assert list((out / 'snapshots').glob('.building-*/build_failure.json'))


def test_previous_stage_outputs_and_changed_validation_protocol_are_rejected():
    for n in ('stage5', 'stage6', 'stage7'):
        with pytest.raises(ValueError): new_output(ROOT / 'data_sources' / n / 'new')
    with pytest.raises(ValueError): new_output(ROOT / 'data/research')
    c = json.loads((ROOT / 'data_sources/stage8/config.json').read_text())
    pipeline.validate_config(c)
    with pytest.raises(ValueError): pipeline.validate_config({**c, 'milestones': [10000]})
