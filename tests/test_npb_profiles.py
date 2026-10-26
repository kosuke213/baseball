from pathlib import Path
from dataclasses import asdict,replace
import copy,hashlib,json,random,sqlite3
import pytest

from data_collection.npb_profiles import parse_profile,roster,Fetcher
from baseball_simulation_lab.npb_profiles.analysis import fit_group,describe,correlation,records
from baseball_simulation_lab.npb_profiles.model import Distribution,Physical,create_player,initial_rosters,birth_date_for_age
from baseball_simulation_lab.npb_profiles.storage import PhysicalStore,public_player
from baseball_simulation_lab.careers.generation import create_player as old_create
from baseball_simulation_lab.careers.public import player_view
from baseball_simulation_lab.careers.world import World
from baseball_simulation_lab.careers.storage import CareerStore
from baseball_simulation_lab.careers.domain import age_on
from baseball_simulation_lab.careers.randomness import keyed

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def model():return Distribution.load()

@pytest.fixture
def article_parser_dependency():
    pytest.importorskip('bs4',reason='Optional acquisition dependency; full npb-profiles CI installs requirements-research.txt')

def test_profile_units_joint_hands_and_unknown_are_not_right_default(article_parser_dependency):
    text='<table class="infobox"><tr><th>身長<br>体重</th><td>6 ft 2 in (188 cm)<br>95 kg</td></tr><tr><th>投球・打席</th><td>左投右打</td></tr><tr><th>国籍</th><td>日本</td></tr><tr><th>生年月日</th><td><span class="bday">2000-02-29</span></td></tr></table>'
    p=parse_profile(text,'https://ja.wikipedia.org/wiki/Test')
    assert (p['height_cm'],p['weight_kg'],p['throws'],p['bats'],p['birth_date'])==(188,95,'L','R','2000-02-29')
    p=parse_profile(text.replace('左投右打','未分類'),'url')
    assert p['throws'] is None and p['bats'] is None and p['nationality_text']=='日本'
    assert parse_profile(text.replace('<th>国籍</th><td>日本</td>','<th>出身地</th><td>日本</td>'),'url')['citizenship_group']=='unknown'
    assert parse_profile(text.replace('<td>日本</td>','<td>アメリカへ亡命</td>'),'url')['citizenship_group']=='unknown'

def test_roster_abs_links_separate_development_and_ignore_coaches(article_parser_dependency):
    text='<h2 id="選手・スタッフ">選手</h2><table><tr><th>監督</th><td><a href="/wiki/Coach">C</a></td></tr><tr><th>投手</th><td><a href="https://ja.wikipedia.org/wiki/A">A</a></td></tr><tr><th>育成選手</th></tr><tr><th>捕手</th><td><a href="./B">B</a><a href="/wiki/Special:X">X</a></td></tr></table>'
    rows=roster(text,2024,'T','url')
    assert [(r['title'],r['registration'],r['position']) for r in rows]==[('A','primary','P'),('B','development','C')]

def test_weighted_statistics_and_nonindependent_member_years():
    s=describe([170,190],[1,3]);assert s['mean']==185 and s['median']==190
    assert correlation([1,2,3],[3,5,7],[1,1,1])==pytest.approx(1)
    rows=[{'identity':str(i),'height_cm':180+i,'weight_kg':80+i,'age':20+i,'throws':'R','bats':'L','birth_date':'2000-01-01','weight':10,'citizenship_group':'japan'} for i in range(20)]
    cfg=json.loads((ROOT/'data_sources/stage11_5/config.json').read_text())
    fit=fit_group(rows*5,cfg)
    assert fit['unique_people']==20 and fit['rows']==100
    assert fit['hands_person_cluster_effective_n']==20
    assert sum(fit['hands'].values())==pytest.approx(20)

@pytest.mark.parametrize('on,age',[('2026-02-28',20),('2026-02-28',22),('2028-02-29',18),('2026-03-01',24)])
def test_sampled_completed_age_survives_leap_normalization(on,age):
    assert age_on(birth_date_for_age(on,age,2,29),on)==age

def test_checksum_and_unvalidated_corrections_rejected(model):
    p=copy.deepcopy(model.parameters);p['groups']['primary:all:all']['height_bias']+=1
    with pytest.raises(ValueError):Distribution(p)

@pytest.mark.parametrize('position',['P','C','IF','OF'])
def test_all_six_joint_hand_cells_are_possible_and_draws_reproducible(model,position):
    a=[model.sample(random.Random(i),position=position) for i in range(100)]
    b=[model.sample(random.Random(i),position=position) for i in range(100)]
    assert a==b and len({(x['height_cm'],x['weight_kg']) for x in a})>90
    assert all(x['throws'] in ('R','L') and x['bats'] in ('R','L','S') for x in a)
    assert all(x['source_position']==position and x['height_cm']>0 and x['weight_kg']>0 for x in a)

def test_generated_world_versions_ids_and_legacy_abilities_not_body_adjusted(model):
    entries=initial_rosters('profile-tests','2026-04-01',115026,distribution=model,team_ids=['A','B'])
    assert len(entries)==120 and len({e.profile.player_id for e in entries})==120
    for e in entries:
        e.profile.validate();e.talent.validate(e.profile);e.state.validate(e.profile);e.physical.validate()
        ordinal=next(i for i in range(1,33) if old_create('profile-tests',e.state.team_id,i,e.profile.role,'2026-04-01',115026)[0].player_id==e.profile.player_id)
        p,t,s=old_create('profile-tests',e.state.team_id,ordinal,e.profile.role,'2026-04-01',115026)
        assert t==e.talent and s==e.state
        assert e.profile.profile_version!='fictional-profiles-1' and not hasattr(p,'height_cm')
        assert age_on(e.profile.birth_date,'2026-04-01')>=16

def test_newcomers_not_silently_calibrated_from_stock(model):
    with pytest.raises(ValueError,match='No calibrated newcomer'):
        create_player('kids','A',10001,'batter','2026-04-01',1,distribution=model,candidate_age=18)
    e=create_player('kids','A',10001,'batter','2026-04-01',1,distribution=model,candidate_age=18,acknowledge_stock_proxy=True)
    assert age_on(e.profile.birth_date,'2026-04-01')==18 and e.profile.entry_age==18
    assert e.physical.origin=='stock_age_conditioned_proxy'
    with pytest.raises(ValueError):model.sample(random.Random(1),position='P',age=100)

def test_separate_random_stream_and_no_legacy_regeneration(model):
    baseline=old_create('fixed','A',1,'batter','2026-04-01',7)
    rng=keyed(7,'growth',baseline[0].player_id,2027);expected=rng.random()
    for i in range(30):create_player('other','A',i,'pitcher','2026-04-01',7,distribution=model)
    assert old_create('fixed','A',1,'batter','2026-04-01',7)==baseline
    assert keyed(7,'growth',baseline[0].player_id,2027).random()==expected

@pytest.fixture
def entry(model):return create_player('physical-store','A',1,'batter','2026-04-01',115026,distribution=model)

def test_immutable_weight_events_restore_and_dated_public_view(tmp_path,entry):
    path=tmp_path/'physical.sqlite3';store=PhysicalStore(path,world_id='physical-store',created_on='2026-04-01')
    store.register(entry.physical,entry.profile);old=store.at(entry.profile.player_id,'2026-04-01')
    store.advance('2027-04-01');store.register_weight(entry.profile.player_id,91.2,store.now,reason='explicit fictional registration')
    assert store.at(entry.profile.player_id,'2026-04-01')==old
    new=store.at(entry.profile.player_id,store.now);assert new['registered_weight_kg']==91.2
    assert new['annual_registered_weights']['2026']==entry.physical.baseline_weight_kg
    assert new['annual_registered_weights']['2027']==91.2
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM physical_events')
    store.close();store=PhysicalStore(path);assert store.at(entry.profile.player_id,store.now)==new
    with pytest.raises(ValueError):store.at(entry.profile.player_id,'2028-01-01')
    with pytest.raises(ValueError):store.register(entry.physical,entry.profile)
    store.close()

def test_sidecar_does_not_mutate_or_extend_career_database(tmp_path,entry):
    path=tmp_path/'career.sqlite3';w=World('physical-store','2026-04-01',1,['A']);w.enrol(entry.profile,entry.talent,entry.state)
    s=CareerStore(path);s.commit(w);s.close();before=path.read_bytes()
    with pytest.raises(ValueError):PhysicalStore(path)
    assert path.read_bytes()==before
    s=CareerStore(path);r=s.restore('physical-store');assert r.profiles==w.profiles and r.states==w.states;s.close()

def test_tamper_detected_even_on_open_sidecar(tmp_path,entry):
    s=PhysicalStore(tmp_path/'p.sqlite3',world_id='x',created_on='2026-04-01');s.register(entry.physical,entry.profile)
    s.db.execute('DROP TRIGGER immutable_physical_events_UPDATE')
    text=s.db.execute('SELECT record_json FROM physical_events').fetchone()[0];r=json.loads(text);r['details']['physical']['height_cm']+=1
    s.db.execute('UPDATE physical_events SET record_json=?',(json.dumps(r),));s.db.commit()
    with pytest.raises(ValueError):s.at(entry.profile.player_id,'2026-04-01')
    s.close()

def test_public_schema_no_latent_or_nested_private_payloads(tmp_path,entry):
    s=PhysicalStore(tmp_path/'p.sqlite3',world_id='x',created_on='2026-04-01');s.register(entry.physical,entry.profile)
    core=player_view(entry.profile,entry.state,'2026-04-01');body=s.at(entry.profile.player_id,'2026-04-01')
    result=public_player(core,body)
    assert not any(key in json.dumps(result) for key in ('private_talent','current_internal','maturation_offset','private_root_seed'))
    result['physical']['height_cm']=1;assert s.at(entry.profile.player_id,s.now)['height_cm']!=1
    assert public_player(core)['profile_extension_status']=='not_recorded_in_legacy_history'
    with pytest.raises(ValueError):public_player({**core,'name':{'private_talent':1}},body)
    with pytest.raises(ValueError):public_player({**core,'season_stats':[{'team_id':{'private_talent':1}}]},body)
    with pytest.raises(ValueError):public_player({**core,'rating_uncertainty':{'private_talent':1}},body)
    with pytest.raises(ValueError):public_player({**core,'current_injury_severity':{'private_talent':1}},body)
    for extra in ({'private_talent':{}},{'calibration_sha256':{'private_talent':1}},{'player_id':'other'},
                  {'registered_on':'2027-01-01'},{'body_version':'unknown'}):
        with pytest.raises(ValueError):public_player(core,{**body,**extra})
    with pytest.raises(ValueError):s.register_weight(entry.profile.player_id,90,s.now,reason={'private_talent':1})
    s.close()

@pytest.mark.parametrize('field,value',[('height_cm',float('nan')),('baseline_weight_kg',0),('birth_date','2030-01-01'),('body_version','future')])
def test_physical_value_validation(entry,field,value):
    with pytest.raises(ValueError):replace(entry.physical,**{field:value}).validate()

def test_prior_outputs_protected():
    for stage in ('stage5','stage10','stage11'):
        with pytest.raises(ValueError):PhysicalStore(ROOT/'data/research'/stage/'do-not-create.sqlite3',world_id='x',created_on='2026-04-01')

def test_player_year_dedup_promotion_multi_team_and_position_conflict(tmp_path):
    from data_collection.npb_profiles import dump
    def member(title,year,team,registration,position):return {'title':title,'year':year,'team':team,'registration':registration,'position':position,'source_url':f'url:{team}:{year}'}
    memberships=[member('A',2021,'X','primary','P'),member('A',2021,'X','development','P'),member('A',2021,'Y','primary','P'),
        member('A',2022,'Y','primary','P'),member('B',2021,'X','primary','P'),member('B',2021,'Y','primary','C')]
    p={'canonical_url':'article:A','source_url':'article:A','inclusion_probability':.5,'birth_date':'2000-01-01',
        'height_cm':180,'weight_kg':80,'throws':'R','bats':'R','citizenship_group':'japan'}
    dump(tmp_path/'memberships.json',memberships);dump(tmp_path/'profiles.json',{'A':p,'B':{**p,'canonical_url':'article:B'}})
    frame,observed,quarantine=records(tmp_path)
    assert len(frame)==3 and len(observed)==2 and len(quarantine)==1
    row=next(r for r in observed if r['year']==2021)
    assert row['registration']=='primary' and row['teams']==['X','Y'] and row['both_registrations']
    assert row['weight']==2 and row['age']==21

def test_fetcher_obeys_robots_budget_and_stops_on_429(tmp_path,monkeypatch):
    from urllib.robotparser import RobotFileParser
    from urllib.error import HTTPError
    import data_collection.npb_profiles as collection
    fetch=object.__new__(Fetcher);fetch.root=tmp_path;fetch.config={'maximum_new_requests':2,'request_interval_seconds':0};fetch.new_requests=0;fetch.last=0
    fetch.robots=RobotFileParser();fetch.robots.parse(['User-agent: *','Disallow: /wiki/Forbidden'])
    calls=[]
    def limited(req,**kw):calls.append(req.full_url);raise HTTPError(req.full_url,429,'limited',{},None)
    monkeypatch.setattr(collection,'urlopen',limited)
    with pytest.raises(ValueError,match='robots'):fetch.get('https://ja.wikipedia.org/wiki/Forbidden')
    assert not calls
    with pytest.raises(RuntimeError,match='stopped'):fetch.get('https://ja.wikipedia.org/wiki/Allowed')
    assert len(calls)==1
    with pytest.raises(ValueError,match='Previously failed'):fetch.get('https://ja.wikipedia.org/wiki/Allowed')
    assert len(calls)==1
