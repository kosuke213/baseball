"""Lightweight probability-table API; only Python's standard library is required."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from .common import END, OUTCOMES, feature_keys, legal_targets, outcome_mask, sha_file, state


@dataclass(frozen=True)
class Step:
    outcome: str
    outs_after: int
    bases_after: int
    runs: int
    completed_pa: bool
    half_ended: bool


def normalized(values):
    if any(not math.isfinite(v) or v < 0 for v in values) or sum(values) <= 0:
        raise ValueError('Invalid probability vector')
    total = sum(values)
    return [v / total for v in values]


class EmpiricalModel:
    """A step spans observed runner-only plays until a PA or half/game end.

    It does not generate pitches, runner identities, pitcher attribution, or
    official scoring. Apply game-ending and automatic-runner rules separately.
    """
    def __init__(self, model, kernels):
        if model['outcomes'] != list(OUTCOMES) or model['training_seasons'] != [2023, 2024]:
            raise ValueError('Unsupported probability-table contract or training seasons')
        self.model, self.kernels = model, kernels

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        for name in ('model.json', 'kernels.json'):
            if sha_file(directory / name) != manifest['files'][name]:
                raise ValueError('Probability-table checksum mismatch')
        return cls(json.loads((directory / 'model.json').read_text(encoding='utf-8')),
                   json.loads((directory / 'kernels.json').read_text(encoding='utf-8')))

    def predict_step(self, *, outs, bases, batter_hand='unknown', pitcher_hand='unknown',
                     inning=1, batting_score_diff=0, half=0, batter_id='', pitcher_id=''):
        pre = state(outs, bases)
        keys = feature_keys(outs=outs, bases=bases, batter_hand=batter_hand, pitcher_hand=pitcher_hand,
                            inning=inning, batting_score_diff=batting_score_diff, half=half,
                            batter_id=batter_id, pitcher_id=pitcher_id)
        tables = self.model['tables']
        league = tables['league']['p']
        hands = tables['hands'].get(keys['hands'], {}).get('p', league)
        context = tables['context'].get(keys['context'], {}).get('p', hands)
        batter = tables['batter'].get(keys['batter'], {}).get('p', league)
        pitcher = tables['pitcher'].get(keys['pitcher'], {}).get('p', league)
        weight = self.model['settings']['player_weight']
        values = [(1 - weight) * c + weight * (b + p) / 2 for c, b, p in zip(context, batter, pitcher)]
        allowed = outcome_mask(pre)
        values = normalized([p if ok else 0.0 for p, ok in zip(values, allowed)])
        return dict(zip(OUTCOMES, values))

    def predict_pa(self, **features):
        """14 outcomes, conditional on this observed window completing a PA."""
        p = self.predict_step(**features)
        values = normalized([p[k] for k in OUTCOMES[:-1]])
        return dict(zip(OUTCOMES[:-1], values))

    def transitions(self, outcome, *, outs, bases, extra_innings=False):
        pre = state(outs, bases)
        if outcome not in OUTCOMES or not legal_targets(pre, outcome):
            raise ValueError('Outcome is unsupported in this base/out state')
        key = f'{pre}:{outcome}:{int(extra_innings)}'
        table = self.kernels['conditional'][key]
        return [{'post_state': post, 'runs': runs, 'probability': p}
                for (post, runs), p in zip(table['targets'], table['p'])]

    def predict_next_state_runs(self, **features):
        p = self.predict_step(**features)
        joint = {}
        for outcome, weight in p.items():
            if weight == 0:
                continue
            for row in self.transitions(outcome, outs=features['outs'], bases=features['bases'],
                                        extra_innings=features.get('inning', 1) >= 10):
                key = row['post_state'], row['runs']
                joint[key] = joint.get(key, 0.0) + weight * row['probability']
        return [{'post_state': post, 'runs': runs, 'probability': value}
                for (post, runs), value in sorted(joint.items())]

    def predict_state_baseline(self, *, outs, bases, extra_innings=False):
        """Direct empirical pre-state baseline, independently scored on 2025."""
        table = self.kernels['state_baseline'][f'{state(outs, bases)}:{int(extra_innings)}']
        return [{'post_state': post, 'runs': runs, 'probability': p}
                for (post, runs), p in zip(table['targets'], table['p'])]

    def sample_step(self, rng, **features):
        """Sample outcome, then a JOINT post-state/runs pair; never independently."""
        probabilities = self.predict_step(**features)
        outcome = rng.choices(list(probabilities), weights=list(probabilities.values()), k=1)[0]
        targets = self.transitions(outcome, outs=features['outs'], bases=features['bases'],
                                   extra_innings=features.get('inning', 1) >= 10)
        row = rng.choices(targets, weights=[r['probability'] for r in targets], k=1)[0]
        ended = row['post_state'] == END
        outs, bases = (3, 0) if ended else divmod(row['post_state'], 8)
        return Step(outcome, outs, bases, row['runs'], outcome != 'runner_only_end', ended)
