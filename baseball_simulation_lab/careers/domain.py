"""Private domain state. Public views must use public.py, never dataclass dumping."""
from dataclasses import asdict,dataclass,replace
from datetime import date
import math

PROFILE_VERSION='fictional-profiles-1'
STATE_VERSION='career-state-1'
BAT_SKILLS=('contact','power','discipline','k_avoid','speed','fielding','throwing','endurance','recovery','durability')
PITCH_SKILLS=('strikeouts','control','hr_suppression','hit_suppression','starter_aptitude','relief_aptitude','stamina','recovery','durability')


def age_on(born,on):
    b=date.fromisoformat(born);d=date.fromisoformat(on)
    if d<b:raise ValueError('Date precedes birth')
    return d.year-b.year-int((d.month,d.day)<(b.month,b.day))


def clamp(x,lo=-3.,hi=3.):return max(lo,min(hi,x))

def display(x):return round(clamp(50+15*x,0,100))

@dataclass(frozen=True)
class Profile:
    player_id:str
    family_name:str
    given_name:str
    birth_date:str
    entry_date:str
    entry_year:int
    entry_age:int
    throws:str
    bats:str
    position:str
    role:str
    nationality:str='JPN'
    profile_version:str=PROFILE_VERSION
    @property
    def name(self):return self.family_name+' '+self.given_name
    def validate(self):
        if not self.player_id or self.role not in ('batter','pitcher'):raise ValueError('Invalid player identity/role')
        if self.throws not in ('L','R') or self.bats not in ('L','R','S'):raise ValueError('Invalid handedness')
        if self.entry_age!=age_on(self.birth_date,self.entry_date) or self.entry_age<16 or date.fromisoformat(self.entry_date).year!=self.entry_year:
            raise ValueError('Inconsistent entry date/age')
        return self

@dataclass(frozen=True)
class Talent:
    growth_rate:float
    maturation_offset:float
    decline_resistance:float
    volatility:float
    stagnation_chance:float
    traits:dict
    def validate(self,profile):
        expected=BAT_SKILLS if profile.role=='batter' else PITCH_SKILLS
        if set(self.traits)!=set(expected) or any(not math.isfinite(v) or v<=0 for v in self.traits.values()):raise ValueError('Invalid latent trait dimensions')
        if any(not math.isfinite(v) for v in (self.growth_rate,self.maturation_offset,self.decline_resistance,self.volatility,self.stagnation_chance)):
            raise ValueError('Non-finite private development parameters')
        if self.growth_rate<=0 or self.volatility<=0 or not 0<=self.decline_resistance<=1 or not 0<=self.stagnation_chance<=1:
            raise ValueError('Invalid private development parameters')
        return self

@dataclass(frozen=True)
class Injury:
    episode_id:str
    severity:int
    phase:str
    days_remaining:int
    started_on:str
    origin:str='generated_health_assumption'

@dataclass(frozen=True)
class State:
    player_id:str
    team_id:str
    as_of:str
    abilities:dict
    fatigue:float=0.
    recovery_rate:float=.25
    injury:Injury|None=None
    injury_history:int=0
    background_injuries:int=0
    career_status:str='active'
    experience:float=0.
    last_start:str|None=None
    last_played:str|None=None
    scouting:dict|None=None
    state_version:str=STATE_VERSION
    def validate(self,profile):
        expected=BAT_SKILLS if profile.role=='batter' else PITCH_SKILLS
        if self.player_id!=profile.player_id or not self.team_id or set(self.abilities)!=set(expected):raise ValueError('State identity/skills mismatch')
        if any(not math.isfinite(v) or not -3<=v<=3 for v in self.abilities.values()):raise ValueError('Ability outside internal bounds')
        if not math.isfinite(self.fatigue) or not 0<=self.fatigue<=1 or not 0<self.recovery_rate<=2:raise ValueError('Invalid fatigue/recovery')
        if self.career_status not in ('active','retired'):raise ValueError('Unknown career status')
        if self.injury and (self.injury.severity not in (1,2,3) or self.injury.phase not in ('unavailable','rehabilitating','return_ready') or self.injury.days_remaining<1):
            raise ValueError('Invalid injury phase')
        date.fromisoformat(self.as_of)
        return self


def state_dict(state):return asdict(state)

def state_from_dict(d):
    d=dict(d)
    if d.get('injury'):d['injury']=Injury(**d['injury'])
    return State(**d)


def projected(state,on,*,allow_boundary=False):
    days=(date.fromisoformat(on)-date.fromisoformat(state.as_of)).days
    if days<0:raise ValueError('Cannot project a state backward')
    fatigue=state.fatigue*math.exp(-state.recovery_rate*days)
    if fatigue<1e-5:fatigue=0.
    injury=state.injury
    if injury:
        left=injury.days_remaining-days
        if left<=0 and not allow_boundary:raise ValueError('A committed injury transition is required for this date')
        injury=replace(injury,days_remaining=max(0,left))
    return replace(state,as_of=on,fatigue=fatigue,injury=injury)


def availability(state):
    if state.career_status!='active':return 'retired'
    if state.injury:return state.injury.phase
    if state.fatigue>=.90:return 'unavailable'
    if state.fatigue>=.65:return 'restricted'
    return 'available'


def can_play(state):return availability(state) in ('available','restricted','return_ready')
