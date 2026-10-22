from dataclasses import replace
from pathlib import Path
import copy,json,random,sqlite3
import pytest

from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.rules import canonical,frame_from_dict,Move,Plan
from baseball_simulation_lab.completion.engine import Game as OldGame,fictional_team
from baseball_simulation_lab.completion.model import bind,NoRoute
from baseball_simulation_lab.stability.engine import Game
from baseball_simulation_lab.stability.model import GameModel,terminal_play,PA_CLASSES
from baseball_simulation_lab.stability.rules import realize,apply_play,adjudicate_events,GameRules,Play,Credit
from baseball_simulation_lab.stability.timeline import Event,Edge,Timeline,generate,constraints
from baseball_simulation_lab.stability.storage import HistoryStore,replay_game
from baseball_simulation_lab.stability.probability import legal_terminal,beta_cdf,beta_quantile
from baseball_simulation_lab.stability.paths import ROOT,new_output
from baseball_simulation_lab.stability.season import Season,run_league

FAILURES=json.loads((ROOT/'data_sources/stage9/failures.json').read_text())['failures']

@pytest.fixture(scope='module')
def model():return GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9',ROOT/'data_sources/stage10/support_model.json')

@pytest.mark.parametrize('f',FAILURES,ids=lambda r:str(r['seed']))
def test_old62_exact_and_generated_counterfactual(f,model):
    old=OldGame(model.previous,(fictional_team('LAB_A'),fictional_team('LAB_H')),seed=f['seed'],allow_assumptions=True,auto_relief_inning=7,record=False)
    assert canonical(old.run()['failure'])==canonical(f)
    if f['sampled_outcome']=='other_pa':
        assert 'other_pa' not in model.predict_step(frame_from_dict(f['frame']))
        with pytest.raises(ValueError,match='quarantine'):model.resolve_outcome(frame_from_dict(f['frame']),'other_pa',random.Random(2),allow_assumptions=True)
        return
    c=f['context'];start=frame_from_dict(f['frame']);frame=frame_from_dict(c['attempted_frame'])
    mapping={'B':start.batter,**{str(i):r.player_id for i,r in enumerate(start.bases,1) if r}}
    play=bind(c['attempted_action'],mapping,'empirical',c['route_ref'])
    with pytest.raises(ValueError,match='timing_unknown'):apply_play(frame,play)
    first=generate(frame,play,random.Random(23));second=generate(frame,play,random.Random(23))
    assert first==second
    a=apply_play(frame,realize(frame,play,first));assert a.timing_source=='generated_assumption'
    assert a.transition.after.score[1]>a.transition.after.score[0]
    people={r.player_id for r in frame.bases if r}|{frame.batter}
    accounted=[r.player_id for r in a.transition.scored]+list(a.transition.out_ids)+list(a.transition.halted_ids)
    assert set(accounted)==people and len(accounted)==len(set(accounted))

@pytest.mark.parametrize('pre',range(24))
def test_positive_support_and_no_impossible_terminal_mass(pre,model):
    f=example_frame(pre);p=model.predict_step(f);c=model.support['states'][str(pre)]
    assert sum(p.values())==pytest.approx(1)
    assert (p['runner_only_end']>0)==legal_terminal(pre)
    if legal_terminal(pre):
        a=apply_play(f,realize(f,terminal_play(f,random.Random(pre)),generate(f,terminal_play(f,random.Random(pre)),random.Random(4))))
        assert a.transition.after.outs==3 and a.transition.after.score==f.score
        assert a.transition.after.orders==f.orders and not a.transition.completed_pa
        assert c['posterior_95'][0]<c['p']<c['posterior_95'][1]
    else:
        with pytest.raises(ValueError):terminal_play(f,random.Random(1))
    for r in model.support_report(f,allow_assumptions=True):
        if r['probability']>0:assert r['empirical_n'] or r['declared_assumption'] or r['generated_terminal_available']


def events(*rows):
    return Timeline(tuple(rows),(),tuple(r.event_id for r in rows),provenance='explicit_event')

@pytest.mark.parametrize('third_kind',['force','batter_before_first'])
def test_rule508_force_third_out_invalidates_prior_home(third_kind):
    f=replace(example_frame(21),inning=9,half=1,lineups=example_frame(21).lineups[::-1],pitchers=example_frame(21).pitchers[::-1])
    t=events(Event('h','score','R3',3,'H'),Event('o','out','R1',1,'OUT',third_kind))
    r=adjudicate_events(f,t)
    assert r['score']==[0,0] and r['out_ids']==['R1'] and not r['finished']


def test_rule508_tag_after_winning_run_is_cancelled():
    f=replace(example_frame(21),inning=9,half=1,lineups=example_frame(21).lineups[::-1],pitchers=example_frame(21).pitchers[::-1])
    r=adjudicate_events(f,events(Event('h','score','R3',3,'H'),Event('o','out','R1',1,'OUT','tag')))
    assert r['finished'] and r['score']==[0,1] and not r['out_ids']

@pytest.mark.parametrize('scorer_origin,expected',[(1,0),(3,1)])
def test_rule508_preceding_vs_trailing_appeal(scorer_origin,expected):
    f=replace(example_frame(23),inning=1)
    r=adjudicate_events(f,events(Event('h','score','R'+str(scorer_origin),scorer_origin,'H'),Event('o','out','R2',2,'OUT','appeal')))
    assert r['score'][0]==expected


def test_partial_constraints_and_unknown_or_fourth_out_refused():
    f=example_frame(20)
    with pytest.raises(ValueError):adjudicate_events(f,events(Event('h','score','R3',3,'H'),Event('o','out','B',0,'OUT','catch')))
    with pytest.raises(ValueError):adjudicate_events(f,events(Event('o','out','B',0,'OUT','unknown')))
    with pytest.raises(ValueError):adjudicate_events(f,events(Event('o','out','B',0,'OUT','tag'),Event('p','out','R3',3,'OUT','appeal')))
    t=Timeline((Event('a','score','R',3,'H'),Event('b','out','B',0,'OUT','tag')),(Edge('a','b','rule','test'),),('b','a'))
    with pytest.raises(ValueError):t.validate()


def test_beta_numerics_and_no_future_training(model):
    for q in (.025,.5,.975):
        x=beta_quantile(q,.5,10000.5);assert beta_cdf(x,.5,10000.5)==pytest.approx(q,abs=1e-8)
    support=copy.deepcopy(model.support);support['training_seasons'].append(2025)
    with pytest.raises(ValueError):GameModel(model.previous,support)
    support=copy.deepcopy(model.support);support['states']['11']['half_end_no_pa']=1
    with pytest.raises(ValueError):GameModel(model.previous,support)


def test_real_game_replay_immutable_season_and_legacy_separation(model,tmp_path):
    teams=(fictional_team('A'),fictional_team('H'));g=Game(model,teams,seed=310000,allow_assumptions=True,auto_relief_inning=7)
    r=g.run();assert r['status']!='failed'
    other=Game(model,teams,seed=310000,allow_assumptions=True,auto_relief_inning=7);assert canonical(other.run())==canonical(r)
    assert canonical(replay_game(g.journal.rows))==canonical(r)
    assert r['timing_provenance']['actions']['generated_assumption']>0
    assert r['scoring_status']['rbi_complete'] and r['record_integrity']['passed']
    store=HistoryStore(tmp_path/'history.db')
    try:
        assert store.save(g) and not store.save(g);assert store.bind_season(g.game_id,'S',1)
        assert canonical(store.load(g.game_id))==canonical(r)
        with pytest.raises(sqlite3.IntegrityError):store.db.execute('UPDATE games SET home_runs=99')
        with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM season_games')
    finally:store.close()
    altered=copy.deepcopy(g.journal.rows);altered[2]['event']['parameters']['timeline']['order']=altered[2]['event']['parameters']['timeline']['order'][::-1]
    with pytest.raises(ValueError):replay_game(altered)
    with pytest.raises(ValueError):replay_game(g.journal.rows[:-1])
    from baseball_simulation_lab.completion.storage import replay_game as previous_replay
    with pytest.raises(ValueError):previous_replay(g.journal.rows)
    one=Season(['A','H']);two=Season(['A','H']);one.add(r);two.add(replay_game(g.journal.rows))
    assert canonical(one.export())==canonical(two.export())
    with pytest.raises(ValueError):one.add(r)


def test_invalid_support_checksum_and_history_protection(model,tmp_path):
    for n in ('support_model.json','support_manifest.json'):(tmp_path/n).write_bytes((ROOT/'data_sources/stage10'/n).read_bytes())
    (tmp_path/'support_model.json').write_text('{}')
    with pytest.raises(ValueError,match='checksum'):GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9',tmp_path/'support_model.json')
    for name in ('stage5','stage6','stage7','stage8','stage9'):
        with pytest.raises(ValueError):new_output(ROOT/'data_sources'/name/'new')
        with pytest.raises(ValueError):HistoryStore(ROOT/'data_sources'/name/'new.db')


def test_league_gate_enforced(tmp_path):
    report={'attempted_games':1000,'failed_games':1,'record_integrity_failures':0,'unresolved_priority_records':0}
    with pytest.raises(ValueError,match='gate'):run_league(None,tmp_path/'league',[],{},report)
    assert not (tmp_path/'league').exists()

@pytest.mark.parametrize('case',json.loads((ROOT/'tests/fixtures/stage10/order_regressions.json').read_text()),ids=lambda x:x['route']['sha256'][:10])
def test_source_reverse_force_and_sacrifice_fly_graph_regressions(case):
    for seed in (7,23,904):
        f=example_frame(int(case['key'].split(':')[0]));mapping={'B':f.batter,**{str(i):r.player_id for i,r in enumerate(f.bases,1) if r}}
        for action in case['route']['actions']:
            p=bind(action,mapping,'empirical',case['route']['sha256'])
            a=apply_play(f,realize(f,p,generate(f,p,random.Random(seed))))
            f=a.transition.after
        assert f.outs<=3


def test_unknown_participant_refused_and_same_runner_appeal():
    f=example_frame(20)
    with pytest.raises(ValueError,match='participant'):adjudicate_events(f,events(Event('h','score','UNKNOWN',3,'H')))
    r=adjudicate_events(f,events(Event('h','score','R3',3,'H'),Event('o','out','R3',3,'OUT','appeal')))
    assert r['score']==[0,0]

@pytest.mark.parametrize('outcome',['walk','hit_by_pitch','interference'])
def test_generated_walkoff_forced_award_touches_first_and_credits_rbi(outcome):
    from baseball_simulation_lab.fullgame.model import assumed_play
    f=example_frame(7);f=replace(f,inning=9,half=1,lineups=f.lineups[::-1],pitchers=f.pitchers[::-1])
    p=assumed_play(f,outcome);timeline=generate(f,p,random.Random(10));a=apply_play(f,realize(f,p,timeline))
    assert a.transition.after.finished and a.transition.after.score==(0,1)
    assert 'touch:1:'+f.batter in a.executed_events
    assert a.credit.at_bat is False and len(a.credit.rbi_ids)==1
    assert not a.transition.out_ids

@pytest.mark.parametrize('pre,outcome,hit_bases',[(4,'double',1),(2,'double',2),(1,'triple',3),(7,'home_run',4)])
def test_rule906_generated_walkoff_hit_value_and_home_run(pre,outcome,hit_bases):
    from baseball_simulation_lab.fullgame.model import assumed_play
    f=example_frame(pre);f=replace(f,inning=9,half=1,lineups=f.lineups[::-1],pitchers=f.pitchers[::-1])
    p=assumed_play(f,outcome);a=apply_play(f,realize(f,p,generate(f,p,random.Random(44))))
    assert a.transition.after.finished and a.credit.hit_bases==hit_bases
    assert len(a.transition.scored)==(4 if outcome=='home_run' else 1)


def test_rule904_planned_reverse_force_dp_cancelled_becomes_rbi():
    case=next(c for c in json.loads((ROOT/'tests/fixtures/stage10/order_regressions.json').read_text()) if c['key']=='13:other_out:0')
    f=example_frame(13);f=replace(f,inning=9,half=1,lineups=f.lineups[::-1],pitchers=f.pitchers[::-1])
    mapping={'B':f.batter,**{str(i):r.player_id for i,r in enumerate(f.bases,1) if r}}
    p=bind(case['route']['actions'][0],mapping,'empirical',case['route']['sha256'])
    assert p.credit.ground_double_play and p.credit.rbi_ids==()
    a=apply_play(f,realize(f,p,generate(f,p,random.Random(2))))
    assert a.transition.after.finished and len(a.transition.out_ids)<2
    assert not a.credit.ground_double_play and a.credit.rbi_ids==tuple(r.player_id for r in a.transition.scored)
