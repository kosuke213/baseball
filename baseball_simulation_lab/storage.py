"""SQLite persistence. Historical records are append-only and detached from rosters."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from .domain import (Environment, Park, Player, PlayerState, Rules, Team, Traits,
                     Weather)
from .engine import Game
from .model import ModelSettings, RuleBasedModel


def encode(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def team_from_dict(data: dict) -> Team:
    data = dict(data)
    players = []
    for raw in data["players"]:
        p = dict(raw)
        p["latent"] = Traits(**p["latent"])
        p["ability"] = Traits(**p["ability"])
        p["state"] = PlayerState(**p["state"])
        players.append(Player(**p))
    data["players"] = players
    return Team(**data)


def game_from_snapshot(snapshot: dict) -> Game:
    if snapshot["engine_version"] != "phase1-engine-1" or snapshot["rules"]["version"] != "phase1-rules-1":
        raise ValueError("Historical engine/rules version is not installed")
    if snapshot["model"]["version"] != RuleBasedModel.version:
        raise ValueError("Historical model version is not installed")
    import numpy as np
    if snapshot["numpy_version"] != np.__version__:
        raise ValueError("Replay requires the NumPy version saved in the snapshot")
    env = snapshot["environment"]
    return Game(*[team_from_dict(t) for t in snapshot["teams"]],
                seed=snapshot["seed"], rules=Rules(**snapshot["rules"]),
                environment=Environment(Park(**env["park"]), Weather(**env["weather"])),
                model=RuleBasedModel(ModelSettings(**snapshot["model"]["settings"])))


def replay(result: dict) -> Game:
    game = game_from_snapshot(result["snapshot"])
    cursor = 0
    while cursor < len(result["events"]):
        event = result["events"][cursor]
        if event["kind"] == "substitution":
            change = event["substitution"]
            if change["kind"] == "pitcher_change":
                game.change_pitcher(change["in"])
            else:
                game.replace_batter(change["side"], change["slot"], change["in"])
        else:
            game.step()
        # Automatic substitutions can generate multiple events in one step.
        emitted = len(game.events) - cursor
        if emitted < 1 or game.events[cursor:] != result["events"][cursor:cursor+emitted]:
            raise ValueError(f"Replay diverged at event {cursor+1}")
        cursor += emitted
    if game.result() != result:
        raise ValueError("Replay final records differ")
    return game


class Store:
    def __init__(self, path: str | Path = "data/lab.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError(f"Unsupported database schema: {version}")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS world (singleton INTEGER PRIMARY KEY CHECK(singleton=1), initial_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS teams (team_id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS players (player_id TEXT PRIMARY KEY, team_id TEXT NOT NULL REFERENCES teams, public_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS player_traits (player_id TEXT PRIMARY KEY REFERENCES players, latent_json TEXT NOT NULL, ability_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS player_states (player_id TEXT PRIMARY KEY REFERENCES players, state_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_versions (model_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS games (game_id TEXT PRIMARY KEY, model_id TEXT NOT NULL REFERENCES model_versions,
          digest TEXT NOT NULL, snapshot_json TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS game_events (game_id TEXT NOT NULL REFERENCES games, sequence INTEGER NOT NULL,
          event_json TEXT NOT NULL, PRIMARY KEY(game_id, sequence));
        CREATE TABLE IF NOT EXISTS batting_statistics (game_id TEXT NOT NULL REFERENCES games, player_id TEXT NOT NULL REFERENCES players,
          statistics_json TEXT NOT NULL, PRIMARY KEY(game_id, player_id));
        CREATE TABLE IF NOT EXISTS pitching_statistics (game_id TEXT NOT NULL REFERENCES games, player_id TEXT NOT NULL REFERENCES players,
          statistics_json TEXT NOT NULL, PRIMARY KEY(game_id, player_id));
        CREATE TABLE IF NOT EXISTS game_lineups (game_id TEXT NOT NULL REFERENCES games, side INTEGER NOT NULL,
          lineup_json TEXT NOT NULL, PRIMARY KEY(game_id, side));
        PRAGMA user_version=1;
        """)
        for table in ("games", "game_events", "batting_statistics", "pitching_statistics", "game_lineups", "model_versions"):
            for operation in ("UPDATE", "DELETE"):
                self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Historical records are immutable'); END")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def initialize(self, teams: list[Team]) -> bool:
        initial = encode([asdict(t) for t in teams])
        existing = self.conn.execute("SELECT initial_json FROM world WHERE singleton=1").fetchone()
        if existing:
            if existing[0] != initial:
                raise ValueError("A different initial world exists; use another DB or explicit reset")
            return False
        with self.conn:
            self.conn.execute("INSERT INTO world VALUES (1, ?)", (initial,))
            for team in teams:
                self.conn.execute("INSERT INTO teams VALUES (?,?)", (team.team_id, team.name))
                for p in team.players:
                    self.conn.execute("INSERT INTO players VALUES (?,?,?)", (p.player_id, team.team_id, encode(p.public())))
                    self.conn.execute("INSERT INTO player_traits VALUES (?,?,?)", (p.player_id, encode(asdict(p.latent)), encode(asdict(p.ability))))
                    self.conn.execute("INSERT INTO player_states VALUES (?,?)", (p.player_id, encode(asdict(p.state))))
        return True

    def initial_teams(self) -> list[Team]:
        row = self.conn.execute("SELECT initial_json FROM world WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("Initialize the database first")
        return [team_from_dict(t) for t in json.loads(row[0])]

    def save(self, game: Game) -> bool:
        result = game.result()
        if sum(e["kind"] == "pitch" for e in result["events"]) != game.state.pitches:
            raise ValueError("Official persistence requires the complete pitch event log")
        digest = hashlib.sha256(encode(result).encode()).hexdigest()
        existing = self.conn.execute("SELECT digest FROM games WHERE game_id=?", (game.game_id,)).fetchone()
        if existing:
            if existing[0] != digest:
                raise ValueError("Conflicting result for the same initial snapshot")
            return False
        metadata = encode(result["snapshot"]["model"])
        model_id = hashlib.sha256(metadata.encode()).hexdigest()
        record = {k: v for k, v in result.items() if k not in ("snapshot", "events", "batting", "pitching")}
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO model_versions VALUES (?,?)", (model_id, metadata))
            self.conn.execute("INSERT INTO games VALUES (?,?,?,?,?)", (game.game_id, model_id, digest, encode(result["snapshot"]), encode(record)))
            self.conn.executemany("INSERT INTO game_events VALUES (?,?,?)", [(game.game_id, e["sequence"], encode(e)) for e in result["events"]])
            for kind in ("batting", "pitching"):
                self.conn.executemany(f"INSERT INTO {kind}_statistics VALUES (?,?,?)", [(game.game_id, pid, encode(s)) for pid, s in result[kind].items()])
            self.conn.executemany("INSERT INTO game_lineups VALUES (?,?,?)", [(game.game_id, side, encode({"initial": result["snapshot"]["teams"][side]["lineup"], "final": result["lineups"][side], "defense": result["defenses"][side]})) for side in (0, 1)])
            for t in game.teams:
                for p in t.players:
                    self.conn.execute("UPDATE player_states SET state_json=? WHERE player_id=?", (encode(asdict(p.state)), p.player_id))
        return True

    def load(self, game_id: str) -> dict:
        row = self.conn.execute("SELECT snapshot_json, record_json FROM games WHERE game_id=?", (game_id,)).fetchone()
        if row is None:
            raise KeyError(game_id)
        result = json.loads(row[1])
        result["snapshot"] = json.loads(row[0])
        result["events"] = [json.loads(r[0]) for r in self.conn.execute("SELECT event_json FROM game_events WHERE game_id=? ORDER BY sequence", (game_id,))]
        for kind in ("batting", "pitching"):
            result[kind] = {pid: json.loads(s) for pid, s in self.conn.execute(f"SELECT player_id, statistics_json FROM {kind}_statistics WHERE game_id=?", (game_id,))}
        return result

    def game_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT game_id FROM games ORDER BY rowid DESC")]

    def public_players(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT public_json FROM players ORDER BY player_id")]
