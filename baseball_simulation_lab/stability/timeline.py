"""Partially ordered milestones. Listed events are NOT observed timestamps."""
from dataclasses import asdict, dataclass
import re

from ..calibrated.rules import UnsupportedRule

POLICY = 'legal-linear-extension-1'

@dataclass(frozen=True)
class Event:
    event_id: str
    kind: str
    player_id: str
    origin: int
    destination: str
    out_kind: str = ''
    provenance: str = 'source_endpoint'

@dataclass(frozen=True)
class Edge:
    before: str
    after: str
    provenance: str
    reason: str

@dataclass(frozen=True)
class Timeline:
    events: tuple[Event, ...]
    edges: tuple[Edge, ...]
    order: tuple[str, ...]
    policy: str = POLICY
    provenance: str = 'generated_assumption'

    def validate(self):
        ids=[e.event_id for e in self.events]
        if len(ids)!=len(set(ids)) or len(self.order)!=len(ids) or set(self.order)!=set(ids):
            raise ValueError('Timeline must execute every distinct milestone exactly once')
        positions={v:i for i,v in enumerate(self.order)}
        for e in self.edges:
            if e.before not in positions or e.after not in positions or positions[e.before]>=positions[e.after]:
                raise ValueError('Timeline violates a partial-order constraint')
        if self.policy!=POLICY or self.provenance not in ('generated_assumption','explicit_event'):
            raise ValueError('Unknown timeline policy/provenance')
        return self

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls,d):
        return cls(tuple(Event(**e) for e in d['events']),tuple(Edge(**e) for e in d['edges']),
                   tuple(d['order']),d['policy'],d['provenance']).validate()


def out_kind(play, move):
    text=play.event_text; role='B' if move.origin==0 else str(move.origin)
    explicit=re.search(r'(?:\.|;)'+role+r'X([123H])\(([^)]*)\)',text)
    if explicit:
        if '/AP' in explicit[2]:return 'appeal'
        if '/FO' in explicit[2]:return 'force'
        return 'tag'
    if move.origin==0:
        if play.credit.hit_bases or play.batter_reached:return 'tag'
        primary=text.split('.')[0]
        if play.credit.sacrifice_fly or re.fullmatch(r'[1-9](?:/(?:F|L|P)[^.]*)?',primary):return 'catch'
        return 'batter_before_first'
    if '/AP' in text:return 'appeal'
    if '/FO' in text or play.credit.ground_double_play:return 'force'
    return 'tag'


def constraints(frame,play):
    """Return endpoints + only justified constraints, with provenance per edge.

    GDP force identity is a declared generated classification where the raw
    endpoint alone does not distinguish a force/tag. This never claims to
    reconstruct the chronology of the original game.
    """
    events=[];edges=[];p=play.plan
    def edge(a,b,why,source='rule'):edges.append(Edge(a,b,source,why))
    for m in p.moves:
        if m.destination=='OUT':
            kind=out_kind(play,m)
            prov='generated_assumption'
            if kind=='force' and '/FO' in play.event_text or kind=='appeal' and '/AP' in play.event_text:
                prov='source_description_and_rules'
            if kind=='catch' and (play.credit.sacrifice_fly or any('/'+t in play.event_text for t in ('F','L','P'))):
                prov='source_description_and_rules'
            if kind=='batter_before_first' and '/G' in play.event_text:
                prov='source_description_and_rules'
            events.append(Event('out:'+m.player_id,'out',m.player_id,m.origin,'OUT',kind,prov))
        elif m.destination=='H':events.append(Event('home:'+m.player_id,'score',m.player_id,m.origin,'H'))
    bm=next((m for m in p.moves if m.origin==0),None)
    reached=play.credit.hit_bases or play.batter_reached
    if bm and (bm.destination in ('1','2','3','H') or reached):
        maximum=4 if bm.destination=='H' else max(reached,int(bm.destination) if bm.destination in ('1','2','3') else 1)
        for base in range(1,min(maximum,3)+1):
            name=f'touch:{base}:'+frame.batter
            events.append(Event(name,'batter_touch',frame.batter,0,str(base),provenance='source_credit_or_endpoint'))
            if base>1:edge(f'touch:{base-1}:'+frame.batter,name,'successive batter base touches')
        endpoint=('out:' if bm.destination=='OUT' else 'home:' if bm.destination=='H' else None)
        if endpoint:edge(f'touch:{min(maximum,3)}:'+frame.batter,endpoint+frame.batter,'reach credited base before stretching out/scoring')
    # Contact-hit templates certify a base credit but do not give its time.
    # The generator chooses a legal convention: run out the credited hit before
    # the home arrivals. It is NOT an observed or mandatory physical ordering.
    if bm and reached and (play.credit.hit_bases or p.outcome in ('walk','hit_by_pitch','interference')):
        milestone=f'touch:{min(maximum,3)}:'+frame.batter
        for h in [e for e in events if e.kind=='score' and e.player_id!=frame.batter]:
            edge(milestone,h.event_id,'generated credited-base completion convention','generated_assumption')
    scorers=sorted([e for e in events if e.kind=='score'],key=lambda e:-e.origin)
    for a,b in zip(scorers,scorers[1:]):edge(a.event_id,b.event_id,'no passing at home in this ordinary generated play')
    outs=[e for e in events if e.kind=='out']
    for o in outs:
        if o.out_kind=='catch':
            for h in scorers:edge(o.event_id,h.event_id,'catch before tag-up scoring (ordinary sacrifice fly)')
        # A lead runner must reach home before a trailing runner is tagged there.
        role='B' if o.origin==0 else str(o.origin)
        if re.search(r'(?:\.|;)'+role+r'XH\([1-9]+\)(?:;|$)',play.event_text):
            for h in scorers:
                if h.origin>o.origin:edge(h.event_id,o.event_id,'lead home arrival before trailing ordinary home tag')
    # A counted run in a reverse-force GDP proves that the final retirement
    # was not a force/batter-before-first third out. GDP alone did not identify
    # a force: revise only the GENERATED classification, never explicit /FO.
    if frame.outs+len(outs)==3 and scorers and not any(o.out_kind in ('tag','catch') for o in outs):
        candidates=[o for o in outs if o.origin and o.provenance=='generated_assumption']
        if candidates and play.third_out=='source_counted' and play.certified:
            old=candidates[-1]
            new=Event(old.event_id,old.kind,old.player_id,old.origin,old.destination,'tag','rule_from_source_adjudication')
            events=[new if e==old else e for e in events];outs=[new if e==old else e for e in outs]
    # Keep the credited sacrifice/strikeout coherent when this play ends a game.
    # The sacrifice timing convention is generative; an ordinary strikeout on a
    # pitch precedes consequential runner advances on that pitch by rule.
    for o in outs:
        if o.player_id==frame.batter and (play.credit.sacrifice_bunt or play.plan.outcome=='strikeout' and not play.plan.dropped_third_strike):
            for h in scorers:edge(o.event_id,h.event_id,'credited PA retirement before consequential scoring',
                'generated_assumption' if play.credit.sacrifice_bunt else 'rule')
    if play.credit.ground_double_play and frame.outs+len(outs)<3:
        for o in outs:
            for h in scorers:edge(o.event_id,h.event_id,'complete credited GDP before scoring','generated_assumption')
    # Source-counted runs exclude a disqualifying third out. It does not identify
    # all timestamps. Choose one legal third out as a GENERATIVE constraint.
    if frame.outs+len(outs)==3 and scorers:
        allowed=[o for o in outs if o.out_kind in ('tag','catch')]
        if not allowed:raise UnsupportedRule('source_runs_conflict_with_generated_third_out_type')
        last=next((o for o in reversed(allowed) if o.out_kind=='tag'),allowed[-1])
        for o in outs:
            if o!=last:edge(o.event_id,last.event_id,'chosen legal final out conditional on recorded runs','generated_assumption')
        for h in scorers:edge(h.event_id,last.event_id,'recorded runs require scoring before the chosen third out','rule_from_source_adjudication')
    # Force DP generated semantics require retiring the forced runner before a
    # batter retirement removes the force. This is labelled as an assumption.
    bfirst=next((o for o in outs if o.player_id==frame.batter and o.out_kind=='batter_before_first'),None)
    if bfirst:
        for o in outs:
            if o.out_kind=='force':edge(o.event_id,bfirst.event_id,'retain force before batter retired','generated_assumption')
    if play.credit.hit_bases:
        milestone=f'touch:{min(play.credit.hit_bases,3)}:'+frame.batter
        for o in outs:edge(milestone,o.event_id,'complete credited hit before any terminating out','generated_assumption')
    if p.completed_pa:
        decision=Event('pa:'+frame.batter,'pa_decision',frame.batter,0,p.outcome,provenance='source_pa_class_or_declared_outcome')
        for e in events:edge(decision.event_id,e.event_id,'pitch/contact decision before consequential endpoints','rule')
        events.insert(0,decision)
    return tuple(events),tuple(dict.fromkeys(edges))


def generate(frame,play,rng):
    events,edges=constraints(frame,play)
    remaining={e.event_id for e in events};done=set();order=[]
    while remaining:
        ready=sorted(i for i in remaining if all(e.before in done for e in edges if e.after==i))
        if not ready:raise UnsupportedRule('cyclic_timeline_constraints')
        # One draw among ready nodes, not uniform over every possible extension.
        chosen=ready[rng.randrange(len(ready))] if len(ready)>1 else ready[0]
        order.append(chosen);done.add(chosen);remaining.remove(chosen)
    return Timeline(events,edges,tuple(order)).validate()
