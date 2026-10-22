"""Reproduce each old failure before comparing rules and revised full games."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import random
import sqlite3

from data_collection.fetch import write_json
from ..calibrated.rules import canonical, frame_from_dict
from ..fullgame.engine import Game as OldGame, fictional_team
from ..fullgame.model import GameModel as OldModel, assumed_play
from ..fullgame.sources import input_paths
from .engine import Game
from .model import bind
from .rules import apply_play, timing_evidence


def run(model, output, root):
    failures=json.loads((root/'data_sources/stage8/failures.json').read_text())['failures']
    old=OldModel.load(root/'data_sources/stage7',root/'data_sources/stage8/routes.json.gz')
    teams=(fictional_team('LAB_A'),fictional_team('LAB_H'));results=[]
    _,s6,_,_=input_paths();db=sqlite3.connect('file:'+str(s6)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        for i,f in enumerate(failures):
            g=OldGame(old,teams,seed=f['seed'],allow_assumptions=True,auto_relief_inning=7,record=False)
            reproduced=g.run()['failure']
            if canonical(reproduced)!=canonical(f):raise ValueError(f'Old failure {f["seed"]} did not reproduce exactly')
            frame=frame_from_dict(f['frame']);pre=frame.outs*8+frame.base_mask
            r={'seed':f['seed'],'old_game_id':f['game_id'],'old_reason':f['reason'],
               'old_exact_reproduced':True,'pre_state':pre,'old_outcome':f['sampled_outcome']}
            if f['sampled_outcome']=='runner_only_end':
                r['interpretation']='old sampled label has no normal-half route; new population is not a repair of this forced outcome'
                r['new_terminal_estimate']=model.terminal['states'][str(pre)]
                r['forced_old_outcome_status']='still_no_empirical_route'
                r['source_windows']=[dict(w) for w in db.execute('select season,game_id,first_source_row,last_source_row,transition_observed,completed_pa,censor_reason,post_state,runs from windows where pre_state=? and outcome=? order by season,first_source_row',(pre,'runner_only_end'))]
            else:
                c=f['context'];attempt=frame_from_dict(c.get('attempted_frame',f['frame']))
                if c.get('attempted_action'):
                    mapping={'B':frame.batter,**{str(j):t.player_id for j,t in enumerate(frame.bases,1) if t}}
                    p=bind(c['attempted_action'],mapping,'empirical',c['route_ref'])
                    r['original_source']=c.get('original_source');r['action']=c['attempted_action']
                else:p=assumed_play(attempt,f['sampled_outcome'])
                try:
                    fixed=apply_play(attempt,p)
                    r.update(same_action_status='resolved',evidence=timing_evidence(attempt,p),
                             new_score=list(fixed.transition.after.score),new_out_ids=list(fixed.transition.out_ids))
                except ValueError as exc:r.update(same_action_status='retained_stop',new_reason=str(exc),category=[3,4])
            new=Game(model,teams,seed=f['seed'],allow_assumptions=True,auto_relief_inning=7,record=False).run()
            r.update(new_full_game_status=new['status'],new_full_game_reason=new['reason'],new_score=new['score'])
            results.append(r)
            if (i+1)%25==0:print(f'Old failure reproduction {i+1}/155',flush=True)
    finally:db.close()
    report={'old_exact_reproduced':len(results),'old_causes':dict(Counter(r['old_reason'] for r in results)),
        'same_walkoff_action_resolved':sum(r.get('same_action_status')=='resolved' for r in results),
        'same_walkoff_action_retained':sum(r.get('same_action_status')=='retained_stop' for r in results),
        'old_terminal_draws_population_redefined':sum(r['old_outcome']=='runner_only_end' for r in results),
        'new_full_seed_games':dict(Counter(r['new_full_game_status'] for r in results)),
        'comparison_limit':'New model probabilities/route prior differ; same seed full games need not encounter the old action. Same-action results are reported separately.',
        'cases':results}
    write_json(Path(output)/'old155_comparison.json',report)
    return report
