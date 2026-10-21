"""Pre-step features and finite, coarse base/out support (standard library only)."""
from __future__ import annotations

import hashlib
from functools import lru_cache
import json
from pathlib import Path

OUTCOMES = ('single', 'double', 'triple', 'home_run', 'sacrifice_bunt', 'sacrifice_fly',
            'hit_by_pitch', 'walk', 'strikeout', 'interference', 'reached_on_error',
            'fielders_choice', 'other_out', 'other_pa', 'runner_only_end')
RAW_OUTCOMES = ('single', 'double', 'triple', 'hr', 'sh', 'sf', 'hbp', 'walk', 'k',
                'xi', 'roe', 'fc', 'othout', 'noout')
END = 24


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha_file(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def state(outs, bases):
    if type(outs) is not int or type(bases) is not int or not 0 <= outs < 3 or not 0 <= bases < 8:
        raise ValueError('outs must be 0..2; bases must be a bit mask 0..7')
    return outs * 8 + bases


def base_mask(values):
    return sum((1 << i) for i, value in enumerate(values) if value)


def feature_keys(*, outs, bases, batter_hand, pitcher_hand, inning, batting_score_diff,
                 half, batter_id='', pitcher_id=''):
    state(outs, bases)
    if type(inning) is not int or inning < 1 or half not in (0, 1):
        raise ValueError('inning >= 1 and half 0 (top) or 1 (bottom) are required')
    if type(batting_score_diff) is not int:
        raise ValueError('batting_score_diff must be an integer known before the step')
    # B is the published switch-hitter category, not an inferred stance.
    bh = batter_hand if batter_hand in ('L', 'R', 'B') else 'unknown'
    ph = pitcher_hand if pitcher_hand in ('L', 'R') else 'unknown'
    hands = canonical([bh, ph])
    inning_band = '1-3' if inning <= 3 else '4-6' if inning <= 6 else '7-9' if inning <= 9 else '10+'
    diff_band = '<=-3' if batting_score_diff <= -3 else '-2,-1' if batting_score_diff < 0 else '0' if batting_score_diff == 0 else '1,2' if batting_score_diff < 3 else '>=3'
    context = canonical([outs, bases, bh, ph, inning_band, diff_band, half])
    return {'hands': hands, 'context': context, 'batter': batter_id or '', 'pitcher': pitcher_id or ''}


@lru_cache(maxsize=360)
def legal_targets(pre_state, outcome):
    """Count-conserving support, not a replacement for MLB's full scoring rules.

    The source unit can include runner events before a completed PA. At END,
    remaining runners are left on base and not carried to the next half.
    """
    outs, bases = divmod(pre_state, 8)
    runners = bases.bit_count()
    added = int(outcome != 'runner_only_end')
    if outcome in ('sacrifice_bunt', 'sacrifice_fly') and (outs == 2 or runners == 0):
        return ()
    targets = []
    for post in range(25):
        post_outs, post_bases = (3, 0) if post == END else divmod(post, 8)
        delta = post_outs - outs
        if delta < 0:
            continue
        if outcome == 'other_out' and delta == 0:
            continue
        if outcome == 'home_run' and (post == END or post_bases != 0):
            continue
        for runs in range(5):
            remaining = runners + added - delta - runs
            if (post != END and remaining != post_bases.bit_count()) or (post == END and remaining < 0):
                continue
            if outcome == 'runner_only_end' and post != END:
                # Non-PA game endings are censored, not completed model steps.
                continue
            targets.append((post, runs))
    return tuple(targets)


@lru_cache(maxsize=24)
def outcome_mask(pre_state):
    return tuple(bool(legal_targets(pre_state, outcome)) for outcome in OUTCOMES)
