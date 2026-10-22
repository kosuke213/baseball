"""Append-only SQLite history with searchable counts and a replayable journal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from ..calibrated.rules import canonical, frame_from_dict
from .engine import Game, Team
from .history import replay_rows
from .records import Scorebook


def replay_game(rows):
    """Rebuild both state and box score; no probability model is loaded."""
    header = rows[0]['header']; req = header['request']
    g = object.__new__(Game)
    g.request = req; g.seed = req['seed']; g.model = SimpleNamespace(version=header['model_version'])
    g.teams = tuple(Team(t['team_id'], tuple(t['lineup']), t['starter'], tuple(t['bench']), tuple(t['bullpen'])) for t in req['teams'])
    g.frame = frame_from_dict(header['initial']); g.book = Scorebook(g.frame, req['teams'])
    g.game_id = hashlib.sha256(canonical({'request': req, 'model': g.model.version, 'rules_version': header['rules_version']}).encode()).hexdigest()[:32]
    g.status = 'in_progress'; g.reason = None; g.failure = None
    g.windows = 0; g.completed_halves = 0; g.attempted_halves = 1; g.walkoff = False
    g.journal = True
    terminal = False

    def observe(before, after, operation, p, applied):
        nonlocal terminal
        if terminal: raise ValueError('Events after game terminal record')
        g.frame = after
        if applied:
            g.book.observe(before, applied)
            if after.outs == 3: g.completed_halves += 1
            g.walkoff |= after.finished
        elif operation == 'advance_half_v2' and not after.finished:
            g.attempted_halves += 1; g.book.start_half(after)
        elif operation == 'change_pitcher': g.book.register_pitcher(after.pitcher, 1 - after.half)
        elif operation == 'substitute': g.book.register_batter(p['player_id'], p['side'])
        elif operation == 'draw':
            if p['window_number'] != g.windows + 1: raise ValueError('Window sequence mismatch')
            g.windows += 1
        elif operation == 'stop':
            if p['window_number'] not in (g.windows, g.windows + 1): raise ValueError('Failed window sequence mismatch')
            g.windows = p['window_number']; g.status = 'failed'; g.reason = p['reason']; g.failure = p; terminal = True
        elif operation == 'finish':
            if p['windows'] != g.windows or p['completed_halves'] != g.completed_halves or p['attempted_halves'] != g.attempted_halves or p['walkoff'] != g.walkoff:
                raise ValueError('Stored completion counters differ from events')
            expected = 'draw' if after.score[0] == after.score[1] else 'completed'
            if p['status'] != expected: raise ValueError('Completion status differs from final score')
            g.status, g.reason = p['status'], p['reason']; terminal = True

    g.frame = replay_rows(rows, observer=observe)
    if not terminal: raise ValueError('Incomplete journal: no game terminal record')
    return g.result()


SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE games(game_id TEXT PRIMARY KEY,game_date TEXT NOT NULL,away_id TEXT NOT NULL,home_id TEXT NOT NULL,
 status TEXT NOT NULL,away_runs INTEGER NOT NULL,home_runs INTEGER NOT NULL,
 model_version TEXT NOT NULL,rules_version TEXT NOT NULL,seed INTEGER NOT NULL,
 payload_sha256 TEXT NOT NULL,result_json TEXT NOT NULL);
CREATE TABLE appearances(game_id TEXT REFERENCES games(game_id),player_id TEXT,team_id TEXT,kind TEXT,
 pa INTEGER,ab INTEGER,h INTEGER,hr INTEGER,r INTEGER,rbi INTEGER,outs INTEGER,
 stats_json TEXT NOT NULL,PRIMARY KEY(game_id,player_id,kind));
CREATE TABLE journal_events(game_id TEXT REFERENCES games(game_id),sequence INTEGER,record_json TEXT NOT NULL,
 PRIMARY KEY(game_id,sequence));
CREATE INDEX games_date_teams ON games(game_date,away_id,home_id);
CREATE INDEX player_history ON appearances(player_id,game_id);
'''


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        root = Path(__file__).resolve().parents[2]
        for prefix in ('data_sources', 'data/research'):
            for name in ('pilot', 'warehouse', 'stage5', 'stage6', 'stage7'):
                protected = root / prefix / name
                if self.path.resolve().is_relative_to(protected.resolve()):
                    raise ValueError('Previous stage data is protected')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA foreign_keys=ON')
        if new:
            self.db.executescript(SCHEMA)
            self.db.execute('INSERT INTO metadata VALUES(?,?)', ('schema_version', 'fullgame-history-1'))
            for table in ('games', 'appearances', 'journal_events'):
                for action in ('UPDATE', 'DELETE'):
                    self.db.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable history'); END")
            self.db.commit()
        else:
            try: version = self.db.execute('SELECT value FROM metadata WHERE key="schema_version"').fetchone()
            except sqlite3.Error:
                self.db.close(); raise ValueError('Existing file is not a fullgame history database')
            if version != ('fullgame-history-1',):
                self.db.close(); raise ValueError('Unknown history schema; migrate to a new database')

    def close(self): self.db.close()

    def save(self, game):
        if not game.journal or game.status == 'in_progress':
            raise ValueError('Saving requires a terminal game with its complete event history')
        result = game.result(); reconstructed = replay_game(game.journal.rows)
        if canonical(result) != canonical(reconstructed):
            raise ValueError('Replayed game/box score differs; refusing to commit history')
        rows = game.journal.rows
        payload = canonical({'result': result, 'journal': rows}); sha = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.db.execute('SELECT payload_sha256 FROM games WHERE game_id=?', (game.game_id,)).fetchone()
        if existing:
            if existing[0] != sha: raise ValueError('Game ID conflict: immutable history differs')
            return False
        with self.db:
            self.db.execute('INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (game.game_id, result['game_date'], *result['team_ids'], result['status'], *result['score'],
                 result['model_version'], result['rules_version'], result['seed'], sha, canonical(result)))
            for kind in ('batting', 'pitching'):
                for pid, s in result[kind].items():
                    self.db.execute('INSERT INTO appearances VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (game.game_id, pid, s['team_id'], kind, s.get('pa'), s.get('ab'), s['h'], s['hr'], s['r'], s.get('rbi'), s.get('outs'), canonical(s)))
            self.db.executemany('INSERT INTO journal_events VALUES(?,?,?)', ((game.game_id, i, canonical(row)) for i, row in enumerate(rows)))
        return True

    def load(self, game_id):
        record = self.db.execute('SELECT result_json,payload_sha256 FROM games WHERE game_id=?', (game_id,)).fetchone()
        if not record: raise KeyError(game_id)
        rows = [json.loads(r[0]) for r in self.db.execute('SELECT record_json FROM journal_events WHERE game_id=? ORDER BY sequence', (game_id,))]
        result = json.loads(record[0])
        if hashlib.sha256(canonical({'result': result, 'journal': rows}).encode()).hexdigest() != record[1]:
            raise ValueError('Stored result/journal checksum mismatch')
        if canonical(replay_game(rows)) != canonical(result): raise ValueError('Stored historical stats do not replay')
        return result
