"""Frozen Stage 7 probabilities with richer source-labelled runner routes."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import gzip
import json
from pathlib import Path

from ..calibrated.api import CalibratedModel
from ..calibrated.identity import example_frame
from ..calibrated.rules import Plan, Move, UnsupportedRule, canonical, conservative_plan, frame_dict
from .rules import Credit, Play, RULES_VERSION, apply_play


class NoRoute(UnsupportedRule):
    def __init__(self, outcome, context):
        super().__init__('no_training_route:' + outcome)
        self.outcome, self.context = outcome, context


@dataclass(frozen=True)
class Draw:
    outcome: str
    plays: tuple[Play, ...]
    probability: float
    route_ref: str


def bind(action, mapping, source, reference):
    plan = Plan(action['outcome'], tuple(Move(mapping[m['role']], m['origin'], m['destination']) for m in action['moves']),
                action['completed_pa'], source, reference, action['dropped_third_strike'])
    credit = action['credit']
    credit = Credit(
        at_bat=credit['at_bat'], hit_bases=credit['hit_bases'],
        rbi_ids=None if credit['rbi_roles'] is None else tuple(mapping[r] for r in credit['rbi_roles']),
        sacrifice_bunt=credit['sacrifice_bunt'], sacrifice_fly=credit['sacrifice_fly'],
        ground_double_play=credit['ground_double_play'], source=source)
    return Play(plan, credit, action['batter_reached'], action['third_out'], source == 'empirical',
                mapping[action['transfer_role']] if action['transfer_role'] else None,
                action['responsibility_complete'], action['event_text'])


def assumed_play(frame, outcome):
    if outcome == 'fielders_choice' and frame.base_mask:
        # An explicit deterministic modelling assumption, never an empirical route:
        # retire the most advanced runner, let the batter reach first. If first is
        # occupied by a different live runner, use the legacy first-runner choice.
        origin = 1 if frame.bases[0] else max(i for i, r in enumerate(frame.bases, 1) if r)
        moves = [Move(r.player_id, i, 'OUT' if i == origin else str(i)) for i, r in enumerate(frame.bases, 1) if r]
        moves.append(Move(frame.batter, 0, '1'))
        plan = Plan(outcome, tuple(moves), True, 'assumption', 'declared-fc-runner-choice-1')
    else:
        plan = conservative_plan(frame, outcome)
    hits = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}.get(outcome, 0)
    excluded = ('walk', 'hit_by_pitch', 'interference', 'sacrifice_bunt', 'sacrifice_fly')
    scorers = tuple(m.player_id for m in plan.moves if m.destination == 'H')
    credit = Credit(outcome not in excluded, hits, None if outcome == 'reached_on_error' and scorers else scorers,
                    outcome == 'sacrifice_bunt', outcome == 'sacrifice_fly', outcome == 'double_play', 'assumption')
    transfer = next((r.player_id for r in frame.bases[:1] if r and outcome == 'fielders_choice'), None)
    return Play(plan, credit, hits or int(outcome in ('walk', 'hit_by_pitch', 'interference', 'reached_on_error', 'fielders_choice')),
                responsibility_transfer=transfer)


class GameModel:
    def __init__(self, base, routes):
        if routes['training_seasons'] != [2023, 2024]:
            raise ValueError('Routes must use 2023-2024 only')
        self.base, self.routes = base, routes
        self.route_sha256 = hashlib.sha256(canonical(routes).encode()).hexdigest()
        self.version = 'game-model-1:' + base.version + ':' + self.route_sha256
        self._choices = {}

    @classmethod
    def load(cls, stage7, routes_path):
        base = CalibratedModel.load(stage7)
        routes_path = Path(routes_path)
        routes = json.loads(gzip.decompress(routes_path.read_bytes()) if routes_path.suffix == '.gz' else routes_path.read_bytes())
        if routes['stage7_model_version'] != base.version:
            raise ValueError('Routes and probability model versions differ')
        return cls(base, routes)

    def predict_step(self, frame, **actors):
        return self.base.predict_step(frame, **actors)

    def predict_pa(self, frame, **actors):
        return self.base.predict_pa(frame, **actors)

    def choices(self, frame, outcome, allow_assumptions):
        pre = frame.outs * 8 + frame.base_mask
        key = pre, outcome, frame.inning >= 10, allow_assumptions
        if key not in self._choices:
            group = self.routes['groups'].get(f'{pre}:{outcome}:{int(key[2])}')
            if group is None:
                group = self.routes['groups'].get(f'{pre}:{outcome}:{1-int(key[2])}', [])
            rows = [(r['actions'], r['n'], 'empirical', r['sha256']) for r in group]
            if allow_assumptions:
                try:
                    assumed = assumed_play(example_frame(pre), outcome)
                    apply_play(example_frame(pre), assumed)
                    rows.append((None, 10, 'assumption', assumed.plan.source_ref))
                except (ValueError, UnsupportedRule):
                    pass
            self._choices[key] = rows
        # Censored walkoff-only templates cannot be reused in an ordinary half.
        return self._choices[key]

    def resolve_outcome(self, frame, outcome, rng, *, allow_assumptions=False, probability=1.0):
        rows = self.choices(frame, outcome, allow_assumptions)
        if not rows:
            raise NoRoute(outcome, {'pre_state': frame.outs * 8 + frame.base_mask,
                                   'training_n': 0, 'allow_assumptions': allow_assumptions})
        actions, _, source, reference = rng.choices(rows, weights=[r[1] for r in rows], k=1)[0]
        if source == 'assumption':
            plays = (assumed_play(frame, outcome),)
            try:
                apply_play(frame, plays[0])
            except ValueError as exc:
                exc.context = {'route_ref': reference, 'source': source, 'action_index': 0}
                raise
        else:
            mapping = {'B': frame.batter, **{str(i): r.player_id for i, r in enumerate(frame.bases, 1) if r}}
            plays = []
            for index, action in enumerate(actions):
                if frame.finished:
                    break
                play = bind(action, mapping, source, reference)
                try:
                    frame = apply_play(frame, play).transition.after
                except ValueError as exc:
                    exc.context = {'route_ref': reference, 'source': source, 'action_index': index,
                                   'attempted_action': action, 'attempted_frame': frame_dict(frame),
                                   'original_source': self.routes['sources'].get(reference)}
                    raise
                plays.append(play)
            plays = tuple(plays)
        return Draw(outcome, plays, probability, reference)

    def sample(self, frame, rng, *, allow_assumptions=False, **actors):
        p = self.predict_step(frame, **actors)
        outcome = rng.choices(list(p), weights=list(p.values()), k=1)[0]
        try:
            return self.resolve_outcome(frame, outcome, rng, allow_assumptions=allow_assumptions, probability=p[outcome])
        except (ValueError, UnsupportedRule) as exc:
            exc.outcome = outcome
            exc.context = {**getattr(exc, 'context', {}), 'sampled_probability': p[outcome]}
            raise

    def support_report(self, frame, *, allow_assumptions=False, **actors):
        return [{'outcome': k, 'probability': p,
                 'empirical_n': sum(r[1] for r in self.choices(frame, k, False)),
                 'declared_assumption': any(r[2] == 'assumption' for r in self.choices(frame, k, allow_assumptions))}
                for k, p in self.predict_step(frame, **actors).items()]
