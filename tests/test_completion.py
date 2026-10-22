from dataclasses import replace
import copy
import json
from pathlib import Path
import random
import sqlite3

import pytest

from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.rules import canonical, frame_from_dict, Move, Plan
from baseball_simulation_lab.fullgame.engine import Game as OldGame, fictional_team
from baseball_simulation_lab.fullgame.model import GameModel as OldModel, assumed_play, Draw
from baseball_simulation_lab.fullgame.rules import Credit, Play, GameRules, apply_play as old_apply
from baseball_simulation_lab.fullgame.league import schedule
from baseball_simulation_lab.completion.engine import Game
from baseball_simulation_lab.completion.model import GameModel, bind
from baseball_simulation_lab.completion.rules import apply_play, timing_evidence
from baseball_simulation_lab.completion.sources import end_kind, recover_multi_force
from baseball_simulation_lab.completion.storage import HistoryStore, replay_game
from baseball_simulation_lab.completion.season import Season, run_league
from baseball_simulation_lab.completion.paths import ROOT, new_output

FAILURES=json.loads((ROOT/'data_sources/stage8/failures.json').read_text())['failures']
RESOLVED={8277,9221,15322}

@pytest.fixture(scope='module')
def model():
    return GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9/routes.json.gz',ROOT/'data_sources/stage9/terminal_model.json')

@pytest.fixture(scope='module')
def old_model():
    return OldModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage8/routes.json.gz')

@pytest.mark.parametrize('failure',FAILURES,ids=lambda f:str(f['seed']))
def test_each_old_failure_exact_and_new_interpretation(failure,old_model,model):
    f=failure
    g=OldGame(old_model,(fictional_team('LAB_A'),fictional_team('LAB_H')),seed=f['seed'],allow_assumptions=True,auto_relief_inning=7,record=False)
    assert canonical(g.run()['failure'])==canonical(f)
    frame=frame_from_dict(f['frame'])
    if f['sampled_outcome']=='runner_only_end':
        pre=frame.outs*8+frame.base_mask;cell=model.terminal['states'][str(pre)]
        assert cell['half_end_no_pa']==0 and cell['exposure']>0
        assert model.predict_step(frame)['runner_only_end']==0
        assert cell['wilson_95'][1]>0
        assert not model.choices(frame,'runner_only_end',False)
        return
    context=f['context'];attempt=frame_from_dict(context.get('attempted_frame',f['frame']))
    if context.get('attempted_action'):
        mapping={'B':frame.batter,**{str(i):r.player_id for i,r in enumerate(frame.bases,1) if r}}
        play=bind(context['attempted_action'],mapping,'empirical',context['route_ref'])
    else:play=assumed_play(attempt,f['sampled_outcome'])
    with pytest.raises(ValueError,match='walkoff_out_timing_unknown'):old_apply(attempt,play)
    if f['seed'] in RESOLVED:
        applied=apply_play(attempt,play);t=applied.transition
        assert t.after.finished and t.after.score[1]==t.after.score[0]+1
        assert t.after.outs==attempt.outs and not t.out_ids
        assert timing_evidence(attempt,play)
        people={r.player_id for r in attempt.bases if r}|{attempt.batter}
        destinations=[r.player_id for r in t.after.bases if r]+[r.player_id for r in t.scored]+list(t.halted_ids)
        assert len(destinations)==len(set(destinations)) and set(destinations)==people
    else:
        with pytest.raises(ValueError,match='walkoff_out_timing_unknown'):apply_play(attempt,play)

@pytest.mark.parametrize('pre',range(24))
def test_probability_contract_and_empirical_roe(model,pre):
    f=example_frame(pre);p=model.predict_step(f)
    assert sum(p.values())==pytest.approx(1) and all(v>=0 for v in p.values())
    assert model.predict_pa(f)==model.base.predict_pa(f)
    choices=model.choices(f,'reached_on_error',True)
    assert choices and all(row[2]=='empirical' for row in choices)
    for row in model.support_report(f,allow_assumptions=True):
        if row['probability']>0 and not row['empirical_n'] and not row['declared_assumption']:
            # Frozen PA calibration retains unsupported other_pa mass. Expose it;
            # do not mask or retry it to claim universal model support.
            assert row['outcome']=='other_pa'
            with pytest.raises(ValueError,match='no_training_route'):
                model.resolve_outcome(f,row['outcome'],random.Random(9),allow_assumptions=True)


def test_corrupt_new_model_and_future_training_refused(model,tmp_path):
    terminal=copy.deepcopy(model.terminal);terminal['training_seasons']=[2023,2024,2025]
    with pytest.raises(ValueError):GameModel(model.base,model.routes,terminal)
    terminal=copy.deepcopy(model.terminal);terminal['states']['0']['p_half_end_no_pa']=.1
    with pytest.raises(ValueError):GameModel(model.base,model.routes,terminal)
    for n in ('model_manifest.json','routes.json.gz','terminal_model.json'):
        (tmp_path/n).write_bytes((ROOT/'data_sources/stage9'/n).read_bytes())
    (tmp_path/'terminal_model.json').write_text('{}')
    with pytest.raises(ValueError,match='checksum'):GameModel.load(ROOT/'data_sources/stage7',tmp_path/'routes.json.gz',tmp_path/'terminal_model.json')


class Scripted:
    version='stage9-test-explicit-1'
    def sample(self,frame,rng,**kwargs):
        p=assumed_play(frame,'strikeout');return Draw('strikeout',(p,),1,p.plan.source_ref)


def test_history_replay_reproducibility_season_binding_and_immutability(tmp_path):
    teams=(fictional_team('A'),fictional_team('H'))
    g=Game(Scripted(),teams,rules=GameRules(9));r=g.run()
    g2=Game(Scripted(),teams,rules=GameRules(9));assert g2.run()==r
    assert replay_game(g.journal.rows)==r
    assert r['rules_version']!='fullgame-rules-1'
    assert r['scoring_status']['coverage_version']=='scoring-coverage-1'
    store=HistoryStore(tmp_path/'history.db')
    try:
        assert store.save(g) and not store.save(g)
        assert canonical(store.load(g.game_id))==canonical(r)
        assert store.bind_season(g.game_id,'S',1) and not store.bind_season(g.game_id,'S',1)
        with pytest.raises(ValueError):store.bind_season('other','S',1)
        with pytest.raises(sqlite3.IntegrityError):store.db.execute('delete from season_games')
        with pytest.raises(sqlite3.IntegrityError):store.db.execute('update appearances set h=99')
    finally:store.close()
    altered=copy.deepcopy(g.journal.rows);altered[1]['event']['parameters']['probability']=.4
    with pytest.raises(ValueError):replay_game(altered)
    with pytest.raises(ValueError):replay_game(g.journal.rows[:-1])
    old=OldGame(Scripted(),teams,rules=GameRules(9));old.run()
    with pytest.raises(ValueError):replay_game(old.journal.rows)


def test_season_counts_nulls_and_duplicate_rejection():
    g=Game(Scripted(),(fictional_team('A'),fictional_team('H')),rules=GameRules(9));r=g.run()
    season=Season(['A','H']);season.add(r);report=season.export()
    assert report['games']==1 and all(x['d']==1 for x in report['standings'])
    assert all(p['er'] is None and p['save'] is None and p['hold'] is None for p in report['players'] if p['kind']=='pitching')
    with pytest.raises(ValueError):season.add(r)
    assert season.export()==report


def test_league_gate_cannot_be_bypassed(tmp_path):
    bad={'attempted_games':1000,'failed_games':1,'record_integrity_failures':0,'unresolved_priority_records':0}
    with pytest.raises(ValueError,match='gate'):run_league(Scripted(),tmp_path/'league',[],{},bad)
    assert not (tmp_path/'league').exists()

@pytest.mark.parametrize('stage',['pilot','warehouse','stage5','stage6','stage7','stage8'])
def test_previous_stage_paths_protected(stage):
    for prefix in ('data/research','data_sources'):
        with pytest.raises(ValueError):new_output(ROOT/prefix/stage/'new')

@pytest.mark.parametrize('kind,pa,observed,post,reason',[
 ('pa_complete',1,1,0,None),('half_end_no_pa',0,1,24,None),
 ('walkoff_game_end',0,0,8,'walkoff'),('special_censored_end',1,0,8,'shortened_game'),('unknown',0,1,8,None)])
def test_end_definition(kind,pa,observed,post,reason):
    assert end_kind({'completed_pa':pa,'transition_observed':observed,'post_state':post,'censor_reason':reason})==kind

@pytest.mark.parametrize('row',json.loads((ROOT/'tests/fixtures/stage9/multi_force.json').read_text()),ids=lambda r:r['gid'])
def test_multi_force_LOB_recovery_and_strict_evidence(row):
    a=recover_multi_force(row)
    assert a['recovery_note']=='two_explicit_retirements_identify_omitted_LOB'
    assert len(a['source_out_ids'])==2
    assert a['source_scorers']==[]
    with pytest.raises(ValueError):recover_multi_force({**row,'event':row['event'].replace('/GDP','/UNKNOWN')})
    with pytest.raises(ValueError):recover_multi_force({**row,'runs':'1'})


def test_routes_version_parent_and_no_2025_sources(model):
    assert model.version.startswith('completion-model-1:')
    assert model.routes['version']=='scoring-routes-2'
    assert all(s['artifact_id'] in ('retro_plays_2023','retro_plays_2024') for s in model.routes['sources'].values())
    teams=(fictional_team('A'),fictional_team('H'))
    one=Game(Scripted(),teams);two_model=Scripted();two_model.version='future-model-version'
    two=Game(two_model,teams)
    assert one.game_id!=two.game_id
    one.run();two.run()
    assert one.result()['score']==two.result()['score']
    assert replay_game(one.journal.rows)==one.result()


def test_season_validation_is_atomic_and_manual_decisions_unknown():
    g=Game(Scripted(),(fictional_team('A'),fictional_team('H')),rules=GameRules(9));r=g.run()
    season=Season(['A','H'])
    bad=copy.deepcopy(r);next(iter(bad['batting'].values()))['h']=-1
    with pytest.raises(ValueError):season.add(bad)
    assert season.export()['games']==0
    r['pitcher_decisions']={'status':'manual_review_fixture','winner':None,'loser':None}
    season.add(r)
    assert all(p['w'] is None and p['l'] is None for p in season.export()['players'] if p['kind']=='pitching')


def test_source_certificate_and_appeal_cannot_be_guessed():
    f=next(r for r in FAILURES if r['seed']==8277);frame=frame_from_dict(f['frame']);c=f['context']
    mapping={'B':frame.batter,**{str(i):r.player_id for i,r in enumerate(frame.bases,1) if r}}
    p=bind(c['attempted_action'],mapping,'empirical',c['route_ref'])
    for changed in (replace(p,certified=False),replace(p,event_text=p.event_text+'/AP'),
                    replace(p,event_text=p.event_text.replace('9432','9432/AP'))):
        with pytest.raises(ValueError):apply_play(frame,changed)


def test_stop_keeps_seed_context_once_and_replays(tmp_path):
    from baseball_simulation_lab.fullgame.model import NoRoute
    class Unsupported:
        version='unrepresented-event-fixture';calls=0
        def sample(self,frame,rng,**kwargs):
            self.calls+=1
            raise NoRoute('other_pa',{'fixture':'no empirical support'})
    model=Unsupported();g=Game(model,(fictional_team('A'),fictional_team('H')),seed=12345)
    r=g.run()
    assert model.calls==1 and r['status']=='failed'
    assert r['failure']['seed']==12345 and r['failure']['sampled_outcome']=='other_pa'
    assert r['failure']['rng_state_after_failure']
    assert r['failure']['context']['fixture']=='no empirical support'
    assert canonical(replay_game(g.journal.rows))==canonical(r)
    store=HistoryStore(tmp_path/'failure.db')
    try:assert store.save(g) and store.load(g.game_id)['status']=='failed'
    finally:store.close()


def test_season_real_event_totals_and_win_loss_conservation():
    class OneRun(Scripted):
        def sample(self,f,rng,**kwargs):
            event='home_run' if f.inning==1 and f.half==0 and f.batter.endswith('B01') else 'strikeout'
            p=assumed_play(f,event);return Draw(event,(p,),1,p.plan.source_ref)
    season=Season(['A','H']);replayed=Season(['A','H'])
    for seed,team_ids in ((1,('A','H')),(2,('H','A'))):
        g=Game(OneRun(),tuple(fictional_team(t) for t in team_ids),seed=seed,rules=GameRules(9))
        r=g.run();assert r['score']==[1,0]
        season.add(r);replayed.add(replay_game(g.journal.rows))
    result=season.export();assert result==replayed.export()
    assert sum(t['w'] for t in result['standings'])==sum(t['l'] for t in result['standings'])==2
    assert all(t['games']==2 and t['w']==1 and t['l']==1 for t in result['standings'])
    assert sum(p['r'] for p in result['players'] if p['kind']=='batting')==2
    assert sum(p['outs'] for p in result['players'] if p['kind']=='pitching')==108
    assert sum(p['w'] for p in result['players'] if p['kind']=='pitching')==2
