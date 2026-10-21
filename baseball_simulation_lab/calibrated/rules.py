"""ID-preserving, deliberately bounded play rules; no probability or DB access."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

RULES_VERSION = 'identity-rules-1'
PA_OUTCOMES = ('single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch',
               'strikeout', 'sacrifice_bunt', 'sacrifice_fly', 'reached_on_error',
               'fielders_choice', 'interference', 'other_out', 'double_play')
RUNNER_EVENTS = ('stolen_base', 'caught_stealing', 'pickoff', 'pickoff_caught_stealing',
                 'wild_pitch', 'passed_ball', 'balk', 'defensive_indifference', 'other_advance', 'foul_error')


class UnsupportedRule(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class RunnerToken:
    player_id: str
    responsible_pitcher: str
    automatic: bool = False
    earned_eligible: bool | None = True


@dataclass(frozen=True)
class Frame:
    lineups: tuple[tuple[str, ...], tuple[str, ...]]
    pitchers: tuple[str, str]
    orders: tuple[int, int] = (0, 0)
    bases: tuple[RunnerToken | None, ...] = (None, None, None)
    outs: int = 0
    inning: int = 1
    half: int = 0
    score: tuple[int, int] = (0, 0)
    balls: int = 0
    strikes: int = 0
    finished: bool = False
    retired_ids: tuple[str, ...] = ()
    pitcher_history: tuple[str, ...] = ()

    @property
    def batter(self):
        return self.lineups[self.half][self.orders[self.half]]

    @property
    def pitcher(self):
        return self.pitchers[1 - self.half]

    @property
    def base_mask(self):
        return sum(1 << i for i, r in enumerate(self.bases) if r is not None)

    def validate(self):
        if len(self.lineups) != 2 or any(len(v) != 9 or len(set(v)) != 9 for v in self.lineups):
            raise ValueError('Two lineups with nine unique IDs are required')
        if set(self.lineups[0]) & set(self.lineups[1]):
            raise ValueError('A player belongs to both teams')
        if (len(self.pitchers) != 2 or self.pitchers[0] == self.pitchers[1]
                or self.pitchers[0] in self.lineups[1] or self.pitchers[1] in self.lineups[0]):
            raise ValueError('Pitcher identity conflicts with team membership')
        ids = [r.player_id for r in self.bases if r]
        if len(self.bases) != 3 or len(ids) != len(set(ids)):
            raise ValueError('Runner IDs occupy duplicate bases')
        if any(not isinstance(v, str) or not v for v in (*self.lineups[0], *self.lineups[1], *self.pitchers, *ids)):
            raise ValueError('Nonempty player IDs are required')
        if any(i not in range(9) or type(i) is not int for i in self.orders):
            raise ValueError('Invalid batting order')
        if self.half not in (0, 1) or type(self.inning) is not int or self.inning < 1 or type(self.outs) is not int or not 0 <= self.outs <= 3:
            raise ValueError('Invalid inning, half or outs')
        if len(self.score) != 2 or any(type(v) is not int or v < 0 for v in self.score):
            raise ValueError('Invalid scoreboard')
        if not 0 <= self.balls <= 3 or not 0 <= self.strikes <= 2:
            raise ValueError('Invalid count')
        if self.outs == 3 and ids:
            raise ValueError('Bases must be closed explicitly at three outs')
        if self.batter in ids and not self.finished:
            raise ValueError('Current batter is already a runner')
        if any(pid not in self.lineups[self.half] for pid in ids):
            raise ValueError('Runner is not in the current batting lineup')
        known_pitchers = {*self.pitchers, *self.pitcher_history}
        if any(not r.responsible_pitcher or r.responsible_pitcher not in known_pitchers for r in self.bases if r):
            raise ValueError('Unknown responsible pitcher')
        if set(self.retired_ids) & {*self.lineups[0], *self.lineups[1], *self.pitchers}:
            raise ValueError('A removed player has re-entered')
        return self


@dataclass(frozen=True)
class Move:
    player_id: str
    origin: int  # batter 0; existing bases 1..3
    destination: str  # '1','2','3','H','OUT','LOB'


@dataclass(frozen=True)
class Plan:
    outcome: str
    moves: tuple[Move, ...]
    completed_pa: bool
    source: str  # empirical / assumption / explicit_event
    source_ref: str
    dropped_third_strike: bool = False


@dataclass(frozen=True)
class Transition:
    after: Frame
    plan: Plan
    scored: tuple[RunnerToken, ...]
    out_ids: tuple[str, ...]
    stranded_ids: tuple[str, ...]
    halted_ids: tuple[str, ...]
    completed_pa: bool
    rules_version: str = RULES_VERSION
    official_scoring_complete: bool = False


def forced_destinations(frame):
    result = {frame.batter: '1'}
    forced = True
    for index, runner in enumerate(frame.bases, 1):
        if runner:
            result[runner.player_id] = ('H' if index == 3 else str(index + 1)) if forced else str(index)
        else:
            forced = False
    return result


def validate_plan(frame, plan):
    frame.validate()
    if frame.finished or frame.outs == 3:
        raise ValueError('No attack after game end or third out; advance the half explicitly')
    if plan.source not in ('empirical', 'assumption', 'explicit_event') or not plan.source_ref:
        raise ValueError('A plan must declare its provenance')
    if plan.completed_pa != (plan.outcome in PA_OUTCOMES):
        raise UnsupportedRule('Unrecognized PA result or runner event')
    if not plan.completed_pa and plan.outcome not in RUNNER_EVENTS:
        raise UnsupportedRule('Unsupported runner event')
    participants = {r.player_id: (i, r) for i, r in enumerate(frame.bases, 1) if r}
    if plan.completed_pa:
        participants[frame.batter] = (0, RunnerToken(frame.batter, frame.pitcher,
                                                   earned_eligible=None if plan.outcome == 'reached_on_error' else True))
    if len(plan.moves) != len(participants) or {m.player_id for m in plan.moves} != set(participants):
        raise ValueError('Every participant must have exactly one disposition')
    dest = {}
    for m in plan.moves:
        if m.origin != participants[m.player_id][0] or m.destination not in ('1', '2', '3', 'H', 'OUT', 'LOB'):
            raise ValueError('Movement origin or destination is invalid')
        if m.destination in ('1', '2', '3') and int(m.destination) < m.origin:
            raise UnsupportedRule('Backward advance is not implemented')
        dest[m.player_id] = m.destination
    occupied = [v for v in dest.values() if v in ('1', '2', '3')]
    if len(occupied) != len(set(occupied)):
        raise ValueError('Two players finish on the same base')
    outs = sum(v == 'OUT' for v in dest.values())
    if frame.outs + outs > 3:
        raise ValueError('Outs exceed three')
    ending = frame.outs + outs == 3
    if 'LOB' in dest.values() and not ending:
        raise ValueError('LOB disposition is only valid at third out')
    if ending and 'H' in dest.values():
        raise UnsupportedRule('Third-out run timing / appeal / force adjudication is not implemented')
    advancing = sorted((m for m in plan.moves if m.destination in ('1', '2', '3', 'H')), key=lambda m: m.origin, reverse=True)
    positions = [4 if m.destination == 'H' else int(m.destination) for m in advancing]
    if any(positions[i] < positions[i + 1] for i in range(len(positions) - 1)):
        raise ValueError('A following live runner passes a leading live runner')
    if plan.completed_pa:
        batter = dest[frame.batter]
        if plan.outcome == 'fielders_choice' and frame.base_mask == 0:
            raise ValueError('Fielders choice requires a preceding runner')
        if plan.outcome in ('walk', 'hit_by_pitch', 'interference') and dest != forced_destinations(frame):
            raise UnsupportedRule('Only the simple forced-base award is implemented for this result')
        hit = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}.get(plan.outcome)
        if hit:
            if batter == 'OUT':
                raise UnsupportedRule('Hit credited before batter stretching out requires a richer route')
            if batter in ('1', '2', '3') and int(batter) < hit:
                raise ValueError('Batter fails to reach the credited hit base')
            if plan.outcome == 'home_run' and (outs or any(v != 'H' for v in dest.values())):
                raise ValueError('A home run must score every current participant, without an out')
        if plan.outcome == 'strikeout':
            if plan.dropped_third_strike:
                if frame.bases[0] is not None and frame.outs < 2:
                    raise ValueError('Dropped third strike does not entitle batter to first')
                if batter not in ('1', '2', '3', 'H', 'LOB'):
                    raise ValueError('Dropped-third-strike safe route is inconsistent')
            elif batter != 'OUT':
                raise ValueError('Ordinary strikeout must retire the batter')
        if plan.outcome in ('sacrifice_bunt', 'sacrifice_fly'):
            if frame.outs >= 2 or not frame.base_mask or batter != 'OUT':
                raise UnsupportedRule('Only a caught/retired-batter sacrifice with fewer than two outs is supported')
            if plan.outcome == 'sacrifice_fly' and not any(v == 'H' for k, v in dest.items() if k != frame.batter):
                raise ValueError('Sacrifice fly must score a runner')
        if plan.outcome == 'other_out' and outs == 0:
            raise ValueError('Other-out result requires an out (not necessarily the batter)')
        if plan.outcome == 'double_play' and (frame.outs >= 2 or frame.bases[0] is None or outs != 2
                                             or dest[frame.batter] != 'OUT' or dest[frame.bases[0].player_id] != 'OUT'):
            raise ValueError('Ground double play requires batter and first-base runner retired')
        if plan.outcome in ('reached_on_error', 'fielders_choice') and batter == 'OUT':
            raise UnsupportedRule('Safe-batter result followed by a stretching out is not implemented')
    return participants, dest


def apply_plan(frame, plan):
    participants, destinations = validate_plan(frame, plan)
    out_ids = tuple(m.player_id for m in plan.moves if m.destination == 'OUT')
    runners = [None, None, None]
    scored, halted, stranded = [], [], []
    score = list(frame.score)
    walkoff = frame.half == 1 and frame.inning >= 9
    # Source fields identify scorers, but not times. Order follows the no-passing rule.
    for m in sorted(plan.moves, key=lambda m: m.origin, reverse=True):
        token = participants[m.player_id][1]
        if m.destination == 'H':
            if walkoff and score[1] > score[0] and plan.outcome != 'home_run':
                halted.append(token.player_id)
            else:
                scored.append(token); score[frame.half] += 1
        elif m.destination in ('1', '2', '3'):
            runners[int(m.destination) - 1] = token
        elif m.destination == 'LOB':
            stranded.append(m.player_id)
    outs = frame.outs + len(out_ids)
    if outs == 3:
        stranded.extend(r.player_id for r in runners if r)
        runners = [None, None, None]
    orders = list(frame.orders)
    if plan.completed_pa:
        orders[frame.half] = (orders[frame.half] + 1) % 9
    finished = walkoff and score[1] > score[0]
    after = replace(frame, bases=tuple(runners), outs=outs, score=tuple(score), orders=tuple(orders),
                    balls=0 if plan.completed_pa else frame.balls, strikes=0 if plan.completed_pa else frame.strikes,
                    finished=finished)
    after.validate()
    accounted = [r.player_id for r in after.bases if r] + [r.player_id for r in scored] + list(out_ids) + stranded + halted
    if len(accounted) != len(set(accounted)) or set(accounted) != set(participants):
        raise ValueError('Identity conservation failed')
    return Transition(after, plan, tuple(scored), out_ids, tuple(stranded), tuple(halted), plan.completed_pa)


def conservative_plan(frame, outcome):
    """Explicit assumptions, never labelled measured advancement."""
    frame.validate()
    if outcome not in PA_OUTCOMES:
        raise UnsupportedRule('No silent fallback for an unobserved runner-only/unknown result')
    moves = []
    if outcome in ('walk', 'hit_by_pitch', 'interference', 'reached_on_error'):
        destinations = forced_destinations(frame)
    else:
        distance = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}.get(outcome)
        destinations = {}
        for i, runner in enumerate(frame.bases, 1):
            if not runner:
                continue
            advance = distance or (1 if outcome == 'sacrifice_bunt' else 0)
            destinations[runner.player_id] = 'H' if i + advance >= 4 else str(i + advance)
        destinations[frame.batter] = ('H' if distance == 4 else str(distance)) if distance else 'OUT'
        if outcome == 'sacrifice_fly':
            if frame.bases[2] is None:
                raise UnsupportedRule('Conservative sac-fly fallback requires a runner on third')
            destinations[frame.bases[2].player_id] = 'H'
        if outcome in ('double_play', 'fielders_choice'):
            if frame.bases[0] is None or frame.outs >= 2:
                raise UnsupportedRule('Fallback choice/double play requires first occupied and <2 outs')
            destinations[frame.bases[0].player_id] = 'OUT'
            destinations[frame.batter] = 'OUT' if outcome == 'double_play' else '1'
    for i, token in enumerate(frame.bases, 1):
        if token:
            moves.append(Move(token.player_id, i, destinations[token.player_id]))
    moves.append(Move(frame.batter, 0, destinations[frame.batter]))
    plan = Plan(outcome, tuple(moves), True, 'assumption', 'conservative-fixed-advance-1')
    validate_plan(frame, plan)
    return plan


def runner_event(frame, outcome, origin, destination):
    if origin not in (1, 2, 3) or frame.bases[origin - 1] is None:
        raise ValueError('Runner-event origin is empty')
    if outcome == 'stolen_base' and destination != ('H' if origin == 3 else str(origin + 1)):
        raise ValueError('Single-steal API advances exactly one base')
    if outcome in ('caught_stealing', 'pickoff') and destination != 'OUT':
        raise ValueError('Caught stealing/pickoff must identify an out')
    moves = tuple(Move(r.player_id, i, destination if i == origin else str(i)) for i, r in enumerate(frame.bases, 1) if r)
    return apply_plan(frame, Plan(outcome, moves, False, 'explicit_event', 'caller-specified-runner-event-1'))


def advance_half(frame, *, automatic_runner=True, inning_cap=12):
    frame.validate()
    if frame.finished or frame.outs != 3:
        raise ValueError('Only a completed half can be advanced')
    if frame.inning >= 9:
        if frame.half == 0 and frame.score[1] > frame.score[0] or frame.half == 1 and frame.score[0] != frame.score[1]:
            return replace(frame, finished=True)
        if frame.half == 1 and frame.inning >= inning_cap:
            raise UnsupportedRule('Laboratory inning cap reached; do not fabricate an MLB tie')
    inning = frame.inning + int(frame.half == 1)
    half = 1 - frame.half
    bases = (None, None, None)
    if automatic_runner and inning >= 10:
        runner = frame.lineups[half][(frame.orders[half] - 1) % 9]
        if runner == frame.pitchers[half]:
            raise UnsupportedRule('Pitcher exception for automatic-runner eligibility requires explicit adjudication')
        bases = (None, RunnerToken(runner, frame.pitchers[1 - half], True, False), None)
    return replace(frame, inning=inning, half=half, outs=0, bases=bases, balls=0, strikes=0).validate()


def substitute(frame, side, slot, player_id, *, pinch_runner=False):
    frame.validate()
    if frame.finished or frame.outs == 3 or side not in (0, 1) or slot not in range(9):
        raise ValueError('Invalid substitution context')
    if frame.balls or frame.strikes:
        raise UnsupportedRule('Mid-count substitution and official inherited-count credit are not implemented')
    used = {*frame.lineups[0], *frame.lineups[1], *frame.pitchers, *frame.retired_ids, *frame.pitcher_history}
    if not player_id or player_id in used:
        raise ValueError('Substitute already used or missing')
    old = frame.lineups[side][slot]
    on_base = any(r and r.player_id == old for r in frame.bases)
    if on_base != pinch_runner or pinch_runner and side != frame.half:
        raise ValueError('A baserunner must be explicitly replaced as a pinch runner')
    lineups = [list(v) for v in frame.lineups]; lineups[side][slot] = player_id
    bases = tuple(replace(r, player_id=player_id) if r and r.player_id == old else r for r in frame.bases)
    return replace(frame, lineups=tuple(tuple(v) for v in lineups), bases=bases,
                   retired_ids=tuple(sorted({*frame.retired_ids, old}))).validate()


def change_pitcher(frame, player_id):
    frame.validate()
    if frame.finished or frame.outs == 3:
        raise ValueError('Cannot change pitcher after a closed half or game')
    if frame.balls or frame.strikes:
        raise UnsupportedRule('Mid-count pitcher credit is not implemented')
    used = {*frame.lineups[0], *frame.lineups[1], *frame.pitchers, *frame.retired_ids, *frame.pitcher_history}
    if not player_id or player_id in used:
        raise UnsupportedRule('Re-entry / two-way position changes need a richer roster contract')
    pitchers = list(frame.pitchers); old = frame.pitcher; pitchers[1 - frame.half] = player_id
    # Prior pitchers stay known for run responsibility, not as eligible players.
    return replace(frame, pitchers=tuple(pitchers), pitcher_history=tuple(sorted({*frame.pitcher_history, old}))).validate()


def count_event(frame, kind):
    frame.validate()
    if frame.finished or frame.outs == 3:
        raise ValueError('Cannot record a pitch in a closed attack')
    if kind == 'ball':
        return apply_plan(frame, conservative_plan(frame, 'walk')) if frame.balls == 3 else replace(frame, balls=frame.balls + 1)
    if kind in ('called_strike', 'swinging_strike'):
        return apply_plan(frame, conservative_plan(frame, 'strikeout')) if frame.strikes == 2 else replace(frame, strikes=frame.strikes + 1)
    if kind == 'foul':
        return replace(frame, strikes=min(frame.strikes + 1, 2))
    raise UnsupportedRule('Count API accepts observed ball/strike/foul; it does not predict pitches')


def frame_dict(frame):
    return asdict(frame)


def frame_from_dict(value):
    value = dict(value)
    for field in ('lineups',):
        value[field] = tuple(tuple(v) for v in value[field])
    for field in ('pitchers', 'orders', 'score', 'retired_ids', 'pitcher_history'):
        value[field] = tuple(value[field])
    value['bases'] = tuple(RunnerToken(**r) if r else None for r in value['bases'])
    return Frame(**value).validate()


def fingerprint(frame):
    return hashlib.sha256(canonical(frame_dict(frame)).encode()).hexdigest()


def plan_dict(plan):
    return asdict(plan)


def plan_from_dict(value):
    return Plan(**{**value, 'moves': tuple(Move(**m) for m in value['moves'])})
