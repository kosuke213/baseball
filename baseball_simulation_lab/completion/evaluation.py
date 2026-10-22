"""Distribution changes and terminal-risk diagnostics, without 2025 fitting."""
from collections import Counter
from contextlib import closing
from dataclasses import replace
import csv
import json
import math
from pathlib import Path
import sqlite3

from data_collection.fetch import write_json
from ..calibrated.identity import example_frame
from ..calibrated.rules import canonical
from ..fullgame.engine import Game as OldGame, fictional_team
from ..fullgame.sources import input_paths


def run(model, output, root):
    rows=[]; worst=0
    for pre in range(24):
        for inning in (1,9,10):
            for half in (0,1):
                f=example_frame(pre)
                if half:f=replace(f,lineups=f.lineups[::-1],pitchers=f.pitchers[::-1],half=1)
                f=replace(f,inning=inning)
                a=model.base.predict_step(f); b=model.predict_step(f)
                tv=sum(abs(a[k]-b[k]) for k in a)/2;worst=max(worst,tv)
                rows.append({'pre':pre,'inning':inning,'half':half,'old_terminal_p':a['runner_only_end'],
                             'new_terminal_p':b['runner_only_end'],'total_variation':tv,
                             'conditional_pa_unchanged':canonical(model.predict_pa(f))==canonical(model.base.predict_pa(f))})
    _,s6,_,_=input_paths();scores={}
    with closing(sqlite3.connect('file:'+str(s6)+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;cache={}
        for year in (2023,2024,2025):
            n=0; totals={'old':[0.,0.,0], 'new':[0.,0.,0]};positives=0;zero_cases=[]
            for w in db.execute('select * from windows where season=? and (completed_pa=1 or (transition_observed=1 and outcome="runner_only_end"))',(year,)):
                key=(w['pre_state'],w['inning'],w['half'],w['score_diff'])
                if key not in cache:
                    f=example_frame(w['pre_state'])
                    if w['half']:f=replace(f,lineups=f.lineups[::-1],pitchers=f.pitchers[::-1],half=1)
                    diff=w['score_diff'];score=(max(0,diff),max(0,-diff)) if not w['half'] else (max(0,-diff),max(0,diff))
                    f=replace(f,inning=w['inning'],score=score)
                    cache[key]=(model.base.predict_step(f)['runner_only_end'], model.predict_step(f)['runner_only_end'])
                y=int(not w['completed_pa']);n+=1;positives+=y
                for name,p in zip(('old','new'),cache[key]):
                    totals[name][0]+=(p-y)**2;lik=p if y else 1-p
                    if lik==0:
                        totals[name][2]+=1
                        if name=='new':zero_cases.append({k:w[k] for k in ('game_id','pre_state','first_source_row','last_source_row')})
                    else:totals[name][1]-=math.log(lik)
            scores[str(year)]={'n':n,'positive_half_end_no_pa':positives,
                **{k:{'brier':v[0]/n,'binary_log_loss':None if v[2] else v[1]/n,
                      'infinite_log_loss':bool(v[2]),'zero_probability_observations':v[2]} for k,v in totals.items()},
                'new_zero_probability_cases':zero_cases}
    write_json(Path(output)/'model_comparison.json',{'contexts':rows,'worst_context_total_variation':worst,
        'conditional_pa_probabilities_unchanged':all(r['conditional_pa_unchanged'] for r in rows),
        'terminal_risk_diagnostics':scores,
        'limits':['Binary likelihood is for redefined normal half-end cohort, not full game predictive accuracy',
                  '2025 is known reference; one unseen runner-only double out remains outside training support',
                  'MLE zero cells have uncertainty and may fail future data; no claim of general positive support',
                  'ROE outcome mass unchanged; its synthetic prior removed, altering conditional route distribution']})


def audit_old_rbi(model, output, root):
    rows=list(csv.DictReader((root/'data_sources/stage8/games.csv').open(encoding='utf-8-sig')))
    seeds=[int(r['seed']) for r in rows if r['status']!='failed' and r['rbi_complete']=='False']
    if len(seeds)!=54:raise ValueError('Expected 54 old RBI-incomplete games')
    from ..fullgame.model import GameModel as OldModel
    from .engine import Game
    old=OldModel.load(root/'data_sources/stage7',root/'data_sources/stage8/routes.json.gz')
    teams=(fictional_team('LAB_A'),fictional_team('LAB_H'));cases=[]
    for seed in seeds:
        g=OldGame(old,teams,seed=seed,allow_assumptions=True,auto_relief_inning=7);r=g.run()
        events=[row['event']['parameters'] for row in g.journal.rows[1:]
                if row['event']['operation']=='play_v2' and row['event']['parameters']['credit']['rbi_ids'] is None]
        if r['scoring_status']['rbi_complete'] or not events:raise ValueError('Old RBI issue did not reproduce')
        new=Game(model,teams,seed=seed,allow_assumptions=True,auto_relief_inning=7,record=False).run()
        cases.append({'seed':seed,'old_unknown_batters':sorted(g.book.unknown_rbi),'old_unknown_events':events,
                      'new_status':new['status'],'new_rbi_complete':new['scoring_status']['rbi_complete'],
                      'comparison_limit':'new draws differ; no source-only judgment assigned to the old assumed error play'})
    write_json(Path(output)/'rbi54_comparison.json',{'old_cases_reproduced':54,
        'new_unknown_rbi_games':sum(not r['new_rbi_complete'] for r in cases),
        'old_causes':dict(Counter(e['plan']['outcome']+':'+e['plan']['source'] for r in cases for e in r['old_unknown_events'])),
        'cases':cases})
