"""Independent full games using one observed-window draw at a time."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import random

from ..calibrated.rules import Frame, UnsupportedRule, canonical, frame_dict
from .history import GameJournal, perform
from .records import Scorebook
from .rules import GameRules, RULES_VERSION, play_dict

ENGINE_VERSION = 'stability-engine-1'


@dataclass(frozen=True)
class Team:
    team_id: str
    lineup: tuple[str, ...]
    starter: str
    bench: tuple[str, ...] = ()
    bullpen: tuple[str, ...] = ()

    def validate(self):
        ids = (*self.lineup, self.starter, *self.bench, *self.bullpen)
        if not self.team_id or len(self.lineup) != 9 or len(ids) != len(set(ids)) or any(not isinstance(p, str) or not p for p in ids):
            raise ValueError('Team requires a unique DH lineup and unique roster IDs')
        return self


def fictional_team(team_id):
    return Team(team_id, tuple(f'{team_id}:B{i:02}' for i in range(1, 10)), f'{team_id}:P01',
                tuple(f'{team_id}:B{i:02}' for i in (10, 11, 12)), (f'{team_id}:P02', f'{team_id}:P03')).validate()


def request(teams, seed, game_date, rules, allow_assumptions, auto_relief_inning):
    rules.validate(); date.fromisoformat(game_date)
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('Seed must fit a nonnegative signed 64-bit integer')
    if len(teams) != 2 or teams[0].team_id == teams[1].team_id:
        raise ValueError('Two distinct teams required')
    all_ids = []
    for team in teams:
        team.validate(); all_ids.extend((*team.lineup, team.starter, *team.bench, *team.bullpen))
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('Player IDs must be globally unique across teams')
    if type(allow_assumptions) is not bool or (auto_relief_inning is not None and (type(auto_relief_inning) is not int or auto_relief_inning < 2)):
        raise ValueError('Invalid explicit experiment policy')
    return {'teams': [asdict(t) for t in teams], 'seed': seed, 'game_date': game_date,
            'rules': asdict(rules), 'allow_assumptions': allow_assumptions,
            'auto_relief_inning': auto_relief_inning, 'engine_version': ENGINE_VERSION}


class Game:
    def __init__(self, model, teams, *, seed=8000, game_date='2026-04-01', rules=None,
                 allow_assumptions=False, auto_relief_inning=None, record=True, journal_path=None):
        self.rules = rules or GameRules()
        self.request = request(teams, seed, game_date, self.rules, allow_assumptions, auto_relief_inning)
        self.model = model; self.teams = teams; self.seed = seed; self.rng = random.Random(seed)
        self.frame = Frame(tuple(t.lineup for t in teams), tuple(t.starter for t in teams)).validate()
        self.game_id = hashlib.sha256(canonical({'request': self.request, 'model': model.version,
                                               'rules_version': RULES_VERSION}).encode()).hexdigest()[:32]
        self.journal = GameJournal(self.frame, self.request, model.version, journal_path) if record else None
        if journal_path and not record: raise ValueError('A journal path requires history recording')
        self.book = Scorebook(self.frame, self.request['teams'])
        self.status = 'in_progress'; self.reason = None; self.failure = None
        self.windows = 0; self.completed_halves = 0; self.attempted_halves = 1; self.walkoff = False

    def _act(self, operation, parameters):
        before = self.frame
        if self.journal:
            self.frame, applied = self.journal.append(operation, parameters)
        else:
            self.frame, applied = perform(self.frame, operation, parameters)
        if applied:
            self.book.observe(before, applied)
            if self.frame.outs == 3: self.completed_halves += 1
        elif operation == 'advance_half_v2' and not self.frame.finished:
            self.attempted_halves += 1; self.book.start_half(self.frame)
        elif operation == 'change_pitcher':
            self.book.register_pitcher(self.frame.pitcher, 1 - self.frame.half)
        elif operation == 'substitute':
            self.book.register_batter(parameters['player_id'], parameters['side'])
        return applied

    def change_pitcher(self, player_id):
        if self.status != 'in_progress': raise ValueError('Closed game')
        if player_id not in self.teams[1 - self.frame.half].bullpen:
            raise ValueError('Pitcher is not in the fielding roster bullpen')
        self._act('change_pitcher', {'player_id': player_id})

    def substitute(self, side, slot, player_id, *, pinch_runner=False):
        if self.status != 'in_progress': raise ValueError('Closed game')
        if side not in (0, 1) or player_id not in self.teams[side].bench:
            raise ValueError('Substitute must be on that team bench')
        self._act('substitute', {'side': side, 'slot': slot, 'player_id': player_id, 'pinch_runner': pinch_runner})

    def step(self):
        if self.status != 'in_progress': raise ValueError('Game already closed')
        try:
            if self.frame.outs == 3:
                self._act('advance_half_v2', asdict(self.rules))
                if self.frame.finished:
                    return self._finish('draw' if self.frame.score[0] == self.frame.score[1] else 'completed',
                                        'inning_limit_draw' if self.frame.score[0] == self.frame.score[1] else 'halves_complete')
            policy = self.request['auto_relief_inning']
            side = 1 - self.frame.half
            if policy and self.frame.inning >= policy and self.frame.outs == 0 and not self.frame.base_mask and self.frame.pitcher == self.teams[side].starter and self.teams[side].bullpen:
                self.change_pitcher(self.teams[side].bullpen[0])
            if self.windows >= self.rules.max_windows:
                raise UnsupportedRule('window_safety_limit')
            self.windows += 1
            draw = self.model.sample(self.frame, self.rng, allow_assumptions=self.request['allow_assumptions'])
            self._act('draw', {'outcome': draw.outcome, 'probability': draw.probability,
                               'route_ref': draw.route_ref, 'window_number': self.windows})
            for play in draw.plays:
                self._act('play_v2', play_dict(play))
                if self.frame.finished:
                    self.walkoff = True
                    return self._finish('completed', 'walkoff')
            self.book.validate(self.frame)
        except (UnsupportedRule, ValueError) as exc:
            self.status = 'failed'; self.reason = str(exc)
            self.failure = {'reason': str(exc), 'exception': type(exc).__name__, 'game_id': self.game_id,
                'seed': self.seed, 'window_number': self.windows, 'frame': frame_dict(self.frame),
                'batter': self.frame.batter, 'pitcher': self.frame.pitcher,
                'sampled_outcome': getattr(exc, 'outcome', None), 'context': getattr(exc, 'context', None),
                'model_version': self.model.version, 'rules_version': RULES_VERSION,
                'rng_state_after_failure': self.rng.getstate()}
            self._act('stop', self.failure)
        return self.status

    def _finish(self, status, reason):
        self.book.validate(self.frame)
        self.status, self.reason = status, reason
        self._act('finish', {'status': status, 'reason': reason, 'windows': self.windows,
                             'completed_halves': self.completed_halves, 'attempted_halves': self.attempted_halves,
                             'walkoff': self.walkoff})
        return status

    def run(self):
        while self.status == 'in_progress': self.step()
        return self.result()

    def result(self):
        if self.status == 'in_progress': raise ValueError('Cannot publish an unfinished game')
        integrity_errors = []
        try:
            self.book.validate(self.frame)
        except ValueError as exc:
            if self.status != 'failed': raise
            integrity_errors.append(str(exc))
        return {'schema_version': 1, 'storage_schema_version': 'stability-history-1', 'game_id': self.game_id, 'game_date': self.request['game_date'],
                'team_ids': [t.team_id for t in self.teams], 'status': self.status, 'reason': self.reason,
                'seed': self.seed, 'model_version': self.model.version, 'rules_version': RULES_VERSION,
                'engine_version': ENGINE_VERSION, 'score': list(self.frame.score), 'final_frame': frame_dict(self.frame),
                'windows': self.windows, 'completed_halves': self.completed_halves, 'attempted_halves': self.attempted_halves,
                'extra_innings': self.frame.inning > 9, 'walkoff': self.walkoff,
                'failure': self.failure, 'event_history_recorded': self.journal is not None,
                'record_integrity': {'passed': not integrity_errors, 'errors': integrity_errors},
                **self.book.export(self.frame, self.status)}
