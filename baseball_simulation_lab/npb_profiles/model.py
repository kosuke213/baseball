"""Sample joint physical profiles, independently of hidden talent/game RNG."""
from dataclasses import dataclass, replace, asdict
from datetime import date
from pathlib import Path
import calendar, hashlib, json, math
from ..careers.randomness import keyed
from ..careers import generation as legacy
from ..careers.domain import age_on

PROFILE_VERSION='npb-sampled-profile-1'
BODY_VERSION='physical-profile-1'
ROOT=Path(__file__).resolve().parents[2]

def birth_date_for_age(on,age,month,day):
    current=date.fromisoformat(on)
    year=current.year-age-int((month,day)>(current.month,current.day))
    valid_day=min(day,calendar.monthrange(year,month)[1]);born=date(year,month,valid_day)
    if age_on(born.isoformat(),on)!=age:
        # A Feb-29 draw plus a nonleap inferred birth year can cross the
        # completed-age boundary on Feb 28. Normalize to a valid Feb 28;
        # do not reroll either the age or the player.
        valid_day=min(valid_day,28)
        year=current.year-age-int((month,valid_day)>(current.month,current.day))
        born=date(year,month,valid_day)
    if age_on(born.isoformat(),on)!=age:raise ValueError('Calendar age normalization failed')
    return born.isoformat()

@dataclass(frozen=True)
class Physical:
    player_id:str
    birth_date:str
    height_cm:float
    baseline_weight_kg:float
    registered_on:str
    source_position:str
    reference_population:str
    distribution_key:str
    calibration_sha256:str
    origin:str='fictional_generation_from_sampled_distribution'
    body_version:str=BODY_VERSION

    def validate(self):
        if not self.player_id or self.source_position not in ('P','C','IF','OF'):raise ValueError('Invalid body identity/position')
        date.fromisoformat(self.registered_on);date.fromisoformat(self.birth_date)
        if not all(math.isfinite(v) and v>0 for v in (self.height_cm,self.baseline_weight_kg)):raise ValueError('Nonpositive/nonfinite physical value')
        if self.birth_date>self.registered_on or self.body_version!=BODY_VERSION:raise ValueError('Invalid body date/version')
        if self.origin not in ('fictional_generation_from_sampled_distribution','explicit_late_fictional_supplement','stock_age_conditioned_proxy'):
            raise ValueError('Physical origin must be explicit')
        return self

@dataclass(frozen=True)
class Generated:
    profile:object
    talent:object
    state:object
    physical:Physical

class Distribution:
    def __init__(self,parameters):
        value=json.loads(json.dumps(parameters));expected=value.pop('parameter_sha256')
        actual=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if actual!=expected or value['version']!='npb-wikipedia-sample-physical-1':raise ValueError('Calibration checksum/version differs')
        if any(value[k] for k in ('ability_correction','platoon_correction','annual_weight_change')):raise ValueError('Unvalidated corrections forbidden')
        self.parameters={**value,'parameter_sha256':expected};self.sha=expected

    @classmethod
    def load(cls,path=None):
        return cls(json.loads(Path(path or ROOT/'data_sources/stage11_5/parameters.json').read_text()))

    def _group(self,position,group,registration):
        groups=self.parameters['groups'];minimum=self.parameters['config']['body_minimum_unique_players']
        requested=f'{registration}:{position}:{group}'
        # Preserve non-Japan body mixtures where support permits. Small position
        # cells pool to that citizenship group before crossing groups.
        candidates=[requested,f'{registration}:all:{group}',f'{registration}:{position}:all',f'{registration}:all:all']
        for key in dict.fromkeys(candidates):
            if key in groups and groups[key]['complete_unique_people']>=minimum:return key,groups[key]
        raise ValueError('Insufficient measured profile support for this registration/population')

    def sample(self,rng,*,position=None,reference_group='all',registration='primary',age=None):
        cfg=self.parameters['config'];groups=self.parameters['groups']
        if position is None:
            weights=self.parameters['position_weights'];position=rng.choices(list(weights),weights=list(weights.values()))[0]
        if position not in ('P','C','IF','OF'):raise ValueError('Unknown official position mapping')
        if reference_group not in ('all','japan','non_japan','multiple','unknown'):raise ValueError('Unknown reference population')
        if reference_group=='all':
            base=groups.get(f'{registration}:{position}:all') or groups.get(f'{registration}:all:all')
            if not base:raise ValueError('Uncalibrated registration group')
            weights=base['citizenship_counts'];reference_group=rng.choices(list(weights),weights=list(weights.values()))[0]
        key,body=self._group(position,reference_group,registration)
        # Position-specific six-way joint hands with a fixed hierarchical prior.
        # Zero observations are not structural zeroes. Never infer matchup odds.
        labels=('RR','RL','RS','LL','LR','LS');global_g=groups[f'{registration}:all:all']
        global_counts=[global_g['hands'][k]+cfg['hand_global_cell_pseudocount'] for k in labels]
        norm=sum(global_counts);position_group=groups.get(f'{registration}:{position}:all') or global_g
        pos_prior=[position_group['hands'][k]+cfg['hand_position_global_prior_mass']*v/norm for k,v in zip(labels,global_counts)]
        pos_total=sum(pos_prior);local=groups.get(f'{registration}:{position}:{reference_group}') or position_group
        strength=cfg['hand_position_prior_strength']
        hand_weights=[local['hands'][k]+strength*v/pos_total for k,v in zip(labels,pos_prior)]
        hand=rng.choices(labels,weights=hand_weights)[0]
        cells=body['body_cells'];requested_age=age
        if age is not None:
            if type(age) is not int or age<16:raise ValueError('Candidate age must be a declared integer >=16')
            near=[c for c in cells if c['age_lower']<=age<c['age_lower']+cfg['body_age_bin_years']]
            if not near:raise ValueError('Requested age outside observed body age cells; no silent extrapolation')
            cells=near
        c=rng.choices(cells,weights=[x['weight'] for x in cells])[0]
        h=c['height_lower']+cfg['body_height_bin_cm']/2+body['height_bias']+rng.uniform(-cfg['body_height_bin_cm']/2,cfg['body_height_bin_cm']/2)
        w=c['weight_lower']+cfg['body_weight_bin_kg']/2+body['weight_bias']+rng.uniform(-cfg['body_weight_bin_kg']/2,cfg['body_weight_bin_kg']/2)
        if h<=0 or w<=0:raise ValueError('Invalid fitted body support')
        if age is None:
            lo=max(c['age_lower'],body['age_min']);hi=min(c['age_lower']+cfg['body_age_bin_years']-1,body['age_max'])
            age=rng.randint(lo,hi)
        months={int(k):v+1 for k,v in body['months'].items()}
        month=rng.choices(list(months),weights=list(months.values()))[0]
        # Calendar-valid birth day. Observed day histogram, not a made-up DOB.
        days={int(k):v+1 for k,v in body['days'].items() if int(k)<=calendar.monthrange(2000,month)[1]}
        day=rng.choices(list(days),weights=list(days.values()))[0]
        return {'height_cm':round(h,1),'weight_kg':round(w,1),'age':age,'birth_month':month,'birth_day':day,
                'throws':hand[0],'bats':hand[1],'source_position':position,'reference_population':reference_group,
                'distribution_key':key,'age_conditioned_stock_proxy':requested_age is not None}

def create_player(world_id,team_id,ordinal,role,on,root,*,distribution=None,reference_group='japan',
                  candidate_age=None,acknowledge_stock_proxy=False):
    if candidate_age is not None and not acknowledge_stock_proxy:
        raise ValueError('No calibrated newcomer distribution; explicitly acknowledge stock proxy or supply future rookie model')
    distribution=distribution or Distribution.load()
    p,t,s=legacy.create_player(world_id,team_id,ordinal,role,on,root,newcomer=candidate_age is not None)
    rng=keyed(root,'npb_physical_generation',p.player_id,f'{on}:{PROFILE_VERSION}:{distribution.sha}')
    if role=='pitcher':position='P'
    elif role=='batter':
        weights={k:v for k,v in distribution.parameters['position_weights'].items() if k in ('C','IF','OF')}
        position=rng.choices(list(weights),weights=list(weights.values()))[0]
    else:raise ValueError('Unknown career role')
    d=distribution.sample(rng,position=position,reference_group=reference_group,age=candidate_age)
    current=date.fromisoformat(on);born=birth_date_for_age(on,d['age'],d['birth_month'],d['birth_day'])
    elapsed=min(current.year-p.entry_year,max(0,d['age']-18)) if candidate_age is None else 0
    entry_year=current.year-elapsed;entry=current.replace(year=entry_year,day=min(current.day,calendar.monthrange(entry_year,current.month)[1])).isoformat()
    p=replace(p,birth_date=born,entry_date=entry,entry_year=entry_year,entry_age=age_on(born,entry),throws=d['throws'],bats=d['bats'],
              position=p.position if role=='pitcher' else position,profile_version=PROFILE_VERSION).validate()
    # All talent/current abilities/health and their RNG remain legacy draws.
    # Body does not become a causal ability or injury coefficient.
    t.validate(p);s.validate(p)
    body=Physical(p.player_id,born,d['height_cm'],d['weight_kg'],on,position,d['reference_population'],
                  d['distribution_key'],distribution.sha,origin='stock_age_conditioned_proxy' if candidate_age is not None else 'fictional_generation_from_sampled_distribution').validate()
    return Generated(p,t,s,body)

def initial_rosters(world_id,on,root,*,distribution=None,team_ids=None,batters=28,pitchers=32):
    if batters<9 or pitchers<2:raise ValueError('Finite roster too small')
    team_ids=team_ids or [f'T{i:02}' for i in range(1,13)]
    if len(set(team_ids))!=len(team_ids):raise ValueError('Duplicate team')
    distribution=distribution or Distribution.load()
    return [create_player(world_id,t,i,role,on,root,distribution=distribution) for t in team_ids for role,n in (('batter',batters),('pitcher',pitchers)) for i in range(1,n+1)]
