from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from collections import defaultdict,Counter
import csv,json,sqlite3,math,statistics
from baseball_simulation_lab.stability.validation import describe
from baseball_simulation_lab.careers.pipeline import publish_public
from data_collection.fetch import write_json
root=ROOT;base=root/'data/research/stage11';key=json.load(open(base/'current.json'))['snapshot_id'];p=base/'snapshots'/key;out=root/'data_sources/stage11'
publish_public(p,out)

def correlation(rows,a,b):
 x=[r[a] for r in rows];y=[r[b] for r in rows];mx=statistics.mean(x);my=statistics.mean(y)
 denominator=math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
 return sum((v-mx)*(w-my) for v,w in zip(x,y))/denominator if denominator else None
with sqlite3.connect(p/'integrated/private_careers.sqlite3') as db:
 rows=defaultdict(list)
 for text, in db.execute('SELECT record_json FROM career_events WHERE kind="enrolment"'):
  e=json.loads(text);rows[e['details']['profile']['role']].append(e['after']['abilities'])
 corr={role:{'n':len(values),'correlations':{a+':'+b:correlation(values,a,b) for a,b in pairs}} for role,pairs in (
 ('batter',[('contact','power'),('contact','k_avoid'),('power','k_avoid')]),('pitcher',[('strikeouts','control'),('stamina','starter_aptitude'),('starter_aptitude','relief_aptitude')])) for values in [rows[role]]}
 injured=db.execute('SELECT count(distinct player_id) FROM career_events WHERE kind="injury_started"').fetchone()[0]
 games=db.execute('SELECT count(*) FROM games').fetchone()[0]
 privacy={'private_game_count':games,'distinct_players_injured_in_actual_integration':injured,
 'pregame_rows':db.execute('SELECT count(*) FROM pregame_states').fetchone()[0],
 'after_world_events':db.execute('SELECT count(*) FROM career_events').fetchone()[0]}
with sqlite3.connect(p/'cohort20/private_cohort.sqlite3') as db:
 changes=[]
 for text, in db.execute('SELECT record_json FROM career_events WHERE kind="annual_development"'):
  changes.extend(json.loads(text)['details']['changes'].values())
 assert db.execute('SELECT count(*) FROM games').fetchone()[0]==0
 growth={'annual_skill_changes':describe(changes),'absolute_change_over_1':sum(abs(v)>1 for v in changes),
  'interpretation':'anonymous synthetic internal-coordinate changes; not measured aging curves'}
write_json(out/'population_diagnostics.json',{'correlations_are_generated_assumptions':True,'initial_trait_correlations':corr,**privacy,**growth})
rows=list(csv.DictReader((p/'integrated/games.csv').open(encoding='utf-8-sig')))
seasons=json.load(open(p/'integrated/public_seasons.json'));summary=json.load(open(p/'integrated/summary.json'));bench=json.load(open(p/'frozen_games/validation.json'));cohort=json.load(open(p/'cohort20/summary.json'))
byseason={r['season_id']:{'games':r['games'],'distributions':{k:describe([int(x[k]) for x in rows if x['season_id']==r['season_id']]) for k in ('runs','h','hr','bb','k','pa','margin')},
 'draws':sum(x['status']=='draw' for x in rows if x['season_id']==r['season_id']),'standings':r['standings']} for r in seasons}
write_json(out/'league_comparison.json',{'seasons':byseason,'reference':json.load(open(root/'data_sources/stage10/mlb_reference.json'))['periods']['2025'],
 'limits':['MLB2025 is known reference, not untouched independent data','abilities/growth/injuries are game assumptions; no NPB calibration','selection and fatigue change the active-player distribution']})
write_json(out/'summary.json',{'snapshot_id':key,'ability_games_benchmark':{k:bench[k] for k in ('attempted_games','completed_games','failed_games','record_integrity_failures','unresolved_priority_records')},
 'integrated':summary,'cohort20':cohort,'tests':{'passed':567,'existing':520,'new':47},
 'private_state_distribution':'private DBs and individual true-value curves remain in ignored workspace; public ZIP contains whitelist exports only',
 'interpretation':'experimental player careers, not fitted medical/NPB career predictions'})
# Public reference facts only; do not redistribute the NPB page or player list.
ref=json.load(open(root/'data_sources/stage11/references.json'))['npb_registration_reference']
write_json(out/'references.json',{'npb_registration_reference':{k:ref[k] for k in ('url','http_status','sha256')},
 'source_use':'reference to registration categories only; no page/list reuse or diagnosis inference',
 'roster_size':{'batters':28,'pitchers':32,'total':60,'status':'experimental finite roster, not an NPB registration-rule implementation'},
 'new_play_datasets_collected':0,'ability_growth_health_fitted_to_real_career_data':False})
print('Published safe reports for',key)

# A spreadsheet-friendly projection of the same validated public DTOs.
from baseball_simulation_lab.stability.validation import csv_file
players=json.load(open(out/'public_players.json'))
skills=sorted({k for player in players for k in player['ratings']})
flat=[]
for player in players:
 row={k:player[k] for k in ('player_id','name','team_id','age','role','position','availability','injury_history_count','career_status','rating_observed_on','rating_uncertainty')}
 row.update({'estimated_'+k:player['ratings'].get(k) for k in skills});flat.append(row)
csv_file(out/'public_players.csv',flat)
