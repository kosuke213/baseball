"""Staged headless diagnostics. Failures are retained and never resampled away."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time

from data_collection.fetch import write_json
from ..calibrated.api import CalibratedModel
from ..calibrated.identity import example_frame
from ..calibrated.rules import canonical, frame_dict
from .engine import Game, fictional_team
from ..fullgame.league import league_gate, schedule, Standings
from .rules import GameRules
from ..fullgame.sources import input_paths
from .storage import HistoryStore


def csv_file(path, rows, fields=None):
    import csv
    rows = list(rows)
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, lineterminator='\n', fieldnames=fields or list(rows[0]) if rows else fields or ['empty'])
        w.writeheader(); w.writerows(rows)


def describe(values):
    values = sorted(values)
    if not values: return {'n': 0}
    def q(v):
        position = (len(values) - 1) * v; lo = int(position); hi = min(lo + 1, len(values) - 1)
        return values[lo] + (position - lo) * (values[hi] - values[lo])
    return {'n': len(values), 'mean': statistics.mean(values), 'sd': statistics.stdev(values) if len(values) > 1 else 0,
            'min': values[0], 'p50': q(.5), 'p90': q(.9), 'p95': q(.95), 'p99': q(.99), 'max': values[-1]}


def compact(result, seconds=0):
    totals = result['team_totals']
    return {'game_id': result['game_id'], 'seed': result['seed'], 'status': result['status'], 'reason': result['reason'],
            'away_runs': result['score'][0], 'home_runs': result['score'][1], 'runs': sum(result['score']),
            **{k: sum(t[k] for t in totals) for k in ('h', 'hr', 'bb', 'hbp', 'k', 'pa')},
            'windows': result['windows'], 'attempted_halves': result['attempted_halves'], 'margin': abs(result['score'][0]-result['score'][1]),
            'completed_halves': result['completed_halves'], 'extra': result['extra_innings'], 'walkoff': result['walkoff'],
            'rbi_complete': result['scoring_status']['rbi_complete'],
            'run_responsibility_complete': result['scoring_status']['run_responsibility_complete'],
            'pitcher_decision_status': result['pitcher_decisions']['status'],
            'record_integrity_passed': result['record_integrity']['passed'], 'seconds': seconds}


def aggregate(rows, elapsed):
    done = [r for r in rows if r['status'] in ('completed', 'draw')]
    failures = Counter(r['reason'] for r in rows if r['status'] == 'failed')
    priority = sum(not r['rbi_complete'] or not r['run_responsibility_complete']
                   or r['pitcher_decision_status'].startswith('manual') for r in done)
    attempted_halves = sum(r['attempted_halves'] for r in rows)
    completed_halves = sum(r['completed_halves'] for r in rows)
    return {'attempted_games': len(rows), 'completed_games': len(done), 'draws': sum(r['status'] == 'draw' for r in rows),
            'failed_games': len(rows) - len(done), 'game_completion_rate': len(done) / len(rows),
            'attempted_halves': attempted_halves, 'third_out_completed_halves': completed_halves,
            'walkoff_ended_halves': sum(r['walkoff'] for r in done),
            'half_completion_rate': (completed_halves + sum(r['walkoff'] for r in done)) / attempted_halves,
            'failure_causes': dict(failures), 'record_integrity_failures': sum(not r['record_integrity_passed'] for r in rows),
            'unresolved_priority_records': priority,
            'blowout_10plus_rate_completed_only': sum(r['margin']>=10 for r in done)/len(done) if done else None,
            'extra_inning_rate_completed_only': sum(r['extra'] for r in done) / len(done) if done else None,
            'walkoff_rate_completed_only': sum(r['walkoff'] for r in done) / len(done) if done else None,
            'distributions_completed_only': {k: describe([r[k] for r in done]) for k in ('runs', 'h', 'hr', 'bb', 'hbp', 'k', 'pa', 'windows', 'margin')},
            'elapsed_seconds': elapsed, 'games_per_second': len(rows) / elapsed if elapsed else None,
            'limitations': ['completed-only distributions exclude failed games and may be selection-biased',
                           'all fictional actors use league fallback; not calibrated NPB abilities',
                           'headless benchmarks are not committed official game histories',
                           'full official scoring remains incomplete even when priority counts are known']}


def observed_reference(output):
    _, source6, _, _ = input_paths(); rows = []
    with closing(sqlite3.connect('file:' + str(source6) + '?mode=ro', uri=True)) as db:
        query = '''SELECT season,game_id,sum(runs),sum(pa),sum(outcome IN ('single','double','triple','home_run')),
          sum(outcome='home_run'),sum(outcome='walk'),sum(outcome='hit_by_pitch'),sum(outcome='strikeout'),max(inning)
          FROM plays GROUP BY season,game_id ORDER BY season,game_id'''
        for year, gid, runs, pa, hits, hr, bb, hbp, k, inning in db.execute(query):
            # NULL outcomes on runner events are ignored by SUM; PA classes are exhaustive.
            rows.append({'season': year, 'game_id': gid, 'runs': runs, 'pa': pa, 'h': hits, 'hr': hr, 'bb': bb, 'hbp': hbp, 'k': k, 'extra': inning > 9})
    csv_file(output / 'mlb_reference_games.csv', rows)
    records = {str(year): {'games': sum(r['season'] == year for r in rows),
        'distributions': {k: describe([r[k] for r in rows if r['season'] == year]) for k in ('runs', 'h', 'hr', 'bb', 'hbp', 'k', 'pa')},
        'extra_inning_rate': statistics.mean(r['extra'] for r in rows if r['season'] == year)} for year in (2023, 2024, 2025)}
    write_json(output / 'mlb_reference.json', {'periods': records,
        'limits': ['MLB regular seasons, not NPB; actual actors/tactics differ from synthetic common-league fallback',
                   '2025 is a known reference, never an untouched final test',
                   'reference totals include all real plays including runner-only events; no new acquisition']})


def run_validation(model, output, config, progress=print):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    milestones = config['milestones']
    if milestones != sorted(set(milestones)) or any(type(n) is not int or not 1 <= n <= 10000 for n in milestones):
        raise ValueError('Unique increasing validation milestones <=10000 required')
    rules = GameRules(**config['rules']).validate()
    teams = (fictional_team('LAB_A'), fictional_team('LAB_H'))
    rows = []; failures = []; checkpoints = []; samples = []
    started = time.perf_counter(); last_progress = started
    store = HistoryStore(output / 'sample_history.sqlite3')
    try:
        for index in range(milestones[-1]):
            game_start = time.perf_counter()
            kwargs = dict(seed=config['seed_start'] + index, game_date=config['game_date'], rules=rules,
                          allow_assumptions=config['allow_assumptions'], auto_relief_inning=config['auto_relief_inning'])
            saved = index < config['sample_histories']
            game = Game(model, teams, record=saved, **kwargs)
            result = game.run()
            rows.append(compact(result, time.perf_counter() - game_start))
            if saved:
                store.save(game)
                assert canonical(store.load(game.game_id)) == canonical(result)
                if index == 0:
                    (output / 'sample_replay.jsonl').write_text(''.join(canonical(r) + '\n' for r in game.journal.rows), encoding='utf-8')
                samples.append({'game_id': game.game_id, 'seed': game.seed, 'status': game.status, 'replay_verified': True})
            if result['failure']: failures.append(result['failure'])
            if index + 1 in milestones:
                report = aggregate(rows, time.perf_counter() - started)
                report['milestone'] = index + 1; checkpoints.append(report)
                if report['record_integrity_failures']:raise ValueError('Stop scale expansion on count inconsistency')
                if index+1>=1000 and not league_gate(report):
                    progress('Expansion stopped: 1000-game stability gate failed');break
                write_json(output / 'checkpoints.json', checkpoints)
                progress(f'Validation {index+1}: complete={report["completed_games"]}, failed={report["failed_games"]}')
            if time.perf_counter() - last_progress > 20:
                progress(f'Validation progress: {index+1}/{milestones[-1]} games'); last_progress = time.perf_counter()
    finally:
        store.close()
    final = checkpoints[-1]
    recent = aggregate(rows[-1000:], 0)
    write_json(output / 'recent_1000.json', recent)
    csv_file(output / 'games.csv', rows)
    write_json(output / 'failures.json', {'failures': failures, 'resampled_games': 0})
    write_json(output / 'validation.json', {**final, 'config': config, 'checkpoints': checkpoints,
               'sample_history_replays': samples, 'league_gate_passed': league_gate(final)})
    distributions = []
    for field in ('runs', 'h', 'hr', 'bb', 'k', 'pa'):
        for value, count in sorted(Counter(r[field] for r in rows if r['status'] != 'failed').items()):
            distributions.append({'metric': field, 'value': value, 'n': count, 'population': 'completed_games_only'})
    csv_file(output / 'distributions.csv', distributions)
    team_ids = [f'T{i:02}' for i in range(1, 13)]
    fixture = schedule(team_ids, config['game_date']); csv_file(output / 'schedule_858.csv', fixture)
    write_json(output / 'league_gate.json', {'passed':league_gate(final),
        'reason':'primary full-cohort stop/consistency/priority gate; strict control is reported separately'})
    observed_reference(output)
    return final
