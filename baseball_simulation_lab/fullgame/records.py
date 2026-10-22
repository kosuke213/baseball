"""Observed event scorebook. Unknown official fields remain null, never guessed."""
from __future__ import annotations

from collections import Counter


class Scorebook:
    def __init__(self, initial, teams):
        self.teams = teams
        self.side = {}
        self.batting = {}; self.pitching = {}
        self.starters = initial.pitchers
        self.lines = {}
        self.sources = Counter()
        self.major = []
        self.last_lead = None
        self.unknown_rbi = set(); self.unknown_responsibility = set()
        for side, team in enumerate(teams):
            for pid in team['lineup'] + team['bench']:
                self.side[pid] = side
            for pid in (team['starter'], *team['bullpen']):
                self.side[pid] = side
        for side, lineup in enumerate(initial.lineups):
            for pid in lineup: self.register_batter(pid, side)
            self.register_pitcher(initial.pitchers[side], side)
        self.start_half(initial)

    def register_batter(self, pid, side):
        self.side[pid] = side
        self.batting.setdefault(pid, dict.fromkeys(('pa', 'ab', 'h', 'double', 'triple', 'hr', 'bb', 'hbp', 'k', 'r', 'rbi', 'sh', 'sf', 'ci'), 0))

    def register_pitcher(self, pid, side):
        self.side[pid] = side
        self.pitching.setdefault(pid, dict.fromkeys(('outs', 'bf', 'h', 'hr', 'bb', 'hbp', 'k', 'runs_charged'), 0))

    def start_half(self, frame):
        self.lines.setdefault(frame.inning, [None, None])[frame.half] = 0

    def observe(self, before, applied):
        t, c = applied.transition, applied.credit
        after, outcome = t.after, t.plan.outcome
        self.sources[t.plan.source] += 1
        self.register_pitcher(before.pitcher, 1 - before.half)
        ps = self.pitching[before.pitcher]
        ps['outs'] += after.outs - before.outs
        self.lines.setdefault(before.inning, [None, None])[before.half] = (self.lines.get(before.inning, [None, None])[before.half] or 0) + len(t.scored)
        if t.completed_pa:
            bid = before.batter; self.register_batter(bid, before.half)
            bs = self.batting[bid]
            bs['pa'] += 1; ps['bf'] += 1; bs['ab'] += int(c.at_bat)
            bs['h'] += int(c.hit_bases > 0); ps['h'] += int(c.hit_bases > 0)
            for distance, label in [(2, 'double'), (3, 'triple'), (4, 'hr')]: bs[label] += int(c.hit_bases == distance)
            ps['hr'] += int(c.hit_bases == 4)
            for label, event in [('bb', 'walk'), ('hbp', 'hit_by_pitch'), ('k', 'strikeout'), ('ci', 'interference')]:
                bs[label] += outcome == event
                if label in ps: ps[label] += outcome == event
            bs['sh'] += c.sacrifice_bunt; bs['sf'] += c.sacrifice_fly
            if c.rbi_ids is None:
                if t.scored: self.unknown_rbi.add(bid)
            else:
                bs['rbi'] += len(c.rbi_ids)
        if not applied.responsibility_complete:
            self.unknown_responsibility.update(r.responsible_pitcher for r in before.bases if r)
            self.unknown_responsibility.add(before.pitcher)
        score = list(before.score)
        for runner in t.scored:
            self.register_batter(runner.player_id, before.half)
            self.batting[runner.player_id]['r'] += 1
            self.register_pitcher(runner.responsible_pitcher, 1 - before.half)
            self.pitching[runner.responsible_pitcher]['runs_charged'] += 1
            score[before.half] += 1
            if score[0] == score[1]:
                self.last_lead = None
            elif score[before.half] == score[1 - before.half] + 1:
                self.last_lead = {'side': before.half, 'candidate': before.pitchers[before.half],
                                  'loser': runner.responsible_pitcher,
                                  'responsibility_complete': applied.responsibility_complete}
        if t.scored or c.hit_bases == 4 or len(t.out_ids) > 1:
            self.major.append({'inning': before.inning, 'half': before.half, 'batter': before.batter,
                               'pitcher': before.pitcher, 'outcome': outcome, 'credited_hit_bases': c.hit_bases,
                               'scorers': [r.player_id for r in t.scored], 'out_ids': list(t.out_ids),
                               'score': list(after.score), 'source': t.plan.source})

    def decisions(self, frame, status):
        if status != 'completed':
            return {'status': 'not_applicable' if status == 'draw' else 'incomplete_game', 'winner': None, 'loser': None}
        if not self.last_lead or not self.last_lead['responsibility_complete'] or self.last_lead['loser'] in self.unknown_responsibility:
            return {'status': 'manual_review_run_responsibility', 'winner': None, 'loser': None}
        lead = self.last_lead; winner = lead['candidate']; side = lead['side']
        relievers = [p for p in self.pitching if self.side[p] == side and p != self.starters[side]]
        if winner == self.starters[side] and self.pitching[winner]['outs'] < 15:
            if len(relievers) == 1:
                winner = relievers[0]
            else:
                return {'status': 'manual_review_starter_minimum', 'winner': None, 'loser': lead['loser']}
        elif winner != self.starters[side] and len(relievers) > 1:
            return {'status': 'manual_review_relief_effectiveness', 'winner': None, 'loser': lead['loser']}
        return {'status': 'determined_within_supported_rules', 'winner': winner, 'loser': lead['loser']}

    def export(self, frame, status):
        batting = {pid: {**s, 'rbi': None if pid in self.unknown_rbi else s['rbi'],
                          'team_id': self.teams[self.side[pid]]['team_id']} for pid, s in sorted(self.batting.items())}
        pitching = {pid: {**{k: v for k, v in s.items() if k != 'runs_charged'},
                           'r': None if pid in self.unknown_responsibility else s['runs_charged'],
                           'ip_display': f'{s["outs"] // 3}.{s["outs"] % 3}',
                           'er': None, 'save': None, 'hold': None,
                           'team_id': self.teams[self.side[pid]]['team_id']} for pid, s in sorted(self.pitching.items())}
        totals = []
        for side in (0, 1):
            bs = [s for pid, s in self.batting.items() if self.side[pid] == side]
            totals.append({'team_id': self.teams[side]['team_id'], 'r': frame.score[side],
                           **{k: sum(s[k] for s in bs) for k in ('pa', 'ab', 'h', 'double', 'triple', 'hr', 'bb', 'hbp', 'k', 'sh', 'sf', 'ci')}})
        return {'batting': batting, 'pitching': pitching, 'team_totals': totals,
                'linescore': [{'inning': inning, 'away': r[0], 'home': r[1]} for inning, r in sorted(self.lines.items())],
                'pitcher_decisions': self.decisions(frame, status),
                'scoring_status': {'basic_counts': 'verified_event_counts', 'rbi_complete': not self.unknown_rbi,
                                   'run_responsibility_complete': not self.unknown_responsibility,
                                   'earned_runs_saves_holds': 'not_implemented', 'full_official_record': False},
                'source_actions': dict(self.sources), 'major_events': self.major}

    def validate(self, frame):
        for side in (0, 1):
            batting = [s for p, s in self.batting.items() if self.side[p] == side]
            opposing = [s for p, s in self.pitching.items() if self.side[p] == 1 - side]
            if sum(s['r'] for s in batting) != frame.score[side]:
                raise ValueError('Player runs differ from scoreboard')
            if sum(s['runs_charged'] for s in opposing) != frame.score[side]:
                raise ValueError('Charged run partition differs from scoreboard')
            for bat, pit in [('h', 'h'), ('hr', 'hr'), ('bb', 'bb'), ('hbp', 'hbp'), ('k', 'k'), ('pa', 'bf')]:
                if sum(s[bat] for s in batting) != sum(s[pit] for s in opposing):
                    raise ValueError('Batting/pitching totals differ: ' + bat)
            if sum((r[side] or 0) for r in self.lines.values()) != frame.score[side]:
                raise ValueError('Linescore differs from scoreboard')
            started = sum(r[1 - side] is not None for r in self.lines.values())
            expected_outs = 3 * started
            if frame.half == 1 - side:
                expected_outs += frame.outs - 3
            if sum(s['outs'] for p, s in self.pitching.items() if self.side[p] == side) != expected_outs:
                raise ValueError('Pitching outs differ from completed/current halves')
            if any(s['ab'] + s['bb'] + s['hbp'] + s['sh'] + s['sf'] + s['ci'] != s['pa'] for s in batting):
                raise ValueError('PA/AB partition is inconsistent')
        return True
