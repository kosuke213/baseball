"""Modest correlated trait priors; fictional game design, not measured talent."""
from datetime import date
import uuid
from .domain import Profile,State,Talent,BAT_SKILLS,PITCH_SKILLS,age_on,clamp
from .randomness import keyed

FAMILIES=('佐藤','鈴木','高橋','田中','伊藤','渡辺','山本','中村','小林','加藤','吉田','山田','佐々木','山口','松本','井上','木村','林','清水','斎藤','池田','橋本','森','阿部','石川','前田','藤田','後藤','岡田','長谷川','村上','近藤')
GIVEN=('翔太','健太','大輔','拓也','直樹','和也','亮介','健一','誠','達也','悠太','浩二','駿','大地','陽介','涼介','優斗','隼人','康平','智也','颯太','裕介','祐樹','将太','航','悠人','修平','和真','隆之','亮太','大和','蓮')


def scout(abilities,rng,on):
    from .domain import display
    return {'observed_on':on,'rating_version':'noisy-scouting-1','ratings':{k:display(v+rng.gauss(0,.42)) for k,v in abilities.items()},'standard_error_points':6.3}


def create_player(world_id,team_id,ordinal,role,on,root,*,newcomer=False):
    rng=keyed(root,'initial_generation',team_id,f'{world_id}:{on}:{role}:{ordinal}:{newcomer}')
    day=date.fromisoformat(on);age=18 if newcomer else rng.choices((18,21,25,29,33,37),(1,2,3,3,2,1))[0]+rng.randrange(3)
    month=rng.randrange(1,13);birth_day=rng.randrange(1,29);birth_year=day.year-age-int((month,birth_day)>(day.month,day.day))
    born=date(birth_year,month,birth_day).isoformat()
    years=0 if newcomer else rng.randrange(age-17)
    entry=day.replace(year=day.year-years).isoformat()
    pid='P'+uuid.uuid5(uuid.NAMESPACE_URL,f'fictional-baseball/{world_id}/{on[:4]}/{team_id}/{role}/{ordinal}').hex[:23]
    position=(('C','IF','OF','DH')[ordinal%4] if role=='batter' else 'SP' if ordinal%3==0 else 'RP')
    p=Profile(pid,rng.choice(FAMILIES),rng.choice(GIVEN),born,entry,int(entry[:4]),age_on(born,entry),
        'L' if rng.random()<.25 else 'R',rng.choices(('L','R','S'),(.35,.60,.05))[0],position,role).validate()
    common=rng.gauss(0,.45);athletic=rng.gauss(0,.45);team_quality=keyed(root,'team_prior',team_id,world_id).gauss(0,.12)
    age_shift=-.5 if age<22 else -.15 if age>34 else 0
    skills=BAT_SKILLS if role=='batter' else PITCH_SKILLS
    values={k:clamp(.45*common+.20*athletic+rng.gauss(0,.60)+team_quality+age_shift) for k in skills}
    if role=='batter':
        slug=rng.gauss(0,.45);values['power']=clamp(values['power']+.4*slug);values['k_avoid']=clamp(values['k_avoid']-.2*slug)
    else:
        force=rng.gauss(0,.45);values['strikeouts']=clamp(values['strikeouts']+.35*force);values['control']=clamp(values['control']-.15*force)
        values['starter_aptitude']=clamp(values['starter_aptitude']+(.6 if position=='SP' else -.4))
        values['relief_aptitude']=clamp(values['relief_aptitude']+(.5 if position=='RP' else -.3))
        values['stamina']=clamp(values['stamina']+(.4 if position=='SP' else -.2))
    talent=Talent(rng.lognormvariate(-2.05,.35),rng.gauss(0,2.5),rng.random(),rng.uniform(.07,.15),rng.uniform(.15,.4),{k:rng.uniform(.35,1.35) for k in skills})
    past=rng.randrange(1,4) if rng.random()<.12 else 0
    state=State(pid,team_id,on,values,injury_history=past,background_injuries=past,
                scouting=scout(values,keyed(root,'scouting',pid,on),on)).validate(p)
    return p,talent,state


def initial_rosters(world_id,on,root,team_ids=None,batters=28,pitchers=32):
    if batters<9 or pitchers<2:raise ValueError('Finite initial roster is too small')
    team_ids=team_ids or [f'T{i:02}' for i in range(1,13)]
    if len(set(team_ids))!=len(team_ids):raise ValueError('Duplicate teams')
    return [create_player(world_id,t,i,role,on,root) for t in team_ids for role,n in (('batter',batters),('pitcher',pitchers)) for i in range(1,n+1)]


def newcomers(world_id,team_id,on,root,number,role='batter',ordinal_start=10001):
    return [create_player(world_id,team_id,ordinal_start+i,role,on,root,newcomer=True) for i in range(number)]
