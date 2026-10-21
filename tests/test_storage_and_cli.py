from copy import deepcopy
import json
import sqlite3
import pytest

from baseball_simulation_lab.__main__ import main
from baseball_simulation_lab.engine import Game
from baseball_simulation_lab.storage import Store, replay


def test_storage_is_repeatable_and_history_is_immutable(tmp_path, teams):
    with Store(tmp_path / "lab.db") as store:
        assert store.initialize(teams)
        assert not store.initialize(teams)
        first = Game(*teams).run()
        assert store.save(first)
        assert not store.save(first)
        old = deepcopy(store.load(first.game_id))
        store.save(Game(*first.teams, seed=43).run())
        assert store.load(first.game_id) == old == first.result()
        assert replay(old).result() == old
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.conn.execute("UPDATE games SET record_json='{}'")


def test_changed_world_is_not_overwritten(tmp_path, teams):
    with Store(tmp_path / "lab.db") as store:
        store.initialize(teams)
        changed = deepcopy(teams)
        changed[0].name = "Different world"
        with pytest.raises(ValueError, match="different initial world"):
            store.initialize(changed)


def test_saved_substitutions_are_replayable(tmp_path, teams):
    game = Game(*teams)
    game.change_pitcher(teams[1].players[21].player_id)
    game.replace_batter(0, 0, teams[0].players[8].player_id)
    game.run()
    with Store(tmp_path / "lab.db") as store:
        store.initialize(teams)
        store.save(game)
        assert replay(store.load(game.game_id)).result() == game.result()


def test_missing_event_log_cannot_be_saved(tmp_path, teams):
    with Store(tmp_path / "lab.db") as store:
        store.initialize(teams)
        with pytest.raises(ValueError, match="complete pitch"):
            store.save(Game(*teams, record_events=False).run())


def test_different_decisions_with_same_seed_are_distinct_experiments(tmp_path, teams):
    first = Game(*teams, seed=7).run()
    second = Game(*teams, seed=7)
    second.change_pitcher(teams[1].players[21].player_id)
    second.run()
    assert first.game_id != second.game_id
    with Store(tmp_path / "lab.db") as store:
        store.initialize(teams)
        assert store.save(first) and store.save(second)
        assert len(store.game_ids()) == 2
        assert replay(store.load(second.game_id)).result() == second.result()


def test_cli_init_simulate_replay_and_repeat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert main(["init"]) == 0
    command = ["simulate", "--games", "2", "--seed", "42"]
    assert main(command) == 0
    summary = json.loads((tmp_path / "reports/latest/summary.json").read_text())
    assert summary["games"] == summary["newly_saved_games"] == 2
    assert summary["rules"]["max_innings"] == 12
    assert summary["numpy_version"]
    with Store() as store:
        ids = store.game_ids()
        assert len(ids) == 2
    assert main(["replay", "--game-id", ids[0]]) == 0
    assert main(command) == 0
    summary = json.loads((tmp_path / "reports/latest/summary.json").read_text())
    assert summary["newly_saved_games"] == 0


def test_reset_requires_explicit_yes(tmp_path):
    with pytest.raises(SystemExit):
        main(["reset", "--db", str(tmp_path/"test.db")])


def test_failed_save_rolls_back_all_tables(tmp_path, teams):
    with Store(tmp_path / "lab.db") as store:
        store.initialize(teams)
        game = Game(*teams).run()
        # A missing referenced player must fail, never leave half of a game saved.
        game.batting["unknown"] = next(iter(game.batting.values()))
        with pytest.raises(sqlite3.IntegrityError):
            store.save(game)
        assert store.game_ids() == []
        assert store.conn.execute("SELECT count(*) FROM game_events").fetchone()[0] == 0
