"""Additive rules over the frozen Stage 7 identity contract.

Source adjudications certify recorded runs, not invented within-play timing.
The original rule implementation and its replay version remain unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re

from ..calibrated import rules as legacy
from ..calibrated.rules import Frame, Move, Plan, RunnerToken, Transition, UnsupportedRule

RULES_VERSION = 'fullgame-rules-1'


@dataclass(frozen=True)
class GameRules:
    max_innings: int | None = 12
    allow_draw: bool = True
    automatic_runner_start: int | None = None
    max_windows: int = 1500

    def validate(self):
        if type(self.allow_draw) is not bool:
            raise ValueError('Draw setting must be boolean')
        if self.max_innings is not None and (type(self.max_innings) is not int or self.max_innings < 9):
            raise ValueError('Maximum innings must be >=9 or None')
        if self.allow_draw and self.max_innings is None:
            raise ValueError('A draw requires a configured inning limit')
        if self.automatic_runner_start is not None and (type(self.automatic_runner_start) is not int or self.automatic_runner_start < 10):
            raise ValueError('Automatic runner starts at inning >=10 or is disabled')
        if type(self.max_windows) is not int or not 1 <= self.max_windows <= 10000:
            raise ValueError('Invalid laboratory safety limit')
        return self


@dataclass(frozen=True)
class Credit:
    at_bat: bool
    hit_bases: int = 0
    rbi_ids: tuple[str, ...] | None = ()
    sacrifice_bunt: bool = False
    sacrifice_fly: bool = False
    ground_double_play: bool | None = False
    source: str = 'explicit_event'


@dataclass(frozen=True)
class Play:
    plan: Plan
    credit: Credit
    batter_reached: int = 0
    third_out: str = 'unspecified'
    certified: bool = False
    responsibility_transfer: str | None = None
    responsibility_complete: bool = True
    event_text: str = ''


@dataclass(frozen=True)
class Applied:
    transition: Transition
    credit: Credit
    responsibility_complete: bool


def play_dict(play):
    return asdict(play)


def play_from_dict(value):
    value = dict(value)
    value['plan'] = legacy.plan_from_dict(value['plan'])
    credit = dict(value['credit'])
    credit['rbi_ids'] = None if credit['rbi_ids'] is None else tuple(credit['rbi_ids'])
    value['credit'] = Credit(**credit)
    return Play(**value)


def next_half(frame, rules):
    rules.validate(); frame.validate()
    if frame.finished or frame.outs != 3:
        raise ValueError('Only a closed half may advance')
    # Winning conditions precede a tie cap, including omission of bottom nine.
    if frame.inning >= 9 and ((frame.half == 0 and frame.score[1] > frame.score[0])
                             or (frame.half == 1 and frame.score[0] != frame.score[1])):
        return replace(frame, finished=True)
    if frame.half == 1 and rules.max_innings is not None and frame.inning >= rules.max_innings:
        if rules.allow_draw:
            return replace(frame, finished=True)
        raise UnsupportedRule('inning_limit_without_draw: no fabricated winner')
    upcoming = frame.inning + int(frame.half == 1)
    use_runner = rules.automatic_runner_start is not None and upcoming >= rules.automatic_runner_start
    return legacy.advance_half(frame, automatic_runner=use_runner,
                               inning_cap=rules.max_innings or frame.inning + 1)


def apply_play(frame, play):
    """Validate and apply one atomic event, with explicit scoring evidence."""
    frame.validate()
    p, c = play.plan, play.credit
    if c.hit_bases not in range(5) or type(c.at_bat) is not bool:
        raise ValueError('Malformed scoring credit')
    expected_hit = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}.get(p.outcome, 0)
    if c.hit_bases != expected_hit or (c.hit_bases and not c.at_bat):
        raise ValueError('Hit credit differs from PA outcome')
    if c.sacrifice_bunt != (p.outcome == 'sacrifice_bunt') or c.sacrifice_fly != (p.outcome == 'sacrifice_fly'):
        raise ValueError('Sacrifice credit differs from PA outcome')
    if c.sacrifice_fly and not any(m.destination == 'H' for m in p.moves):
        raise ValueError('Sacrifice fly must score a runner')
    if not p.completed_pa and (c.at_bat or c.hit_bases or c.rbi_ids):
        raise ValueError('Runner-only event cannot credit a PA, AB, hit or RBI')
    if p.completed_pa and p.outcome in ('walk', 'hit_by_pitch', 'interference', 'sacrifice_bunt', 'sacrifice_fly') and c.at_bat:
        raise ValueError('Excluded PA cannot count as AB')
    if p.completed_pa and p.outcome not in ('walk', 'hit_by_pitch', 'interference', 'sacrifice_bunt', 'sacrifice_fly') and not c.at_bat:
        raise ValueError('This completed PA must count as AB')
    if c.ground_double_play and c.rbi_ids:
        raise ValueError('No RBI on a ground force double play')
    if c.rbi_ids is not None and (len(set(c.rbi_ids)) != len(c.rbi_ids) or not set(c.rbi_ids) <= {m.player_id for m in p.moves if m.destination == 'H'}):
        raise ValueError('RBI credits must identify actual planned scorers')
    outs = sum(m.destination == 'OUT' for m in p.moves)
    ending_runs = frame.outs + outs == 3 and any(m.destination == 'H' for m in p.moves)
    if ending_runs:
        if play.third_out not in ('source_counted', 'tag_after_runs'):
            raise UnsupportedRule('third_out_timing_unknown: force/appeal cannot be guessed')
        if play.third_out == 'source_counted' and not (play.certified and p.source == 'empirical'):
            raise ValueError('Source-counted third-out runs require an empirical certificate')
    try:
        result = legacy.apply_plan(frame, p)
    except UnsupportedRule:
        # Broader paths require source evidence or explicit, sufficiently rich rules.
        if not play.certified and not (ending_runs and play.third_out == 'tag_after_runs'):
            raise
        batter_move = next((m for m in p.moves if m.origin == 0), None)
        if batter_move and batter_move.destination == 'OUT' and expected_hit and play.batter_reached < expected_hit:
            raise ValueError('Stretching-out route lacks evidence of credited base reached')
        # Reuse the legacy participant/origin/conservation validator. Result-specific
        # extensions are adjudicated here; no surrogate is ever emitted as a play.
        surrogate = replace(p, outcome='other_out' if outs else 'reached_on_error',
                            completed_pa=True if p.completed_pa else False,
                            moves=tuple(replace(m, destination='LOB') if ending_runs and m.destination == 'H' else m for m in p.moves))
        if not p.completed_pa:
            surrogate = replace(surrogate, outcome=p.outcome)
        legacy.validate_plan(frame, surrogate)
        if p.outcome in ('sacrifice_bunt', 'sacrifice_fly') and (frame.outs >= 2 or frame.base_mask == 0):
            raise ValueError('Invalid sacrifice context')
        if p.outcome == 'home_run' and (outs or any(m.destination != 'H' for m in p.moves)):
            raise ValueError('Home run cannot retire a runner')
        result = _extended_apply(frame, p)
    # Walkoff timing of an out and a winning run is not established by a generic
    # route from another game. Reject rather than credit an out after game end.
    caught_fly = (p.outcome == 'sacrifice_fly' and outs == 1
                  and any(m.player_id == frame.batter and m.destination == 'OUT' for m in p.moves)
                  and (p.source in ('assumption', 'explicit_event') and not play.certified
                       or re.fullmatch(r'[1-9](?:/[^.]*)?', play.event_text.split('.')[0]) is not None))
    if result.after.finished and outs and not caught_fly and not (play.certified and play.third_out == 'actual_walkoff'):
        raise UnsupportedRule('walkoff_out_timing_unknown')
    if play.responsibility_transfer:
        runner = next((r for r in frame.bases if r and r.player_id == play.responsibility_transfer), None)
        if runner is None or not any(m.player_id == runner.player_id and m.destination == 'OUT' for m in p.moves):
            raise ValueError('Responsibility transfer requires the retired inherited runner')
        bases = tuple(replace(r, responsible_pitcher=runner.responsible_pitcher) if r and r.player_id == frame.batter else r for r in result.after.bases)
        result = replace(result, after=replace(result.after, bases=bases).validate())
    actual_ids = {r.player_id for r in result.scored}
    c = replace(c, rbi_ids=None if c.rbi_ids is None else tuple(pid for pid in c.rbi_ids if pid in actual_ids))
    # OBR 9.06(f): the winning run limits a non-HR game-ending hit's value.
    if result.after.finished and 0 < c.hit_bases < 4 and result.scored:
        winner = result.scored[-1].player_id
        origin = next(m.origin for m in p.moves if m.player_id == winner)
        credited = min(c.hit_bases, 4 - origin)
        if credited != c.hit_bases:
            bases = list(result.after.bases)
            index = next((i for i, r in enumerate(bases) if r and r.player_id == frame.batter), None)
            if index is None or bases[credited - 1] is not None:
                raise UnsupportedRule('walkoff_hit_credit_requires_touch_order')
            token = bases[index]; bases[index] = None; bases[credited - 1] = token
            result = replace(result, after=replace(result.after, bases=tuple(bases)).validate())
            c = replace(c, hit_bases=credited)
    responsibility_complete = play.responsibility_complete or all(r.responsible_pitcher == frame.pitcher for r in frame.bases if r)
    return Applied(replace(result, rules_version=RULES_VERSION), c, responsibility_complete)


def _extended_apply(frame, p):
    """Apply an already validated certified path, retaining the legacy ID types."""
    participants = {r.player_id: r for r in frame.bases if r}
    if p.completed_pa:
        participants[frame.batter] = RunnerToken(frame.batter, frame.pitcher,
                                                earned_eligible=None if p.outcome == 'reached_on_error' else True)
    bases = [None] * 3; scored = []; halted = []; stranded = []; out_ids = []
    score = list(frame.score)
    for m in sorted(p.moves, key=lambda m: m.origin, reverse=True):
        if m.destination == 'H':
            if frame.half == 1 and frame.inning >= 9 and score[1] > score[0] and p.outcome != 'home_run':
                halted.append(m.player_id)
            else:
                scored.append(participants[m.player_id]); score[frame.half] += 1
        elif m.destination == 'OUT':
            out_ids.append(m.player_id)
        elif m.destination == 'LOB':
            stranded.append(m.player_id)
        else:
            bases[int(m.destination) - 1] = participants[m.player_id]
    outs = frame.outs + len(out_ids)
    if outs == 3:
        stranded.extend(r.player_id for r in bases if r); bases = [None] * 3
    orders = list(frame.orders)
    if p.completed_pa:
        orders[frame.half] = (orders[frame.half] + 1) % 9
    after = replace(frame, bases=tuple(bases), outs=outs, orders=tuple(orders), score=tuple(score),
                    balls=0 if p.completed_pa else frame.balls, strikes=0 if p.completed_pa else frame.strikes,
                    finished=frame.half == 1 and frame.inning >= 9 and score[1] > score[0]).validate()
    final_ids = [r.player_id for r in bases if r] + [r.player_id for r in scored] + out_ids + stranded + halted
    if len(final_ids) != len(set(final_ids)) or set(final_ids) != set(participants):
        raise ValueError('Extended path violates identity conservation')
    return Transition(after, p, tuple(scored), tuple(out_ids), tuple(stranded), tuple(halted), p.completed_pa,
                      rules_version=RULES_VERSION)
