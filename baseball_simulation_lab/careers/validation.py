"""Controlled PA draws, frozen-roster games, real seasons, and annual-only cohorts."""
from collections import Counter,defaultdict
from dataclasses import asdict,replace
from datetime import date
from pathlib import Path
import json,math,random,statistics,time

from data_collection.fetch import write_json
from ..calibrated.identity import example_frame
from ..calibrated.rules import canonical
from ..completion.season import Season
from ..stability.engine import Game
from ..stability.validation import aggregate,compact,csv_file,describe
from ..fullgame.league import schedule
from .adapter import AbilityModel,Snapshot,ADAPTER_VERSION
from .domain import BAT_SKILLS,PITCH_SKILLS,age_on,can_play,state_dict
from .generation import initial_rosters,newcomers
from .integration import prepare_game,apply_game
from .world import World
from .storage import CareerStore
from .views import export_public


def new_world(world_id,on,root,team_ids=None):
    ids=team_ids or [f'T{i:02}' for i in range(1,13)];w=World(world_id,on,root,ids)
    for p,t,s in initial_rosters(world_id,on,root,ids):w.enrol(p,t,s)
    return w


def contrasts(base,output,n=100000):
    frame=example_frame(0);rows=[];scenarios=[('average_vs_average',0,0,0,0),('strong_batter_vs_average',1,0,0,0),
        ('average_vs_strong_pitcher',0,1,0,0),('strong_vs_strong',1,1,0,0),('fatigued_batter',0,0,.7,0),
        ('fatigued_pitcher',0,0,0,.7),('young_same_ability',0,0,0,0),('veteran_same_ability',0,0,0,0)]
    for index,(label,b,p,bfat,pfat) in enumerate(scenarios):
        actors=[Snapshot(frame.batter,'A','batter','2026-04-01',tuple((k,b-.55*bfat) for k in BAT_SKILLS),'available','contrast',bfat),
                Snapshot(frame.pitcher,'H','pitcher','2026-04-01',tuple((k,p-.55*pfat) for k in PITCH_SKILLS),'available','contrast',pfat)]
        model=AbilityModel(base,actors);prob=model.predict_pa(frame)
        # Identical ages/abilities get identical draws; other contrasts use fixed
        # independent streams, not cherry-picked favourable realizations.
        seed=110001 if label in ('average_vs_average','young_same_ability','veteran_same_ability') else 110001+index
        outcomes=random.Random(seed).choices(list(prob),weights=list(prob.values()),k=n);counts=Counter(outcomes)
        hits=sum(counts[k] for k in ('single','double','triple','home_run'));ab=n-sum(counts[k] for k in ('walk','hit_by_pitch','interference','sacrifice_bunt','sacrifice_fly'))
        rows.append({'scenario':label,'trials':n,'seed':seed,'probabilities':prob,'counts':dict(counts),'batting_average':hits/ab,
            'hr_rate':counts['home_run']/n,'bb_rate':counts['walk']/n,'k_rate':counts['strikeout']/n,
            'probability_interpretation':'conditional PA outcomes, not complete games','ages_have_no_direct_pa_bonus':True})
    write_json(Path(output)/'ability_contrasts.json',{'trials_per_scenario':n,'scenarios':rows,
        'basis':'bounded exponential odds; all coefficients are game-design assumptions, not measured latent talent',
        'limits':['finite samples overlap; strong players are not guaranteed success','same-ability young/veteran contrast isolates age; age affects recovery and development separately']})
    return rows


def frozen_games(base,output,config):
    output=Path(output);output.mkdir(parents=True)
    world=new_world('stage11-frozen',config['start_date'],config['benchmark_world_seed'])
    ids=world.team_ids;actual=[];neutral=[];failures=[];samples=[]
    start=time.perf_counter();checkpoints=[]
    for index in range(config['benchmark_games']):
        a=ids[index%12];b=ids[(index%12+1+index//12%11)%12]
        if a==b:raise ValueError('Benchmark self match')
        game,_=prepare_game(world,base,a,b,number=index+1,season_id='frozen-benchmark',record=index<3)
        r=game.run();actual.append(compact(r))
        if r['failure']:failures.append(r['failure'])
        # Same dated rosters and game RNG; Stage 10 league-average control.
        control=Game(base,game.teams,seed=game.seed,game_date=world.now,allow_assumptions=True,auto_relief_inning=7,record=False)
        neutral.append(compact(control.run()))
        if index<3:samples.append({'game_id':r['game_id'],'status':r['status']})
        if index+1 in (100,1000):
            report=aggregate(actual,time.perf_counter()-start);report['milestone']=index+1;checkpoints.append(report)
            print(f'Ability game check {index+1}: completed={report["completed_games"]}, failed={report["failed_games"]}',flush=True)
            if report['failed_games'] or report['record_integrity_failures'] or report['unresolved_priority_records']:break
    final=aggregate(actual,time.perf_counter()-start)
    csv_file(output/'games.csv',actual);csv_file(output/'neutral_games.csv',neutral)
    write_json(output/'validation.json',{**final,'checkpoints':checkpoints,'neutral_control':aggregate(neutral,0),
        'mode':'independent games from frozen initial healthy rosters; no accumulated career workload in this benchmark',
        'samples':samples,'config':config})
    write_json(output/'failures.json',{'failures':failures,'resampled_games':0})
    return final


def seasons(base,output,config):
    output=Path(output);output.mkdir(parents=True)
    world=new_world(config['world_id'],config['start_date'],config['world_seed'])
    store=CareerStore(output/'private_careers.sqlite3');store.commit(world)
    reports=[];game_rows=[];failed=None;start=time.perf_counter();past_payloads={};season_start_inputs_verified=True
    try:
        for offset in range(config['integrated_seasons']):
            year=int(config['start_date'][:4])+offset;season_id=f'{config["world_id"]}:{year}'
            world.advance(f'{year}-04-01');store.commit(world)
            # Explicit season-start snapshots; same IDs and actual current states.
            for pid in sorted(world.states):
                world._emit('season_started',pid,world.now,season_id,world.current(pid),{'season_id':season_id})
            store.commit(world)
            season_initial={pid:dict(world.current(pid).abilities) for pid in world.profiles}
            first_game_teams=set()
            league=Season(world.team_ids);fixture=schedule(list(world.team_ids),world.now)
            for item in fixture:
                world.advance(item['date'])
                try:game,snapshots=prepare_game(world,base,item['away'],item['home'],number=item['number'],season_id=season_id)
                except ValueError as exc:
                    failed={'reason':'roster_problem','detail':str(exc),'date':world.now,'scheduled_number':item['number'],'season_id':season_id};store.commit(world);break
                for team in game.teams:
                    if team.team_id not in first_game_teams:
                        for snap in snapshots:
                            if snap.team_id==team.team_id and dict(snap.current_internal)!=season_initial[snap.player_id]:raise ValueError('New season did not use committed current abilities')
                        first_game_teams.add(team.team_id)
                result=game.run()
                if result['status']=='failed':
                    store.commit(world,game=game,snapshots=snapshots,season_id=season_id,scheduled_number=item['number']);failed=result['failure'];break
                apply_game(world,game)
                store.commit(world,game=game,snapshots=snapshots,season_id=season_id,scheduled_number=item['number'])
                league.add(result);game_rows.append({'season_id':season_id,'number':item['number'],'date':world.now,**compact(result)})
                priority=not result['scoring_status']['rbi_complete'] or not result['scoring_status']['run_responsibility_complete'] or result['pitcher_decisions']['status'].startswith('manual')
                if priority:failed={'reason':'priority_record_incomplete','game_id':game.game_id};break
                if item['number']%100==0:print(f'Career league {year}: {item["number"]}/858 saved',flush=True)
            report=league.export();report.update(season_id=season_id,year=year,completed_on=world.now,
                status='completed' if len(league.results)==858 and failed is None else 'stopped')
            if report['status']=='completed':
                if any(r['games']!=143 for r in report['standings']):raise ValueError('Each team must play 143')
                if sum(r['w'] for r in report['standings'])!=sum(r['l'] for r in report['standings']):raise ValueError('Season W/L mismatch')
            store.save_season(world.world_id,season_id,world.now,report);reports.append(report)
            if failed:break
            past_payloads.update(dict(store.db.execute('SELECT game_id,payload_sha256 FROM games')))
            world.grow(f'{year}-11-01',environment=config['development_environment']);store.commit(world)
        # Replay games using the frozen Stage 10 interpreter, no ability model.
        rebuilt={r['season_id']:Season(world.team_ids) for r in reports}
        for season_id,gid in store.db.execute('SELECT season_id,game_id FROM season_games ORDER BY season_id,scheduled_number'):
            r=store.load(gid)
            if r['status'] in ('completed','draw'):rebuilt[season_id].add(r)
        for report in reports:
            replay=rebuilt[report['season_id']].export()
            if any(canonical(replay[k])!=canonical(report[k]) for k in ('games','players','standings')):raise ValueError('Replayed career season differs')
        if any(dict(store.db.execute('SELECT game_id,payload_sha256 FROM games')).get(g)!=sha for g,sha in past_payloads.items()):raise ValueError('Past game history changed')
        bad_inputs=store.db.execute("""SELECT count(*) FROM appearances a JOIN pregame_states p ON a.game_id=p.game_id AND a.player_id=p.player_id
            JOIN games g ON a.game_id=g.game_id WHERE json_extract(p.snapshot_json,'$.availability') NOT IN ('available','restricted','return_ready')
            OR json_extract(p.snapshot_json,'$.as_of')<>g.game_date""").fetchone()[0]
        if bad_inputs:raise ValueError('Ineligible/future pregame actor used')
        restored=store.restore(world.world_id)
        if canonical({p:state_dict(s) for p,s in restored.states.items()})!=canonical({p:state_dict(s) for p,s in world.states.items()}):raise ValueError('Career state replay differs')
        public=export_public(store,world.world_id,world.now).list_players()
        write_json(output/'public_players.json',public)
        write_json(output/'public_seasons.json',reports)
        events=Counter(e['event']['kind'] for e in world.events)
        # Only anonymous, sufficiently sized summaries of internal trait levels.
        grouped=defaultdict(list)
        for pid,p in world.profiles.items():
            s=world.current(pid);grouped[p.role,age_on(p.birth_date,world.now)//5*5].append(sum(s.abilities.values())/len(s.abilities))
        groups=[{'role':role,'age_band_start':band,**describe(values)} for (role,band),values in sorted(grouped.items()) if len(values)>=10]
        summary={'status':'completed' if len(reports)==config['integrated_seasons'] and not failed else 'stopped',
            'world_id':world.world_id,'seasons':len(reports),'executed_games':len(game_rows),'failure':failed,
            'events':dict(events),'all_game_replays_equal':True,'career_state_replay_equal':True,
            'players_generated':len(world.profiles),'player_ids_preserved':set(restored.profiles)==set(world.profiles),
            'current_date':world.now,'elapsed_seconds':time.perf_counter()-start,'ability_age_groups_anonymous':groups,
            'past_game_payloads_unchanged':True,'unavailable_or_future_actor_appearances':bad_inputs,'new_season_inputs_verified':True,'private_database_published':False,'rules':'DH batting lineups; approximate workload, no measured pitches; finite roster, no auto replacements'}
        write_json(output/'summary.json',summary);csv_file(output/'games.csv',game_rows)
        return summary
    finally:store.close()


def annual_cohort(output,config):
    output=Path(output);output.mkdir(parents=True)
    on=config['start_date'];world=World('annual-cohort20',on,config['cohort_seed'],['C01'])
    n=config['cohort_players']//2
    for role in ('batter','pitcher'):
        for p,t,s in newcomers(world.world_id,'C01',on,world.root_seed,n,role):world.enrol(p,t,s)
    store=CareerStore(output/'private_cohort.sqlite3');store.commit(world)
    curves=defaultdict(list);rows=[];sample_rows=[];private_rows=[]
    sample_ids=sorted(world.profiles)[:12]
    initial={pid:sum(s.abilities.values())/len(s.abilities) for pid,s in world.states.items()}
    for year in range(int(on[:4]),int(on[:4])+config['cohort_years']):
        world.advance(f'{year}-07-01')
        for pid,p in sorted(world.profiles.items()):
            if not can_play(world.current(pid)):continue
            if p.role=='batter':world.load(pid,f'annual-proxy:{year}',pa=500,field_game=True,source='annual_exposure_assumption_not_games')
            else:world.load(pid,f'annual-proxy:{year}',outs=500,bf=700,started=True,source='annual_exposure_assumption_not_games')
        world.grow(f'{year}-11-01',environment=1.)
        world.advance(f'{year+1}-04-01');store.commit(world)
        grouped=defaultdict(list);active=Counter()
        for pid,p in world.profiles.items():
            s=world.current(pid);age=age_on(p.birth_date,world.now);mean=sum(s.abilities.values())/len(s.abilities)
            curves[pid].append((age,mean));grouped[p.role].append(mean);active[p.role]+=s.career_status=='active'
            private_rows.append({'player_id':pid,'year':year+1,'age':age,'mean_internal':mean,'status':s.career_status})
            if pid in sample_ids:sample_rows.append({'sample_id':sample_ids.index(pid)+1,'year':year+1,'age':age,'mean_scouted_rating':statistics.mean(s.scouting['ratings'].values()),'status':s.career_status})
        for role,values in grouped.items():rows.append({'year':year+1,'role':role,'active':active[role],**describe(values)})
        print(f'Annual-only cohort {year+1}: {len(world.profiles)} IDs retained',flush=True)
    restored=store.restore(world.world_id)
    if canonical({p:state_dict(s) for p,s in restored.states.items()})!=canonical({p:state_dict(s) for p,s in world.states.items()}):raise ValueError('20-year state replay differs')
    store.close()
    events=Counter(e['event']['kind'] for e in world.events)
    counts={'improved_at_some_point':0,'stalled_first_ten':0,'peak_at_25_or_younger':0,'late_jump_29plus':0,'above_average_35plus':0,'declined_from_peak':0}
    for pid,curve in curves.items():
        vals=[v for age,v in curve];peak=max(vals);peak_age=curve[vals.index(peak)][0]
        counts['improved_at_some_point']+=peak>initial[pid]+.4
        counts['stalled_first_ten']+=max(vals[:10])<initial[pid]+.2
        counts['peak_at_25_or_younger']+=peak_age<=25
        counts['late_jump_29plus']+=any(age>=29 and v-curve[i-1][1]>.15 for i,(age,v) in enumerate(curve) if i)
        counts['above_average_35plus']+=any(age>=35 and v>.3 for age,v in curve)
        counts['declined_from_peak']+=vals[-1]<peak-.6
    csv_file(output/'anonymous_age_curves.csv',rows);csv_file(output/'public_sample_scouted_curves.csv',sample_rows)
    csv_file(output/'private_internal_curves.csv',private_rows)
    report={'players':len(world.profiles),'annual_steps':config['cohort_years'],'actual_games':0,'events':dict(events),'diversity_counts_overlapping':counts,
        'criterion_units':'continuous internal z; display ratings are a separate noisy estimate',
        'exposure':'500 PA or 500 pitching outs/700 BF annual proxy, not measured game records',
        'limits':['annual-only state validation, not 20 years of league games','injury/growth/retirement priors are game assumptions, not medical/NPB predictions'],
        'all_internal_values_in_bounds':all(-3<=v<=3 for s in world.states.values() for v in s.abilities.values()),
        'no_future_profiles_precomputed':True,'career_state_replay_equal':True}
    write_json(output/'summary.json',report)
    return report
