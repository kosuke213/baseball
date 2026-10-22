"""Timeline adjudication: observations, rules and generated order stay separate."""
from dataclasses import asdict, dataclass, fields, replace

from ..calibrated.rules import Frame, Move, Plan, RunnerToken, Transition, UnsupportedRule
from ..fullgame.rules import (Credit, GameRules, Play as OriginalPlay, Applied as OriginalApplied,
    next_half, play_from_dict as original_decode, apply_play as template_apply)
from ..completion.rules import apply_play as strict_apply
from .timeline import Timeline, constraints

RULES_VERSION='stability-rules-1'

@dataclass(frozen=True)
class Play(OriginalPlay):
    timeline: Timeline | None = None

@dataclass(frozen=True)
class Applied(OriginalApplied):
    timing_source: str = 'observed_or_rule'
    cancelled_out_ids: tuple[str,...] = ()
    executed_events: tuple[str,...] = ()
    actual_result: str = ''


def play_dict(play):return asdict(play)


def play_from_dict(d):
    d=dict(d);timeline=d.pop('timeline',None);p=original_decode(d)
    return Play(**{f.name:getattr(p,f.name) for f in fields(OriginalPlay)},
                timeline=Timeline.from_dict(timeline) if timeline else None)


def realize(frame,play,timeline):
    return Play(**{f.name:getattr(play,f.name) for f in fields(OriginalPlay)},timeline=timeline)


def apply_play(frame,play):
    timeline=getattr(play,'timeline',None)
    if timeline is None:
        a=strict_apply(frame,play)
        return Applied(replace(a.transition,rules_version=RULES_VERSION),a.credit,a.responsibility_complete)
    timeline.validate()
    expected_events,expected_edges=constraints(frame,play)
    if timeline.events!=expected_events or timeline.edges!=expected_edges:
        raise ValueError('Timeline milestones/evidence differ from the selected template')
    # This keeps source endpoint/credit validation, including conservation,
    # separate from the generated game-ending adjudication.
    regular=template_apply(replace(frame,inning=1),play)
    t=regular.transition
    ruling=adjudicate_events(frame,timeline,home_run=play.plan.outcome=='home_run')
    tokens={r.player_id:r for r in frame.bases if r}
    if play.plan.completed_pa:
        tokens[frame.batter]=RunnerToken(frame.batter,frame.pitcher,earned_eligible=None if play.plan.outcome=='reached_on_error' else True)
    score=ruling['score'];scored=[tokens[p] for p in ruling['scored_ids']]
    out_ids=ruling['out_ids'];executed=ruling['executed'];finished=ruling['finished']
    if play.credit.hit_bases and f'touch:{min(play.credit.hit_bases,3)}:'+frame.batter not in executed:
        raise UnsupportedRule('credited_hit_base_not_completed_before_play_end')
    generated_plan=replace(play.plan,source='assumption',source_ref=play.plan.source_ref+':'+timeline.policy)
    credit=play.credit
    if not finished:
        # Raw endpoints remain the ordinary-game result. No model may silently
        # contradict a counted third-out run or invent an extra run/out.
        if tuple(score)!=t.after.score or set(out_ids)!=set(t.out_ids):
            raise UnsupportedRule('generated_timeline_disagrees_with_source_endpoint')
        after=replace(t.after,inning=frame.inning)
        transition=replace(t,after=after,plan=generated_plan,rules_version=RULES_VERSION)
    else:
        # There are no active bases once the game ends. Preserve every unscored,
        # unretired participant as halted; do not invent terminal LOB/base stats.
        orders=list(frame.orders)
        if play.plan.completed_pa:orders[frame.half]=(orders[frame.half]+1)%9
        halted=tuple(sorted(set(tokens)-set(out_ids)-{r.player_id for r in scored}))
        after=replace(frame,bases=(None,None,None),score=tuple(score),outs=frame.outs+len(out_ids),
            orders=tuple(orders),balls=0 if play.plan.completed_pa else frame.balls,
            strikes=0 if play.plan.completed_pa else frame.strikes,finished=True).validate()
        transition=Transition(after,generated_plan,tuple(scored),tuple(out_ids),(),halted,play.plan.completed_pa,rules_version=RULES_VERSION)
        if 0<credit.hit_bases<4:
            origin=next(m.origin for m in play.plan.moves if m.player_id==scored[-1].player_id)
            credit=replace(credit,hit_bases=min(credit.hit_bases,4-origin))
        # A planned force GDP whose second out is cancelled is not an actual GDP.
        if credit.ground_double_play and len(out_ids)<2:
            credit=replace(credit,ground_double_play=False,rbi_ids=None if 'E' in play.event_text else tuple(r.player_id for r in scored))
        else:credit=replace(credit,rbi_ids=None if credit.rbi_ids is None else tuple(p for p in credit.rbi_ids if p in {r.player_id for r in scored}))
    cancelled=tuple(p for p in t.out_ids if p not in out_ids)
    ids=[r.player_id for r in transition.after.bases if r]+[r.player_id for r in transition.scored]+list(transition.out_ids)+list(transition.stranded_ids)+list(transition.halted_ids)
    if len(ids)!=len(set(ids)) or set(ids)!=set(tokens):raise ValueError('Timeline violates participant conservation')
    actual='walkoff_contact_without_out' if finished and not out_ids and play.plan.outcome=='other_out' else play.plan.outcome
    return Applied(transition,credit,regular.responsibility_complete,'generated_assumption',cancelled,tuple(executed),actual)


def adjudicate_events(frame,timeline,*,home_run=False):
    """Pure OBR 5.08 ruling over a supplied (generated or explicit) chronology.

    Score milestones are attempts, not pre-awarded runs. This API can invalidate
    an earlier home arrival on a force/batter-before-first third out, and treats
    preceding and trailing runner appeals differently. Fourth outs are explicit
    unsupported inputs. It does not invent a missing chronological order.
    """
    timeline.validate();frame.validate()
    lookup={e.event_id:e for e in timeline.events};ordered=[lookup[i] for i in timeline.order]
    known={r.player_id:i for i,r in enumerate(frame.bases,1) if r};known[frame.batter]=0
    if any(e.player_id not in known or e.origin!=known[e.player_id] for e in ordered):
        raise ValueError('Milestone participant/origin differs from the frame')
    outs=[e for e in ordered if e.kind=='out']
    if frame.outs+len(outs)>3:raise UnsupportedRule('fourth_out_appeal_not_implemented')
    third=outs[-1] if frame.outs+len(outs)==3 else None
    void_all=third is not None and third.out_kind in ('force','batter_before_first')
    if any(e.kind not in ('out','score','batter_touch','pa_decision') for e in ordered):raise ValueError('Unknown milestone type')
    if any(e.out_kind not in ('force','batter_before_first','tag','catch','appeal') for e in outs):raise UnsupportedRule('unknown_out_type')
    # Ordinary caught fly: a legal scoring advance follows the catch/tag-up.
    for catch in (e for e in outs if e.out_kind=='catch'):
        if any(timeline.order.index(h.event_id)<timeline.order.index(catch.event_id) for h in ordered if h.kind=='score'):
            raise ValueError('Caught-fly scoring cannot precede the catch')
    score=list(frame.score);scored=[];out_ids=[];executed=[];finished=False
    for event in ordered:
        executed.append(event.event_id)
        if event.kind=='out':
            out_ids.append(event.player_id)
            if frame.outs+len(out_ids)==3:break
        elif event.kind=='score':
            invalid=void_all or (third is not None and third.out_kind=='appeal' and event.origin<=third.origin)
            if invalid:continue
            scored.append(event.player_id);score[frame.half]+=1
            if frame.half==1 and frame.inning>=9 and score[1]>score[0] and not home_run:
                finished=True;break
    if home_run and frame.half==1 and frame.inning>=9 and score[1]>score[0]:finished=True
    return {'score':score,'scored_ids':scored,'out_ids':out_ids,'executed':executed,'finished':finished,
            'third_out_disqualifies_all_runs':void_all}
