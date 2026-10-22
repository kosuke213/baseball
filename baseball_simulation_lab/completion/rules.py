"""Conservative Stage 9 timing evidence; old journals retain old rules."""
from dataclasses import replace
import re

from ..calibrated.rules import Transition, UnsupportedRule
from ..fullgame.rules import (GameRules, Credit, Play, Applied, next_half,
                              play_dict, play_from_dict, apply_play as stage8_apply)

RULES_VERSION = 'completion-rules-1'


def timing_evidence(frame, play):
    """A trailing runner cannot legally reach home before a scoring leader.

    Restrict to one ordinary tag at home, no appeals/errors/force, and no other
    outs. Event string order alone is never treated as chronological evidence.
    """
    p = play.plan
    outs = [m for m in p.moves if m.destination == 'OUT']
    scorers = [m for m in p.moves if m.destination == 'H']
    if (not play.certified or p.source != 'empirical' or len(outs) != 1
            or not scorers or play.credit.hit_bases not in (1, 2, 3)
            or any(marker in play.event_text for marker in ('/AP', '/FO', '/GDP', '/DP', 'E', 'BR', 'OBS'))):
        return None
    need = frame.score[0] - frame.score[1] + 1
    leaders = sorted(scorers, key=lambda m: -m.origin)
    if not 1 <= need <= len(leaders): return None
    winner = leaders[need - 1]
    out = outs[0]
    role = 'B' if out.origin == 0 else str(out.origin)
    # Ordinary 2 (catcher) putout, or another fielding position at home.
    # Exclude appeal/force qualifiers by requiring a digits-only fielding code.
    if (out.origin >= winner.origin or
            re.search(r'(?:\.|;)' + role + r'XH\([1-9]+\)(?:;|$)', play.event_text) is None):
        return None
    return 'trailing_runner_home_tag_after_winning_runner'


def apply_play(frame, play):
    try:
        applied = stage8_apply(frame, play)
    except UnsupportedRule as exc:
        if str(exc) != 'walkoff_out_timing_unknown': raise
        evidence = timing_evidence(frame, play)
        if not evidence: raise
        # Validate the original complete route in a non-game-ending context.
        regular = stage8_apply(replace(frame, inning=1), play)
        t = regular.transition
        need = frame.score[0] - frame.score[1] + 1
        scored = t.scored[:need]
        c = play.credit
        winner = scored[-1].player_id
        origin = next(m.origin for m in play.plan.moves if m.player_id == winner)
        hit_bases = min(c.hit_bases, 4 - origin)
        bases = list(t.after.bases)
        # A batter stretching out at home has already reached all credited bases.
        if frame.batter in t.out_ids:
            from ..calibrated.rules import RunnerToken
            if bases[hit_bases - 1] is not None:
                raise UnsupportedRule('walkoff_hit_credit_requires_touch_order')
            bases[hit_bases - 1] = RunnerToken(frame.batter, frame.pitcher)
        score = (frame.score[0], frame.score[1] + need)
        after = replace(frame, bases=tuple(bases), score=score, finished=True,
                        orders=t.after.orders, balls=t.after.balls, strikes=t.after.strikes)
        people = {r.player_id for r in frame.bases if r} | {frame.batter}
        represented = {r.player_id for r in scored} | {r.player_id for r in bases if r}
        # Once the game has ended, leftover runners are halted, not official LOB.
        halted = tuple(sorted(people - represented))
        transition = Transition(after.validate(), play.plan, scored, (), (), halted, t.completed_pa,
                                rules_version=RULES_VERSION)
        c = replace(c, hit_bases=hit_bases,
                    rbi_ids=None if c.rbi_ids is None else tuple(pid for pid in c.rbi_ids if pid in {r.player_id for r in scored}))
        applied = Applied(transition, c, regular.responsibility_complete)
    return replace(applied, transition=replace(applied.transition, rules_version=RULES_VERSION))
