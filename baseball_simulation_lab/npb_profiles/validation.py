"""Fixed-seed aggregate distribution and unchanged-engine compatibility checks."""
from pathlib import Path
from collections import Counter,defaultdict
from dataclasses import asdict
import json,random,math,time,hashlib,sqlite3
import numpy as np
from data_collection.npb_profiles import ROOT,dump,new_stage_path
from .analysis import records,summary,describe,correlation,write_csv,weighted_quantile
from .model import Distribution,initial_rosters
from .storage import PhysicalStore,public_player
from ..careers.world import World
from ..careers.storage import CareerStore
from ..careers.integration import prepare_game
from ..careers.public import player_view
from ..careers.domain import state_dict
from ..calibrated.rules import canonical
from ..stability.storage import replay_game
from ..completion.season import Season

def generation_validation(root=None,output=None):
    root=new_stage_path(root or ROOT/'data/research/stage11_5');output=new_stage_path(output or ROOT/'data_sources/stage11_5')
    cfg=json.loads((output/'config.json').read_text());model=Distribution.load(output/'parameters.json');frame,observed,_=records(root)
    train=[r for r in observed if r['registration']=='primary' and r['year']<2025]
    # The model samples positions from the whole listed frame, then draws a
    # sampled profile conditional on that position. Use this same target for
    # comparison; report survey-weighted raw descriptors separately.
    total_pos=model.parameters['position_weights'];total=sum(total_pos.values());by=Counter()
    for r in train:by[r['position']]+=r['weight']
    target=[{**r,'weight':r['weight']*total_pos[r['position']]/by[r['position']]} for r in train]
    batches=[];all_rows=[]
    for seed in cfg['generation_seeds']:
        rng=random.Random(seed);batch=[]
        for i in range(cfg['players_per_seed']):
            d=model.sample(rng);r={**d,'identity':f'{seed}:{i}','position':d['source_position'],'weight':1.}
            batch.append(r);all_rows.append(r)
        batches.append({'seed':seed,**summary(batch)})
    expected=summary(target);actual=summary(all_rows)
    def water(field):
        a=[r for r in target if r.get(field) is not None];b=[r[field] for r in all_rows]
        qs=np.linspace(.005,.995,200)
        return float(np.mean([abs(weighted_quantile([r[field] for r in a],[r['weight'] for r in a],q)-weighted_quantile(b,[1.]*len(b),q)) for q in qs]))
    hand_tv=sum(abs(expected['handedness'][k]['weighted_share']-actual['handedness'][k]['weighted_share']) for k in ('RR','RL','RS','LL','LR','LS'))/2
    positions=Counter(r['position'] for r in all_rows);pos_tv=sum(abs(positions[k]/len(all_rows)-v/total) for k,v in total_pos.items())/2
    gates=cfg['generation_gates']
    errors={'height_mean_error_cm':abs(actual['height_cm']['mean']-expected['height_cm']['mean']),
            'weight_mean_error_kg':abs(actual['weight_kg']['mean']-expected['weight_kg']['mean']),
            'maximum_sd_relative_error':max(abs(actual[k]['sd_population']/expected[k]['sd_population']-1) for k in ('height_cm','weight_kg')),
            'height_weight_correlation_error':abs(actual['pearson_height_weight']-expected['pearson_height_weight']),
            'hand_total_variation':hand_tv,'position_total_variation':pos_tv,'age_wasserstein_years':water('age')}
    train_ids={r['identity'] for r in train};year25=[r for r in observed if r['registration']=='primary' and r['year']==2025]
    held=[r for r in year25 if r['identity'] not in train_ids]
    result={'generated_players':len(all_rows),'fixed_seeds':cfg['generation_seeds'],'players_per_seed':cfg['players_per_seed'],
            'training_target':expected,'generated':actual,'per_seed':batches,'errors':errors,'gates':gates,
            'gates_passed':{k:v<=gates[k] for k,v in errors.items()},'same_data_fit_check_not_independent':True,
            'reference_2025':summary(year25),'disjoint_person_2025':summary(held),
            'disjoint_person_2025_note':'no training person overlap, but physical values all observed at retrieval and small nonrandom profile coverage; not temporal predictive validation',
            'per_position':{p:{'target':summary([r for r in target if r['position']==p]),'generated':summary([r for r in all_rows if r['position']==p])} for p in ('P','C','IF','OF')},
            'field_wasserstein':{k:water(k) for k in ('height_cm','weight_kg','age')},
            'uncertainty':'Across-seed variation is generator Monte Carlo variability; not uncertainty of all NPB players.'}
    dump(output/'generation_validation.json',result)
    write_csv(output/'generation_by_seed.csv',[{'seed':b['seed'],'n':b['rows'],'height_mean_cm':b['height_cm']['mean'],'height_sd':b['height_cm']['sd_population'],
              'weight_mean_kg':b['weight_kg']['mean'],'weight_sd':b['weight_kg']['sd_population'],'pearson':b['pearson_height_weight']} for b in batches])
    dump(root/'generated_sample_private.json',all_rows)
    return result

def compatibility(root=None,output=None,game_count=100):
    from ..careers.pipeline import load_base
    root=new_stage_path(root or ROOT/'data/research/stage11_5');output=new_stage_path(output or ROOT/'data_sources/stage11_5')
    dest=root/'compatibility'
    if dest.exists():raise FileExistsError('Compatibility run is immutable; use a new destination')
    dest.mkdir(parents=True);start=time.perf_counter();base=load_base();d=Distribution.load(output/'parameters.json')
    entries=initial_rosters('npb-profile-world','2026-04-01',115026,distribution=d)
    w=World('npb-profile-world','2026-04-01',115026,[f'T{i:02}' for i in range(1,13)])
    side=PhysicalStore(dest/'physical.sqlite3',world_id=w.world_id,created_on=w.now);career=CareerStore(dest/'private_careers.sqlite3')
    for e in entries:w.enrol(e.profile,e.talent,e.state);side.register(e.physical,e.profile)
    career.commit(w);before={pid:state_dict(w.current(pid)) for pid in w.profiles}
    games=[]
    for i in range(game_count):
        away=w.team_ids[i%12];home=w.team_ids[(i+1+i//12)%12]
        if home==away:home=w.team_ids[(i+1)%12]
        game,snaps=prepare_game(w,base,away,home,on=w.now,season_id='physical-compatibility',number=i)
        result=game.run()
        if canonical(result)!=canonical(replay_game(game.journal.rows)):raise ValueError('Game replay differs')
        # This benchmark freezes healthy initial rosters; it is not a season.
        career.commit(w,game=game,snapshots=snaps)
        priority=not result['scoring_status']['rbi_complete'] or not result['scoring_status']['run_responsibility_complete'] or result['pitcher_decisions']['status'].startswith('manual')
        games.append({'game_id':game.game_id,'status':result['status'],'score':result['score'],
                      'record_errors':not result['record_integrity']['passed'],'unknown_priority':priority})
    assert before=={pid:state_dict(w.current(pid)) for pid in w.profiles}
    restored=career.restore(w.world_id)
    assert {pid:asdict(p) for pid,p in restored.profiles.items()}=={pid:asdict(p) for pid,p in w.profiles.items()}
    assert {pid:state_dict(restored.current(pid)) for pid in restored.profiles}==before
    public=[public_player(player_view(e.profile,w.current(e.profile.player_id),w.now),side.at(e.profile.player_id,w.now)) for e in entries]
    dump(output/'fictional_players.json',public)
    write_csv(output/'fictional_players.csv',[{'player_id':x['player']['player_id'],'name':x['player']['name'],'team_id':x['player']['team_id'],
         'age':x['player']['age'],'position':x['player']['position'],'throws':x['player']['throws'],'bats':x['player']['bats'],
         'birth_date':x['physical']['birth_date'],'height_cm':x['physical']['height_cm'],'weight_kg':x['physical']['registered_weight_kg'],
         'origin':x['physical']['origin']} for x in public])
    first=entries[0];pid=first.profile.player_id;old=side.at(pid,w.now);side.advance('2027-04-01')
    side.register_weight(pid,round(first.physical.baseline_weight_kg+1,1),side.now,reason='explicit API test; not automatic annual model')
    assert side.at(pid,'2026-04-01')==old
    side.close();side=PhysicalStore(dest/'physical.sqlite3');assert side.at(pid,'2027-04-01')['registered_weight_kg']==round(first.physical.baseline_weight_kg+1,1)
    side.close();career.close()
    result={'players':len(entries),'frozen_initial_roster_games':len(games),'completed_games':sum(g['status'] in ('completed','draw') for g in games),
            'failed_games':sum(g['status']=='failed' for g in games),'record_error_games':sum(bool(g['record_errors']) for g in games),
            'unknown_priority_games':sum(bool(g['unknown_priority']) for g in games),'game_journal_replays_equal':True,
            'new_profile_career_roundtrip_equal':True,'physical_weight_roundtrip_equal':True,'past_weight_view_unchanged':True,
            'attributes_only_no_new_ability_or_platoon_adjustment':True,'elapsed_seconds':time.perf_counter()-start}
    dump(output/'compatibility.json',result);dump(dest/'games.json',games)
    return result

def legacy_replay(output=None):
    output=Path(output or ROOT/'data_sources/stage11_5');base=ROOT/'data/research/stage11/snapshots/43b33331491d69d608bf9d2a'
    path=base/'integrated/private_careers.sqlite3'
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    before=sha(path);store=CareerStore(path);w=store.restore('stage11-integrated')
    reports=store.seasons_at(w.world_id,w.now);seasons={r['season_id']:Season(w.team_ids) for r in reports};count=0
    for season,gid in store.db.execute('SELECT season_id,game_id FROM season_games ORDER BY season_id,scheduled_number'):
        r=store.load(gid);seasons[season].add(r);count+=1
    for r in reports:
        rebuilt=seasons[r['season_id']].export()
        for key in ('games','standings','players'):assert canonical(rebuilt[key])==canonical(r[key])
    assert len(w.profiles)==720 and count==1716 and not any(hasattr(p,'height_cm') for p in w.profiles.values())
    store.close();assert before==sha(path)
    # Verify every old private/public snapshot payload against its saved manifest.
    from ..completion.pipeline import verify_snapshot
    verify_snapshot(base)
    result={'old_players':720,'games_replayed':count,'seasons_rebuilt':len(reports),'rankings_and_player_totals_equal':True,
            'old_database_sha256_before':before,'old_database_sha256_after':sha(path),'old_snapshot_all_payload_hashes_equal':True,
            'legacy_physical_values_not_auto_added':True,'probability_model_required_for_replay':False}
    dump(output/'legacy_replay.json',result)
    return result
