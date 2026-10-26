"""Event-driven private player lifecycles; no future events precomputed."""
from dataclasses import asdict,replace
from datetime import date,timedelta
import hashlib,math,copy

from ..calibrated.rules import canonical
from .domain import Profile,Talent,State,Injury,age_on,clamp,projected,state_dict,state_from_dict,can_play
from .generation import scout
from .randomness import keyed,event_seed

CAREER_VERSION='stochastic-careers-1'
PEAKS={'contact':28,'power':29,'discipline':30,'k_avoid':27,'speed':25,'fielding':27,'throwing':28,'endurance':27,
       'recovery':26,'durability':27,'strikeouts':27,'control':30,'hr_suppression':29,'hit_suppression':28,
       'starter_aptitude':29,'relief_aptitude':28,'stamina':27}


def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()


class World:
    def __init__(self,world_id,on,root_seed,team_ids):
        date.fromisoformat(on)
        self.world_id=world_id;self.created_on=on;self.now=on;self.root_seed=root_seed;self.team_ids=tuple(team_ids)
        self.profiles={};self.talents={};self.states={};self.entry_abilities={};self.events=[];self.event_ids=set()
        self.header={'world_id':world_id,'created_on':on,'private_root_seed':root_seed,'team_ids':list(team_ids),'career_version':CAREER_VERSION}
        self.previous=digest(self.header);self.committed=0;self.applied_games=set();self.grown_years=set()

    def _emit(self,kind,pid,on,scope,after=None,details=None):
        eid=digest([self.world_id,kind,pid,scope])
        if eid in self.event_ids:raise ValueError('Career event already applied')
        before=self.states.get(pid) if pid else None
        if after:
            if after.as_of!=on:raise ValueError('State date differs from event')
            after.validate(self.profiles[pid])
        record={'sequence':len(self.events)+1,'event_id':eid,'event_date':on,'player_id':pid,'kind':kind,
                'scope':scope,'career_version':CAREER_VERSION,'before_sha256':digest(state_dict(before)) if before else None,
                'after':state_dict(after) if after else None,'details':details or {},'previous':self.previous}
        sha=digest(record);self.events.append({'event':record,'hash':sha});self.event_ids.add(eid);self.previous=sha
        if after:self.states[pid]=after

    def enrol(self,profile,talent,state):
        profile.validate();talent.validate(profile);state.validate(profile)
        if profile.player_id in self.profiles or state.team_id not in self.team_ids:raise ValueError('Duplicate player or unknown team')
        if state.as_of!=self.now or profile.entry_date>self.now:raise ValueError('Cannot enrol a future/past current state')
        talent=copy.deepcopy(talent);state=copy.deepcopy(state)
        self.profiles[profile.player_id]=profile;self.talents[profile.player_id]=talent
        if profile.entry_date==self.now:entry=dict(state.abilities)
        else:
            rng=keyed(self.root_seed,'background_entry',profile.player_id,profile.entry_year)
            entry={k:clamp(rng.gauss(-.4,.6)) for k in state.abilities}
        self.entry_abilities[profile.player_id]=entry
        self._emit('enrolment',profile.player_id,self.now,'initial',state,
            {'profile':asdict(profile),'private_talent':asdict(talent),'entry_abilities':entry,
             'entry_snapshot_origin':'generated_background' if profile.entry_date<self.now else 'simulated_entry',
             'prior_injuries_origin':'fictional_background'})

    def current(self,pid):return copy.deepcopy(projected(self.states[pid],self.now))

    def advance(self,on):
        target=date.fromisoformat(on)
        if target<date.fromisoformat(self.now):raise ValueError('World time cannot move backward')
        if on==self.now:return
        for pid in sorted(self.states):
            state=self.states[pid]
            while state.injury:
                boundary=date.fromisoformat(state.as_of)+timedelta(days=state.injury.days_remaining)
                if boundary>target:break
                stamp=boundary.isoformat();old=state.injury
                state=projected(state,stamp,allow_boundary=True)
                if old.phase=='unavailable':
                    state=replace(state,injury=replace(old,phase='rehabilitating',days_remaining=2+old.severity*3))
                    kind='rehabilitation_started'
                elif old.phase=='rehabilitating':
                    rng=keyed(self.root_seed,'return_effect',pid,old.episode_id)
                    values=dict(state.abilities)
                    for k in values:
                        if k in ('power','contact','speed','strikeouts','stamina','durability'):
                            values[k]=clamp(values[k]-max(0,rng.gauss(.025*old.severity,.018)))
                    state=replace(state,abilities=values,injury=replace(old,phase='return_ready',days_remaining=4))
                    kind='return_cleared'
                else:state=replace(state,injury=None);kind='restriction_ended'
                self._emit(kind,pid,stamp,old.episode_id+':'+old.phase,state,{'assumption':True,'severity':old.severity})
            final=projected(state,on)
            if state.injury or state.fatigue!=final.fatigue:
                self._emit('calendar_recovery',pid,on,on,final,{'elapsed_calendar_days':(target-date.fromisoformat(state.as_of)).days})
        self.now=on;self._emit('clock_advanced',None,on,on,details={'current_date':on})

    def _health(self,pid,units,scope,source):
        s=self.current(pid);p=self.profiles[pid]
        if s.career_status!='active' or s.injury and s.injury.phase!='return_ready':return
        age=age_on(p.birth_date,self.now)
        factor=(1+2.5*s.fatigue)*(1+.025*max(0,age-27))*(1+.10*s.injury_history)*math.exp(-.25*s.abilities['durability'])
        probability=min(.35,1-math.exp(-.00030*units*factor))
        rng=keyed(self.root_seed,'injury',pid,scope)
        if rng.random()>=probability:return
        severity=rng.choices((1,2,3),(.70,.25,.05))[0]
        duration=rng.randint(*{1:(3,14),2:(15,45),3:(46,120)}[severity])
        episode=digest([pid,scope,'injury'])[:24]
        injury=Injury(episode,severity,'unavailable',duration,self.now)
        after=replace(s,injury=injury,injury_history=s.injury_history+1)
        self._emit('injury_started',pid,self.now,scope,after,{'severity':severity,'initial_rest_days':duration,
            'hazard_probability':probability,'exposure_origin':source,'medical_prediction':False})

    def load(self,pid,scope,*,pa=0,outs=0,bf=0,field_game=False,started=False,source='actual_game'):
        s=self.current(pid);p=self.profiles[pid]
        if not can_play(s):raise ValueError('Unavailable player cannot receive game exposure')
        if any(type(v) is not int or v<0 for v in (pa,outs,bf)):raise ValueError('Workloads are nonnegative recorded counts')
        if p.role=='batter':
            increment=.018*pa+(.04 if p.position=='C' else .025) * int(field_game)
            increment*=math.exp(-.12*s.abilities['endurance']);units=pa+5*int(field_game);experience=pa/500
        else:
            increment=(.018*outs+.005*bf)*math.exp(-.12*s.abilities['stamina']);units=.6*outs+.2*bf;experience=bf/700
        if units==0:return
        age=age_on(p.birth_date,self.now)
        rate=(.19 if p.role=='batter' else .33)*math.exp(.10*s.abilities['recovery'])/(1+.018*max(0,age-27))
        after=replace(s,fatigue=min(1,s.fatigue+increment),recovery_rate=rate,experience=s.experience+experience,
                      last_played=self.now,last_start=self.now if started else s.last_start)
        self._emit('workload',pid,self.now,scope,after,{'pa':pa,'pitching_outs':outs,'batters_faced':bf,
            'field_game':field_game,'started':started,'exposure_origin':source,'measured_pitch_count':None})
        self._health(pid,units,scope,source)

    def grow(self,on,*,environment=1.):
        if not .5<=environment<=1.5:raise ValueError('Unsupported development environment')
        year=int(on[:4])
        if year in self.grown_years:raise ValueError('Annual development already applied')
        self.advance(on)
        for pid in sorted(self.states):
            state=self.current(pid);p=self.profiles[pid];talent=self.talents[pid]
            if state.career_status!='active':continue
            age=age_on(p.birth_date,on);values={};changes={}
            rng=keyed(self.root_seed,'growth',pid,year)
            stagnant=rng.random()<talent.stagnation_chance
            breakout=rng.random()<.035
            for skill,current in state.abilities.items():
                peak=PEAKS[skill]+talent.maturation_offset
                if age<peak:
                    room=max(.05,1-max(0,current)/3)
                    drift=talent.growth_rate*talent.traits[skill]*room*environment*(.8+.04*min(state.experience,5))*(.65 if state.injury else 1-.15*state.fatigue)
                    if stagnant:drift=0
                    if breakout:drift+=rng.uniform(.12,.30)
                else:
                    coefficient=.027 if skill in ('contact','discipline','control') else .042 if skill in ('speed','recovery','stamina','endurance') else .033
                    drift=-coefficient*(age-peak+1)**1.12*(1-.6*talent.decline_resistance)
                noise=rng.gauss(0,talent.volatility*(.5 if stagnant else 1))
                values[skill]=clamp(current+drift+noise);changes[skill]=values[skill]-current
            new=replace(state,abilities=values,scouting=scout(values,keyed(self.root_seed,'scouting',pid,on),on))
            self._emit('annual_development',pid,on,str(year),new,{'age':age,'environment':environment,'stagnation_draw':stagnant,
                'breakout_draw':breakout,'changes':changes,'model_version':CAREER_VERSION,'uses_season_batting_average':False})
            # A simple stochastic exit, with no contract or dramatic story quota.
            risk=min(.6,max(0,age-35)**2*.0025)*math.exp(-.15*max(0,sum(values.values())/len(values)))
            if keyed(self.root_seed,'retirement',pid,year).random()<risk:
                self._emit('retired',pid,on,str(year),replace(new,career_status='retired'),{'reason':'age_ability_game_prior','probability':risk})
        self.grown_years.add(year)
        self._emit('development_completed',None,on,str(year),details={'year':year,'environment':environment})

    def transfer(self,pid,team_id,on):
        if team_id not in self.team_ids or pid not in self.profiles:raise ValueError('Unknown player/destination team')
        self.advance(on)
        s=self.current(pid)
        self._emit('affiliation_changed',pid,on,team_id+':'+on,replace(s,team_id=team_id),{'old_team_id':s.team_id,'new_team_id':team_id})

    def mark_game(self,game_id):
        if game_id in self.applied_games:raise ValueError('Game workload already applied')
        self.applied_games.add(game_id)
        self._emit('game_applied',None,self.now,game_id,details={'game_id':game_id})
