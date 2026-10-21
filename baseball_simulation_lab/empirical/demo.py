"""Coarse score-only demonstration, separate from the Phase 1 pitch engine."""
from __future__ import annotations

import random


def simulate(model, seed=42, max_innings=12):
    rng = random.Random(seed)
    scores = [0, 0]
    steps = []
    for inning in range(1, max_innings + 1):
        for half in (0, 1):
            if half == 1 and inning >= 9 and scores[1] > scores[0]:
                return {'scores': scores, 'steps': steps, 'finished': True}
            outs, bases = 0, 2 if inning >= 10 else 0
            while outs < 3:
                result = model.sample_step(rng, outs=outs, bases=bases, inning=inning, half=half,
                                           batting_score_diff=scores[half] - scores[1 - half])
                steps.append({'inning': inning, 'half': half, 'outs_before': outs, 'bases_before': bases,
                              'outcome': result.outcome, 'runs': result.runs, 'outs_after': result.outs_after,
                              'bases_after': result.bases_after, 'completed_pa': result.completed_pa})
                scores[half] += result.runs
                outs, bases = result.outs_after, result.bases_after
                if len(steps) > 3000:
                    raise RuntimeError('Demo safety step limit reached; no fabricated result returned')
                if half == 1 and inning >= 9 and scores[1] > scores[0]:
                    # Actual walkoff advancement/official hit credit is intentionally not reconstructed.
                    return {'scores': scores, 'steps': steps, 'finished': True}
        if inning >= 9 and scores[0] != scores[1]:
            return {'scores': scores, 'steps': steps, 'finished': True}
    return {'scores': scores, 'steps': steps, 'finished': False, 'limit': 'laboratory inning cap, not MLB rule'}
