"""Pure bounded exponential odds tilts over existing executable PA support."""
from dataclasses import asdict,dataclass
import hashlib,math
from types import MappingProxyType
from datetime import date

from ..calibrated.rules import canonical
from ..completion.model import Draw
from .domain import can_play,availability,projected,BAT_SKILLS,PITCH_SKILLS

ADAPTER_VERSION='career-odds-adapter-1'

@dataclass(frozen=True)
class Snapshot:
    player_id:str
    team_id:str
    role:str
    as_of:str
    effective:tuple
    availability:str
    state_version:str
    fatigue:float=0.
    current_internal:tuple=()
    def __post_init__(self):
        date.fromisoformat(self.as_of)
        if not math.isfinite(self.fatigue) or not 0<=self.fatigue<=1:raise ValueError('Invalid snapshot fatigue')
        allowed=BAT_SKILLS if self.role=='batter' else PITCH_SKILLS if self.role=='pitcher' else ()
        if any(k not in allowed or not math.isfinite(v) or not -3<=v<=3 for k,v in self.current_internal):raise ValueError('Invalid frozen current ability')
        if not allowed or len(dict(self.effective))!=len(self.effective) or not set(dict(self.effective))<=set(allowed):raise ValueError('Invalid snapshot skills/role')
        if any(not math.isfinite(v) or not -4<=v<=3 for k,v in self.effective):raise ValueError('Invalid effective ability')
    def values(self):return dict(self.effective)


def snapshot(profile,state,on):
    if state.as_of>on:raise ValueError('Future player state cannot be a pregame input')
    state=projected(state,on)
    penalty=state.fatigue*.55+(.20 if availability(state)=='return_ready' else 0)
    adjusted={k:v-penalty for k,v in state.abilities.items()}
    return Snapshot(profile.player_id,state.team_id,profile.role,on,tuple(sorted(adjusted.items())),availability(state),state.state_version,state.fatigue,tuple(sorted(state.abilities.items())))


class AbilityModel:
    def __init__(self,base,snapshots,*,enabled=True):
        if type(enabled) is not bool:raise ValueError('Adapter enabled flag must be boolean')
        self.base=base;self.snapshots=MappingProxyType({s.player_id:s for s in snapshots});self.enabled=enabled
        if len(self.snapshots)!=len(snapshots):raise ValueError('Duplicate actor snapshot')
        self.snapshot_sha=hashlib.sha256(canonical([asdict(s) for s in sorted(snapshots,key=lambda s:s.player_id)]).encode()).hexdigest()
        self.version=(ADAPTER_VERSION+':'+base.version+':'+self.snapshot_sha) if enabled else base.version

    def validate_game_date(self,on):
        if self.enabled and any(s.as_of!=on for s in self.snapshots.values()):raise ValueError('Pregame snapshots must match the game date')

    def _actors(self,frame):
        result=[]
        for pid,role in ((frame.batter,'batter'),(frame.pitcher,'pitcher')):
            s=self.snapshots.get(pid)
            if s is None:
                result.append({});continue  # explicit league-average fallback
            if s.role!=role or s.availability not in ('available','restricted','return_ready'):
                raise ValueError('Unavailable/wrong-role player cannot participate')
            result.append(s.values())
        return result

    def predict_pa(self,frame,**actors):
        p=self.base.predict_pa(frame,**actors)
        if not self.enabled:return p
        b,t=self._actors(frame);get=lambda v,k:v.get(k,0.)
        hit=get(b,'contact');power=get(b,'power');supp=get(t,'hit_suppression')
        offsets={'single':.24*hit-.22*supp,'double':.16*hit+.20*power-.15*supp,
            'triple':.15*hit+.15*power+.10*get(b,'speed')-.16*supp,
            'home_run':.38*power-.34*get(t,'hr_suppression'),
            'walk':.35*get(b,'discipline')-.35*get(t,'control'),
            'strikeout':-.28*get(b,'k_avoid')-.12*hit+.38*get(t,'strikeouts')}
        if not any(offsets.values()):return p
        weighted={k:v*math.exp(max(-1.25,min(1.25,offsets.get(k,0.)))) for k,v in p.items()}
        total=sum(weighted.values())
        return {k:v/total for k,v in weighted.items()}

    def predict_step(self,frame,**actors):
        original=self.base.predict_step(frame,**actors)
        if not self.enabled:return original
        p=self.predict_pa(frame,**actors);unadjusted=self.base.predict_pa(frame,**actors)
        if p==unadjusted:return original
        q=original['runner_only_end']
        return {**{k:(1-q)*v for k,v in p.items()},'runner_only_end':q}

    def sample(self,frame,rng,*,allow_assumptions=False,**actors):
        if not self.enabled:return self.base.sample(frame,rng,allow_assumptions=allow_assumptions,**actors)
        probabilities=self.predict_step(frame,**actors)
        outcome=rng.choices(list(probabilities),weights=list(probabilities.values()),k=1)[0]
        try:return self.base.resolve_outcome(frame,outcome,rng,allow_assumptions=allow_assumptions,probability=probabilities[outcome])
        except ValueError as exc:
            exc.outcome=outcome;exc.context={**getattr(exc,'context',{}),'adapter_version':self.version};raise
