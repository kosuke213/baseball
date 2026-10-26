from dataclasses import asdict,replace
from datetime import date
from pathlib import Path
import copy,json,math,random,sqlite3
import pytest

from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.rules import canonical
from baseball_simulation_lab.stability.engine import Game,fictional_team
from baseball_simulation_lab.stability.model import GameModel
from baseball_simulation_lab.stability.storage import replay_game
from baseball_simulation_lab.careers.domain import Profile,State,Injury,age_on,can_play,availability,state_dict
from baseball_simulation_lab.careers.generation import initial_rosters,newcomers
from baseball_simulation_lab.careers.world import World
from baseball_simulation_lab.careers.randomness import keyed
from baseball_simulation_lab.careers.adapter import AbilityModel,Snapshot,snapshot
from baseball_simulation_lab.careers.manager import select,RosterShortage
from baseball_simulation_lab.careers.integration import prepare_game,apply_game
from baseball_simulation_lab.careers.storage import CareerStore
from baseball_simulation_lab.careers.public import PublicAPI,player_view
from baseball_simulation_lab.careers.views import export_public
from baseball_simulation_lab.careers.validation import new_world

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def base():return GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9',ROOT/'data_sources/stage10/support_model.json')

@pytest.fixture
def world():return new_world('test-world','2026-04-01',110026,team_ids=['T01','T02'])


def test_generation_unique_dates_correlations_and_separate_newcomers(world):
    assert len(world.profiles)==120 and len(set(world.profiles))==120
    for pid,p in world.profiles.items():
        p.validate();world.current(pid).validate(p)
        assert p.entry_age==age_on(p.birth_date,p.entry_date)
        assert all(-3<=v<=3 for v in world.current(pid).abilities.values())
    kids=newcomers('test-world','T01',world.now,world.root_seed,20)
    assert not set(p.player_id for p,t,s in kids)&set(world.profiles)
    assert all(age_on(p.birth_date,world.now)==p.entry_age==18 for p,t,s in kids)
    assert not any('future' in k for p,t,s in kids for k in asdict(p))

@pytest.mark.parametrize('born,on,age',[('2008-10-26','2026-10-25',17),('2008-10-26','2026-10-26',18),('2008-02-29','2026-02-28',17),('2008-02-29','2026-03-01',18)])
def test_calendar_age(born,on,age):assert age_on(born,on)==age

@pytest.mark.parametrize('pre',range(24))
def test_normalization_support_and_exact_mean_fallback(base,pre):
    f=example_frame(pre)
    neutral=AbilityModel(base,[])
    assert neutral.predict_step(f)==base.predict_step(f)
    actors=[Snapshot(f.batter,'A','batter','2026-04-01',(('power',2.),('discipline',1.)),'available','test'),
            Snapshot(f.pitcher,'H','pitcher','2026-04-01',(('control',-2.),('strikeouts',2.)),'available','test')]
    model=AbilityModel(base,actors);p=model.predict_step(f);old=base.predict_step(f)
    assert sum(p.values())==pytest.approx(1) and all(0<=v<=1 for v in p.values())
    assert {k for k,v in p.items() if v>0}=={k for k,v in old.items() if v>0}
    assert p['runner_only_end']==old['runner_only_end']


def test_ability_directions_fatigue_and_frozen_input(base,world):
    f=example_frame(0)
    neutral=AbilityModel(base,[]).predict_pa(f)
    strong=AbilityModel(base,[Snapshot(f.batter,'A','batter',world.now,(('power',1.),),'available','test')])
    assert strong.predict_pa(f)['home_run']>neutral['home_run']
    pitcher=AbilityModel(base,[Snapshot(f.pitcher,'H','pitcher',world.now,(('strikeouts',1.),('control',1.)),'available','test')])
    assert pitcher.predict_pa(f)['strikeout']>neutral['strikeout'] and pitcher.predict_pa(f)['walk']<neutral['walk']
    pid=next(pid for pid,p in world.profiles.items() if p.role=='batter');p=world.profiles[pid];s=world.current(pid)
    before=snapshot(p,s,world.now);tired=snapshot(p,replace(s,fatigue=.8),world.now)
    assert tired.values()['power']<before.values()['power']
    model=AbilityModel(base,[before]);frozen=model.version;world.grow('2026-11-01')
    assert model.version==frozen and model.snapshots[pid]==before
    with pytest.raises(TypeError):model.snapshots[pid]=tired
    with pytest.raises(ValueError):model.validate_game_date('2027-04-01')


def test_disabled_adapter_reproduces_stage10_complete_journal(base):
    teams=(fictional_team('AWAY'),fictional_team('HOME'))
    a=Game(base,teams,seed=310000,allow_assumptions=True,auto_relief_inning=7)
    disabled=AbilityModel(base,[],enabled=False);b=Game(disabled,teams,seed=310000,allow_assumptions=True,auto_relief_inning=7)
    assert canonical(a.run())==canonical(b.run())
    assert canonical(a.journal.rows)==canonical(b.journal.rows)
    assert disabled.version==base.version

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),4.,-5.])
def test_invalid_effective_abilities_rejected(bad):
    with pytest.raises(ValueError):Snapshot('B','A','batter','2026-04-01',(('power',bad),),'available','test')


def test_injury_rehab_return_and_dated_history(world,tmp_path):
    pid=next(iter(world.states));s=world.current(pid)
    injury=Injury('fixture-episode',2,'unavailable',3,world.now)
    world._emit('injury_fixture',pid,world.now,'fixture',replace(s,injury=injury,injury_history=s.injury_history+1))
    assert not can_play(world.current(pid))
    store=CareerStore(tmp_path/'private.sqlite3');store.commit(world)
    world.advance('2026-04-04');assert availability(world.current(pid))=='rehabilitating'
    world.advance('2026-04-12');assert availability(world.current(pid))=='return_ready'
    assert can_play(world.current(pid))
    world.advance('2026-04-16');assert availability(world.current(pid))=='available'
    store.commit(world)
    assert availability(store.state_at(world.world_id,pid,'2026-04-02'))=='unavailable'
    assert availability(store.state_at(world.world_id,pid,'2026-04-06'))=='rehabilitating'
    with pytest.raises(ValueError):store.state_at(world.world_id,pid,'2027-01-01')
    store.close()


def test_actual_game_workload_recovery_and_replay(base,world,tmp_path):
    store=CareerStore(tmp_path/'private.sqlite3');store.commit(world)
    game,snapshots=prepare_game(world,base,'T01','T02');r=game.run();assert r['status'] in ('completed','draw')
    before={p:world.current(p).fatigue for p in r['batting']}
    apply_game(world,game)
    assert any(world.current(p).fatigue>before[p] for p in before)
    store.commit(world,game=game,snapshots=snapshots,season_id='2026',scheduled_number=1)
    assert canonical(store.load(game.game_id))==canonical(r)
    with pytest.raises(ValueError):apply_game(world,game)
    saved=canonical(store.load(game.game_id));world.grow('2026-11-01');store.commit(world)
    assert canonical(store.load(game.game_id))==saved
    restored=store.restore(world.world_id)
    assert canonical({p:state_dict(s) for p,s in restored.states.items()})==canonical({p:state_dict(s) for p,s in world.states.items()})
    assert set(restored.profiles)==set(world.profiles)
    assert canonical(replay_game(game.journal.rows))==canonical(r)
    assert store.db.execute('SELECT count(*) FROM pregame_states').fetchone()[0]==len(snapshots)
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM career_events')
    store.close()


def test_roster_shortage_and_unavailable_players_are_not_silently_replaced(base,world):
    excluded=[]
    for pid,p in world.profiles.items():
        if world.states[pid].team_id=='T01' and p.role=='batter':
            s=world.current(pid);world._emit('injury_fixture',pid,world.now,pid,replace(s,injury=Injury('x'+pid,1,'unavailable',5,world.now)));excluded.append(pid)
    with pytest.raises(RosterShortage):select(world,'T01')
    assert len(world.profiles)==120
    assert all(not can_play(world.current(p)) for p in excluded)


def test_independent_streams_and_future_not_materialized(world):
    assert keyed(world.root_seed,'growth','B',2026).getstate()!=keyed(world.root_seed,'injury','B',2026).getstate()
    copied=copy.deepcopy(world);a,b=list(world.states)[:2]
    s=copied.current(a);copied._emit('injury_fixture',a,copied.now,'x',replace(s,injury=Injury('x',1,'unavailable',5,copied.now)))
    world.grow('2026-11-01');copied.grow('2026-11-01')
    assert world.current(b).abilities==copied.current(b).abilities
    assert all(e['event']['event_date']<=world.now for e in world.events)
    again=new_world('test-world','2026-04-01',110026,['T01','T02']);again.grow('2026-11-01')
    assert canonical(world.events)==canonical(again.events)
    with pytest.raises(ValueError):world.grow('2026-12-01')


def test_public_api_never_exports_private_traits_or_rng(world,tmp_path):
    store=CareerStore(tmp_path/'private.sqlite3');store.commit(world)
    api=export_public(store,world.world_id,world.now);data=api.list_players();text=json.dumps(api.__dict__,ensure_ascii=False)
    for forbidden in ('private_root_seed','growth_rate','maturation_offset','entry_abilities','abilities','current_internal','random_state','private_talent'):
        assert forbidden not in text
    assert all('ratings' in p and 'rating_uncertainty' in p for p in data)
    first=data[0];first['ratings']['private_root_seed']=123
    with pytest.raises(ValueError):PublicAPI([first])
    private=copy.deepcopy(data[1]);private['private_talent']={}
    with pytest.raises(ValueError):PublicAPI([private])
    with pytest.raises(ValueError):export_public(store,world.world_id,'2027-01-01')
    store.close()


def test_affiliation_history_profile_fixed_and_future_inputs_refused(world,tmp_path):
    pid=next(iter(world.states));profile=world.profiles[pid]
    store=CareerStore(tmp_path/'private.sqlite3');store.commit(world)
    world.transfer(pid,'T02','2026-04-03');store.commit(world)
    assert store.state_at(world.world_id,pid,'2026-04-01').team_id=='T01'
    assert store.state_at(world.world_id,pid,'2026-04-03').team_id=='T02'
    assert world.profiles[pid]==profile
    with pytest.raises(ValueError):world.advance('2026-04-02')
    store.close()


def test_tampering_and_game_snapshot_conflict_roll_back(base,world,tmp_path):
    path=tmp_path/'private.sqlite3';store=CareerStore(path);store.commit(world)
    game,snaps=prepare_game(world,base,'T01','T02');game.run();apply_game(world,game)
    bad=(replace(snaps[0],fatigue=.7),*snaps[1:])
    with pytest.raises(ValueError):store.commit(world,game=game,snapshots=bad,season_id='S',scheduled_number=1)
    assert store.db.execute('SELECT count(*) FROM games').fetchone()[0]==0
    store.commit(world,game=game,snapshots=snaps,season_id='S',scheduled_number=1)
    store.db.execute('DROP TRIGGER immutable_career_events_UPDATE')
    with store.db:store.db.execute("UPDATE career_events SET record_sha256='tampered' WHERE sequence=1")
    with pytest.raises(ValueError):store.restore(world.world_id)
    store.close()


def test_prior_schemas_and_outputs_protected(tmp_path):
    from baseball_simulation_lab.stability.storage import HistoryStore
    path=tmp_path/'old.sqlite3';old=HistoryStore(path);old.close();before=path.read_bytes()
    with pytest.raises(ValueError):CareerStore(path)
    assert path.read_bytes()==before
    for name in ('stage5','stage6','stage7','stage8','stage9','stage10'):
        with pytest.raises(ValueError):CareerStore(ROOT/'data_sources'/name/'no.sqlite3')


def test_same_entrant_can_have_different_futures_and_environment_effect():
    p,t,s=newcomers('rookie','T01','2026-04-01',77,1)[0]
    worlds=[]
    for name,root,env in [('one',100,1.),('other',101,1.),('development',100,1.5)]:
        w=World(name,'2026-04-01',root,['T01']);w.enrol(p,t,s);w.grow('2026-11-01',environment=env);worlds.append(w)
    assert worlds[0].current(p.player_id).abilities!=worlds[1].current(p.player_id).abilities
    assert sum(worlds[2].current(p.player_id).abilities.values())>=sum(worlds[0].current(p.player_id).abilities.values())
    assert all(w.profiles[p.player_id]==p for w in worlds)


def test_recovery_uses_calendar_and_load_rates_not_fictional_pitches(world):
    pid=next(iter(world.states));world.load(pid,'fixture',pa=4,field_game=True)
    first=world.current(pid).fatigue
    assert first>0
    world.advance('2026-04-02');second=world.current(pid).fatigue
    world.advance('2026-04-10');assert world.current(pid).fatigue<second<first
    workload=next(e['event']['details'] for e in world.events if e['event']['kind']=='workload')
    assert workload['measured_pitch_count'] is None


def test_public_historical_cutoff_excludes_new_players_and_future_scouting(world,tmp_path):
    store=CareerStore(tmp_path/'world.sqlite3');store.commit(world)
    count=len(world.profiles);world.grow('2026-11-01');world.advance('2027-04-01')
    for p,t,s in newcomers(world.world_id,'T01',world.now,world.root_seed,2):world.enrol(p,t,s)
    store.commit(world)
    past=export_public(store,world.world_id,'2026-04-01').list_players()
    assert len(past)==count and all(p['rating_observed_on']=='2026-04-01' for p in past)
    assert len(export_public(store,world.world_id,world.now).list_players())==count+2
    store.close()


def test_rejected_development_does_not_advance_time_and_latent_nan_refused(world):
    world.grow('2026-11-01');before=canonical(world.events);now=world.now
    with pytest.raises(ValueError):world.grow('2026-12-01')
    assert world.now==now and canonical(world.events)==before
    p,t,s=newcomers('bad','T01',now,3,1)[0]
    with pytest.raises(ValueError):world.enrol(p,replace(t,growth_rate=float('nan')),s)
