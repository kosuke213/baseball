"""Versioned calibrated window model + ID transition API, standard library only."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from ..empirical.api import EmpiricalModel, normalized
from ..empirical.common import OUTCOMES, sha_file
from .identity import bind_action, template_choices
from .rules import RULES_VERSION, Frame, Plan, Transition, UnsupportedRule, apply_plan, conservative_plan


def calibrate(probabilities, parameters, league):
    temperature = parameters['temperature']
    weight = parameters['league_weight']
    powered = normalized([p ** (1 / temperature) for p in probabilities])
    return normalized([(1 - weight) * p + weight * q for p, q in zip(powered, league)])


@dataclass(frozen=True)
class WindowResult:
    after: Frame
    sampled_outcome: str
    transitions: tuple[Transition, ...]
    model_version: str
    rules_version: str = RULES_VERSION

    @property
    def scored(self):
        return tuple(r for t in self.transitions for r in t.scored)

    @property
    def out_ids(self):
        return tuple(pid for t in self.transitions for pid in t.out_ids)

    @property
    def completed_pa(self):
        return any(t.completed_pa for t in self.transitions)


class CalibratedModel:
    def __init__(self, base_model, kernels, templates, calibration, version):
        self.base = EmpiricalModel(base_model, kernels)
        self.templates = templates
        self.calibration = calibration
        self.version = version
        if templates['training_seasons'] != [2023, 2024] or calibration['fit_period'] != '2024-H1':
            raise ValueError('Unexpected model training/calibration contract')

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        names = ['base_model.json', 'kernels.json', 'identity_model.json', 'calibration.json']
        values = {}
        for name in names:
            if sha_file(directory / name) != manifest['files'][name]:
                raise ValueError('Stage 7 model checksum mismatch')
            values[name] = json.loads((directory / name).read_text(encoding='utf-8'))
        return cls(*(values[n] for n in names), version=manifest['snapshot_id'])

    def features(self, frame, *, batter_hand='unknown', pitcher_hand='unknown', batter_model_id='', pitcher_model_id=''):
        frame.validate()
        if frame.finished or frame.outs == 3:
            raise ValueError('No prediction for a closed attack')
        return dict(outs=frame.outs, bases=frame.base_mask, inning=frame.inning, half=frame.half,
                    batting_score_diff=frame.score[frame.half] - frame.score[1 - frame.half],
                    batter_hand='B' if batter_hand == 'S' else batter_hand, pitcher_hand=pitcher_hand,
                    batter_id=batter_model_id, pitcher_id=pitcher_model_id)

    def predict_pa(self, frame, **actors):
        features = self.features(frame, **actors)
        p = self.base.predict_pa(**features)
        league = self.base.model['tables']['league']['p']
        from ..empirical.common import outcome_mask
        mask = outcome_mask(frame.outs * 8 + frame.base_mask)[:-1]
        q = normalized([v if ok else 0 for v, ok in zip(league[:-1], mask)])
        calibrated = calibrate(list(p.values()), self.calibration['parameters'], q)
        # A preceding runner is required for an FC PA. This is a rules constraint,
        # separate from calibration, and is also applied in ID-model evaluation.
        if frame.base_mask == 0:
            calibrated[OUTCOMES.index('fielders_choice')] = 0
            calibrated = normalized(calibrated)
        return dict(zip(OUTCOMES[:-1], calibrated))

    def predict_step(self, frame, **actors):
        p = self.base.predict_step(**self.features(frame, **actors))
        aborted = p['runner_only_end']
        result = {k: (1 - aborted) * v for k, v in self.predict_pa(frame, **actors).items()}
        result['runner_only_end'] = aborted
        return result

    def resolve_outcome(self, frame, outcome, rng, *, allow_assumptions=False):
        """Resolve a sampled observed-window result; intermediate plays retain IDs.

        Missing support raises. Assumed routes require an explicit opt-in and
        carry source='assumption' in every generated event.
        """
        self.features(frame)
        if outcome == 'double_play':
            if not allow_assumptions:
                raise UnsupportedRule('Explicit generic double play requires an assumed route')
            transition = apply_plan(frame, conservative_plan(frame, outcome))
            return WindowResult(transition.after, outcome, (transition,), self.version)
        candidates = template_choices(self.templates, frame.outs * 8 + frame.base_mask, outcome, frame.inning >= 10)
        if not allow_assumptions:
            candidates = [c for c in candidates if c[2] == 'empirical']
        if not candidates:
            raise UnsupportedRule('No supported empirical route; no silent resampling or guessed runner choice')
        actions, _, source, reference = rng.choices(candidates, weights=[c[1] for c in candidates], k=1)[0]
        mapping = {'B': frame.batter, **{str(i): r.player_id for i, r in enumerate(frame.bases, 1) if r}}
        transitions = []
        for action in actions:
            if frame.finished:
                break
            plan = bind_action(action, mapping, reference)
            if source == 'assumption':
                plan = replace(plan, source='assumption')
            transition = apply_plan(frame, plan)
            transitions.append(transition); frame = transition.after
        return WindowResult(frame, outcome, tuple(transitions), self.version)

    def sample(self, frame, rng, *, allow_assumptions=False, **actors):
        p = self.predict_step(frame, **actors)
        outcome = rng.choices(list(p), weights=list(p.values()), k=1)[0]
        return self.resolve_outcome(frame, outcome, rng, allow_assumptions=allow_assumptions)

    def support_report(self, frame, **actors):
        rows = []
        for outcome, probability in self.predict_step(frame, **actors).items():
            choices = template_choices(self.templates, frame.outs * 8 + frame.base_mask, outcome, frame.inning >= 10)
            rows.append({'outcome': outcome, 'probability': probability,
                         'empirical_n': sum(c[1] for c in choices if c[2] == 'empirical'),
                         'assumption_available': any(c[2] == 'assumption' for c in choices)})
        return rows
