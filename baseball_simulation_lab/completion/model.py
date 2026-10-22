"""Frozen Stage 7 probabilities with richer source-labelled runner routes."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import gzip
import json
import math
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


from ..fullgame.model import assumed_play


class GameModel:
    def __init__(self, base, routes, terminal):
        if routes['training_seasons'] != [2023, 2024]:
            raise ValueError('Routes must use 2023-2024 only')
        self.base, self.routes, self.terminal = base, routes, terminal
        if terminal["training_seasons"] != [2023, 2024]:
            raise ValueError("Terminal risk cannot learn from 2025")
        if set(terminal['states']) != {str(i) for i in range(24)}:
            raise ValueError('All 24 terminal risk states required')
        for cell in terminal['states'].values():
            n, k = cell['exposure'], cell['half_end_no_pa']
            if (type(n) is not int or type(k) is not int or n <= 0 or not 0 <= k <= n
                    or cell['pa_complete'] + k != n or cell['p_half_end_no_pa'] != k/n):
                raise ValueError('Terminal risk estimate disagrees with counts')
        self.route_sha256 = hashlib.sha256(canonical(routes).encode()).hexdigest()
        self.version = 'completion-model-1:' + base.version + ':' + hashlib.sha256(canonical({'routes': self.route_sha256, 'terminal': terminal, 'roe_prior': 'empirical_only'}).encode()).hexdigest()
        self._choices = {}

    @classmethod
    def load(cls, stage7, routes_path, terminal_path, *, verify=True):
        if verify:
            from ..empirical.common import sha_file
            directory = Path(routes_path).parent
            manifest = json.loads((directory / 'model_manifest.json').read_text())
            for path in (Path(routes_path), Path(terminal_path)):
                if path.resolve().parent != directory.resolve() or sha_file(path) != manifest['files'][path.name]:
                    raise ValueError('Stage 9 model checksum mismatch')
        base = CalibratedModel.load(stage7)
        routes_path = Path(routes_path)
        routes = json.loads(gzip.decompress(routes_path.read_bytes()) if routes_path.suffix == '.gz' else routes_path.read_bytes())
        if routes['stage7_model_version'] != base.version:
            raise ValueError('Routes and probability model versions differ')
        model = cls(base, routes, json.loads(Path(terminal_path).read_text()))
        if verify and model.version != manifest['model_version']:
            raise ValueError('Stage 9 model version mismatch')
        return model

    def predict_step(self, frame, **actors):
        p = self.predict_pa(frame, **actors)
        hazard = self.terminal['states'][str(frame.outs * 8 + frame.base_mask)]['p_half_end_no_pa']
        return {**{k: (1 - hazard) * v for k, v in p.items()}, 'runner_only_end': hazard}

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
            if allow_assumptions and outcome != 'reached_on_error':
                try:
                    assumed = assumed_play(example_frame(pre), outcome)
                    apply_play(example_frame(pre), assumed)
                    rows.append((None, 10, 'assumption', assumed.plan.source_ref))
                except (ValueError, UnsupportedRule):
                    pass
            self._choices[key] = rows
        # No scorer-judgment ROE prior: outcome mass is retained, using observed routes.
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
