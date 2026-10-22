from dataclasses import replace
import json
import sqlite3

import pytest

from baseball_simulation_lab.calibrated.rules import Move, Plan, canonical, frame_dict
from baseball_simulation_lab.fullgame.engine import Game, Team, fictional_team
from baseball_simulation_lab.fullgame.history import replay_rows
from baseball_simulation_lab.fullgame.league import Standings, league_gate, schedule
from baseball_simulation_lab.fullgame.model import Draw, NoRoute, assumed_play
from baseball_simulation_lab.fullgame.rules import Credit, GameRules, Play
from baseball_simulation_lab.fullgame.storage import HistoryStore, replay_game


class Scripted:
    version = 'test-explicit-outcomes-1'
    def __init__(self, choose=None): self.choose = choose or (lambda f: 'strikeout'); self.calls = 0
    def sample(self, frame, rng, **kwargs):
        self.calls += 1
        outcome = self.choose(frame)
        if outcome == 'FAIL': raise NoRoute('runner_only_end', {'fixture': True})
        p = assumed_play(frame, outcome)
        return Draw(outcome, (p,), 1.0, p.plan.source_ref)


def teams(): return fictional_team('A'), fictional_team('H')


def test_nine_inning_draw_and_replay_box_score(tmp_path):
    game = Game(Scripted(), teams(), rules=GameRules(9), journal_path=tmp_path / 'journal.jsonl')
    r = game.run()
    assert r['status'] == 'draw' and r['windows'] == 54 and r['completed_halves'] == 18
    assert r['score'] == [0, 0] and sum(s['pa'] for s in r['batting'].values()) == 54
    assert sum(s['outs'] for s in r['pitching'].values()) == 54
    assert canonical(replay_game(game.journal.rows)) == canonical(r)
    assert replay_rows(game.journal.rows) == game.frame
    with pytest.raises(FileExistsError): Game(Scripted(), teams(), journal_path=tmp_path / 'journal.jsonl')


def test_home_lead_omits_bottom_nine_and_away_lead_plays_it():
    for leader, windows, halves in [(1, 52, 17), (0, 55, 18)]:
        m = Scripted(lambda f: 'home_run' if f.inning == 1 and f.half == leader and f.batter.endswith('B01') else 'strikeout')
        g = Game(m, teams()); r = g.run()
        assert r['status'] == 'completed' and r['windows'] == windows and r['completed_halves'] == halves
        assert r['linescore'][-1]['home'] == (None if leader == 1 else 0)
        assert r['pitcher_decisions']['winner'] == teams()[leader].starter
        assert r['pitcher_decisions']['loser'] == teams()[1-leader].starter


def test_bottom_ninth_walkoff_and_hit_rbi_counts():
    g = Game(Scripted(lambda f: 'home_run' if f.inning == 9 and f.half == 1 else 'strikeout'), teams())
    r = g.run(); assert r['score'] == [0, 1] and r['walkoff'] and r['completed_halves'] == 17
    assert r['team_totals'][1]['hr'] == 1 and sum(s['rbi'] for s in r['batting'].values()) == 1
    assert canonical(replay_game(g.journal.rows)) == canonical(r)


def test_configured_automatic_runner_does_not_count_as_pa_or_hit():
    g = Game(Scripted(), teams(), rules=GameRules(10, True, 10))
    r = g.run(); assert r['extra_innings'] and r['status'] == 'draw'
    assert r['windows'] == 60 and r['team_totals'][0]['pa'] == 30
    assert r['team_totals'][0]['h'] == 0 and r['team_totals'][0]['r'] == 0
    assert canonical(replay_game(g.journal.rows)) == canonical(r)


def test_mid_pa_runner_third_out_does_not_charge_pa_or_move_batting_order():
    class RunnerThird(Scripted):
        def sample(self, f, rng, **kwargs):
            if f.outs == 2 and f.base_mask:
                moves = tuple(Move(r.player_id, i, 'OUT') for i, r in enumerate(f.bases, 1) if r)
                p = Play(Plan('caught_stealing', moves, False, 'explicit_event', 'test'), Credit(False))
                return Draw('runner_only_end', (p,), 1, 'test')
            return super().sample(f, rng, **kwargs)
    g = Game(RunnerThird(lambda f: 'single' if f.batter.endswith('B01') and f.outs == 0 else 'strikeout'), teams(), rules=GameRules(9))
    g.step(); g.step(); g.step(); batter = g.frame.batter
    assert g.frame.outs == 2
    g.step(); assert g.frame.outs == 3 and g.frame.batter == batter
    assert sum(s['pa'] for s in g.book.batting.values()) == 3


def test_no_resampling_failure_context_and_replay(tmp_path):
    m = Scripted(lambda f: 'FAIL'); g = Game(m, teams(), seed=441)
    r = g.run(); assert r['status'] == 'failed' and m.calls == 1
    f = r['failure']; assert f['seed'] == 441 and f['sampled_outcome'] == 'runner_only_end'
    assert f['batter'] == 'A:B01' and f['pitcher'] == 'H:P01' and f['rules_version']
    assert f['model_version'] == m.version and f['rng_state_after_failure']
    assert canonical(replay_game(g.journal.rows)) == canonical(r)
    with pytest.raises(ValueError): g.step()
    s = HistoryStore(tmp_path / 'failed.sqlite3'); assert s.save(g); assert s.load(g.game_id)['status'] == 'failed'; s.close()


def test_safety_limit_is_a_saved_failure_and_no_draw_rule_is_explicit():
    g = Game(Scripted(), teams(), rules=GameRules(max_windows=1)); r = g.run()
    assert r['status'] == 'failed' and r['reason'] == 'window_safety_limit'
    assert canonical(replay_game(g.journal.rows)) == canonical(r)
    g = Game(Scripted(), teams(), rules=GameRules(9, False)); r = g.run()
    assert r['status'] == 'failed' and 'inning_limit_without_draw' in r['reason']


def test_substitutions_and_inherited_pitcher_runs_replay():
    g = Game(Scripted(lambda f: 'single' if f.half == 0 and f.batter.endswith('B01') else 'strikeout'), teams(), rules=GameRules(9))
    g.step(); assert g.frame.bases[0].player_id == 'A:B01'
    g.change_pitcher('H:P02'); g.substitute(0, 0, 'A:B10', pinch_runner=True)
    g.substitute(0, 1, 'A:B11')
    assert g.frame.bases[0].responsible_pitcher == 'H:P01'
    with pytest.raises(ValueError): g.change_pitcher('A:P02')
    with pytest.raises(ValueError): g.substitute(0, 0, 'A:B01', pinch_runner=True)
    g._act('draw', {'outcome': 'home_run', 'probability': 1, 'route_ref': 'test', 'window_number': 2}); g.windows = 2
    g._act('play_v2', __import__('baseball_simulation_lab.fullgame.rules', fromlist=['play_dict']).play_dict(assumed_play(g.frame, 'home_run')))
    r = g.run()
    assert r['pitching']['H:P01']['r'] == 1 and r['pitching']['H:P02']['r'] == 1
    assert r['batting']['A:B10']['r'] == 1 and r['batting']['A:B11']['hr'] == 1
    assert canonical(replay_game(g.journal.rows)) == canonical(r)


def test_persistent_history_is_idempotent_immutable_and_model_independent(tmp_path):
    g = Game(Scripted(), teams(), rules=GameRules(9)); result = g.run()
    store = HistoryStore(tmp_path / 'history.sqlite3')
    assert store.save(g) and not store.save(g)
    other = Game(Scripted(lambda f: 'home_run' if f.inning == 1 and f.half == 0 and f.batter.endswith('B01') else 'strikeout'),
                 teams(), rules=GameRules(9))
    other.run()
    assert other.game_id == g.game_id
    with pytest.raises(ValueError, match='conflict'): store.save(other)
    g.model = None  # replay/load must not call a newer model
    assert store.load(result['game_id']) == json.loads(canonical(result))
    for query in ('DELETE FROM games', 'UPDATE appearances SET h=99', 'DELETE FROM journal_events'):
        with pytest.raises(sqlite3.IntegrityError): store.db.execute(query)
    assert store.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    store.close()
    plain = tmp_path / 'other.sqlite3'; sqlite3.connect(plain).close()
    with pytest.raises(ValueError): HistoryStore(plain)


def test_corrupt_or_truncated_history_and_fake_completed_result_are_rejected():
    g = Game(Scripted(), teams(), rules=GameRules(9)); g.run()
    rows = json.loads(canonical(g.journal.rows))
    with pytest.raises(ValueError): replay_game(rows[:-1])
    next(r for r in rows[1:] if r['event']['operation'] == 'play_v2')['event']['parameters']['credit']['hit_bases'] = 4
    with pytest.raises(ValueError): replay_game(rows)
    rows = json.loads(canonical(g.journal.rows)); rows[0]['header']['model_version'] = 'newer'
    with pytest.raises(ValueError): replay_game(rows)


def test_headless_benchmarks_cannot_be_saved_as_historical_games(tmp_path):
    g = Game(Scripted(), teams(), rules=GameRules(9), record=False); g.run()
    s = HistoryStore(tmp_path / 'history.sqlite3')
    with pytest.raises(ValueError): s.save(g)
    s.close()


def test_schedule_and_standings_have_no_duplicate_games_or_ids():
    ids = [f'T{i:02}' for i in range(12)]; games = schedule(ids)
    assert len(games) == 858
    for t in ids:
        assert sum(t in (g['away'], g['home']) for g in games) == 143
        assert sum(g['home'] == t for g in games) in (71, 72)
    table = Standings(ids)
    r = {'status': 'completed', 'game_id': 'g', 'team_ids': ids[:2], 'score': [2, 1]}
    table.add(r)
    with pytest.raises(ValueError): table.add(r)
    with pytest.raises(ValueError): table.add({**r, 'game_id': 'bad', 'status': 'failed'})
    table.add({**r, 'game_id': 'draw', 'status': 'draw', 'score': [0, 0]})
    row = next(r for r in table.rows() if r['team_id'] == ids[0])
    assert (row['w'], row['l'], row['d'], row['games'], row['win_pct']) == (1, 0, 1, 2, 1)
    assert not league_gate({'attempted_games': 1000, 'failed_games': 1, 'record_integrity_failures': 0, 'unresolved_priority_records': 0})
    assert league_gate({'attempted_games': 1000, 'failed_games': 0, 'record_integrity_failures': 0, 'unresolved_priority_records': 0})


def test_roster_collisions_invalid_dates_seeds_and_previous_paths_are_rejected():
    a, h = teams()
    for kwargs in ({'seed': -1}, {'seed': True}, {'game_date': 'nonsense'}):
        with pytest.raises(ValueError): Game(Scripted(), (a, h), **kwargs)
    with pytest.raises(ValueError): Game(Scripted(), (a, replace(h, starter=a.starter)))
    from pathlib import Path
    with pytest.raises(ValueError): HistoryStore(Path(__file__).resolve().parents[1] / 'data/research/stage7/should-not-exist.sqlite3')


def test_unknown_rbi_is_null_and_relief_winner_can_require_review():
    g = Game(Scripted(), teams())
    for _ in range(3): g.step()
    g.step()  # begin bottom one; retire one home batter
    g.change_pitcher('A:P02')
    # A second relief later makes a short relief candidate discretionary.
    g.change_pitcher('A:P03')
    g.book.last_lead = {'side': 0, 'candidate': 'A:P02', 'loser': 'H:P01', 'responsibility_complete': True}
    assert g.book.decisions(g.frame, 'completed')['status'] == 'manual_review_relief_effectiveness'
    g.book.last_lead['candidate'] = 'A:P01'
    assert g.book.decisions(g.frame, 'completed')['status'] == 'manual_review_starter_minimum'
    g.book.unknown_rbi.add('A:B01')
    result = g.book.export(g.frame, 'failed')
    assert result['batting']['A:B01']['rbi'] is None
    assert all(s['er'] is None and s['save'] is None and s['hold'] is None for s in result['pitching'].values())
