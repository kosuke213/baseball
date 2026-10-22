"""A balanced laboratory schedule, with a strict full-season execution gate."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta


def schedule(team_ids, start='2026-04-01'):
    if len(team_ids) != 12 or len(set(team_ids)) != 12:
        raise ValueError('The laboratory schedule requires twelve unique teams')
    ring = list(team_ids); rounds = []
    for r in range(11):
        pairs = []
        for i in range(6):
            a, b = ring[i], ring[-1 - i]
            ia, ib = team_ids.index(a), team_ids.index(b)
            if 11 in (ia, ib):
                other = ib if ia == 11 else ia
                home = team_ids[other] if other % 2 == 0 else team_ids[11]
            else:
                home = a if (ib - ia) % 11 in range(1, 6) else b
            pairs.append((b if home == a else a, home))
        rounds.append(pairs)
        ring = [ring[0], ring[-1], *ring[1:-1]]
    games = []
    for leg in range(13):
        for r, pairs in enumerate(rounds):
            matchday = leg * 11 + r
            day = date.fromisoformat(start) + timedelta(days=matchday + matchday // 6)
            for a, b in pairs:
                away, home = (a, b) if leg % 2 == 0 else (b, a)
                games.append({'number': len(games) + 1, 'date': day.isoformat(), 'away': away, 'home': home, 'round': matchday + 1})
    validate_schedule(games, team_ids)
    return games


def validate_schedule(games, team_ids):
    counts = Counter(); pairs = Counter(); day_teams = set()
    for g in games:
        if g['away'] == g['home']: raise ValueError('A team cannot play itself')
        for team in (g['away'], g['home']):
            key = g['date'], team
            if team not in team_ids or key in day_teams: raise ValueError('Duplicate team/date or unknown team')
            day_teams.add(key); counts[team] += 1
        pairs[tuple(sorted((g['away'], g['home'])))] += 1
    if len(games) != 858 or set(counts.values()) != {143} or len(pairs) != 66 or set(pairs.values()) != {13}:
        raise ValueError('Schedule does not satisfy 12 x 143 / 2 with 13 games per pair')
    return True


class Standings:
    def __init__(self, team_ids):
        self.table = {t: {'team_id': t, 'w': 0, 'l': 0, 'd': 0, 'runs_for': 0, 'runs_against': 0} for t in team_ids}
        self.games = set()

    def add(self, result):
        if result['status'] not in ('completed', 'draw'): raise ValueError('Failed game cannot enter standings')
        if result['game_id'] in self.games: raise ValueError('Game already counted')
        a, b = result['team_ids']; x, y = result['score']
        if a == b or a not in self.table or b not in self.table: raise ValueError('Unknown/distinct team IDs required')
        if (result['status'] == 'draw') != (x == y): raise ValueError('Status differs from score')
        self.games.add(result['game_id'])
        for team, scored, allowed in [(a, x, y), (b, y, x)]:
            row = self.table[team]
            row['runs_for'] += scored; row['runs_against'] += allowed
            row['w' if scored > allowed else 'l' if scored < allowed else 'd'] += 1

    def rows(self):
        rows = [{**r, 'games': r['w'] + r['l'] + r['d'], 'win_pct': r['w'] / (r['w'] + r['l']) if r['w'] + r['l'] else None} for r in self.table.values()]
        rows.sort(key=lambda r: (-(r['win_pct'] if r['win_pct'] is not None else -1), -r['w'], r['team_id']))
        previous = None; rank = 0
        for i, r in enumerate(rows, 1):
            key = r['win_pct'], r['w']
            if key != previous: rank = i
            r['rank'] = rank; previous = key
        return rows


def league_gate(validation):
    return (validation['attempted_games'] >= 1000 and validation['failed_games'] == 0
            and validation['record_integrity_failures'] == 0 and validation['unresolved_priority_records'] == 0)
