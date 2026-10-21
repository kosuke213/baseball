from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "baseball_simulation_lab/app.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run(timeout=30)
    assert not app.exception


def test_ui_dashboard_pitch_full_game_and_saved_replay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert len(app.dataframe[0].value) == 56
    assert not {"latent", "ability", "state"} & set(app.dataframe[0].value.columns)
    app.sidebar.radio[0].set_value("試合実験").run()
    assert not app.exception
    click(app, "新しい試合")
    click(app, "1球進める")
    assert app.session_state.game.state.pitches == 1
    click(app, "最後まで進める")
    assert app.session_state.game.state.finished
    app.sidebar.radio[0].set_value("保存試合・リプレイ").run()
    assert not app.exception
    app.slider[0].set_value(0).run()
    assert not app.exception
    app.sidebar.radio[0].set_value("開発者").run()
    assert not app.exception


def test_ui_defense_change_can_be_corrected_without_crashing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("試合実験").run()
    app.selectbox(key="aonami-C").set_value("aonami-09").run()
    assert not app.exception
    click(app, "新しい試合")
    assert app.error  # User must also align the nine-person batting order.
