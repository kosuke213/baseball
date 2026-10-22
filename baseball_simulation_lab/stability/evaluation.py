"""Raw-cohort diagnostics, 2024 selection vs known 2025 reference kept distinct."""
from collections import Counter
from contextlib import closing
import json,math,sqlite3
from pathlib import Path

from data_collection.fetch import write_json
from ..fullgame.sources import input_paths
from ..calibrated.identity import example_frame
from .probability import legal_terminal


def evaluate(model,output):
    _,path,_,_=input_paths();counts={};outcome_counts={}
    with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as db:
        for y,s,n,k in db.execute('SELECT season,pre_state,count(*),sum(completed_pa=0) FROM windows WHERE completed_pa=1 OR (transition_observed=1 AND outcome="runner_only_end") GROUP BY 1,2'):
            counts[y,s]=(n,k)
        outcome_counts={str(year):{o:n for o,n in db.execute('SELECT outcome,count(*) FROM windows WHERE season=? AND completed_pa=1 GROUP BY outcome',(year,))} for year in (2023,2024,2025)}
    def score(train_years,target,alpha):
        n_total=0;loss=0.;brier=0.;zero=0;illegal_mass=0.;rows=[]
        for pre in range(24):
            n=sum(counts[y,pre][0] for y in train_years);k=sum(counts[y,pre][1] for y in train_years)
            q=((k+alpha)/(n+2*alpha) if alpha else k/n) if legal_terminal(pre) else 0
            nt,kt=counts[target,pre];n_total+=nt;brier+=kt*(1-q)**2+(nt-kt)*q*q
            if kt and q==0:zero+=kt
            elif kt:loss-=kt*math.log(q)
            loss-=(nt-kt)*math.log1p(-q)
            if not legal_terminal(pre):illegal_mass+=q
            rows.append({'pre_state':pre,'legal':legal_terminal(pre),'n_train':n,'k_train':k,'p':q,'n_target':nt,'k_target':kt})
        return {'n':n_total,'binary_log_loss':None if zero else loss/n_total,'infinite_log_loss':bool(zero),
                'zero_probability_observations':zero,'brier':brier/n_total,'structurally_impossible_mass':illegal_mass,'states':rows}
    candidates={str(a):score([2023],2024,a) for a in (0,.1,.5,1)}
    reference={str(a):score([2023,2024],2025,a) for a in (0,.1,.5,1)}
    changes=[];support=[]
    for pre in range(24):
        frame=example_frame(pre);old=model.previous.predict_step(frame);new=model.predict_step(frame)
        names=set(old)|set(new);changes.append({'pre_state':pre,'total_variation':sum(abs(old.get(n,0)-new.get(n,0)) for n in names)/2,
            'retired_placeholder_mass':old['other_pa'],'old_terminal':old['runner_only_end'],'new_terminal':new['runner_only_end']})
        for row in model.support_report(frame,allow_assumptions=True):
            supported=row['empirical_n']>0 or row['declared_assumption'] or row['generated_terminal_available']
            if row['probability']>0 and not supported:raise ValueError('Positive generative probability lacks executable support')
            support.append({'pre_state':pre,**row,'supported':supported})
    write_json(Path(output)/'probability_evaluation.json',{'cohort':'complete PA windows + observed ordinary no-PA half ends; non-PA game-end censoring excluded',
        'candidates_2023_to_2024':candidates,'known_reference_2023_2024_to_2025':reference,
        'predictive_selection':'MLE retained: no log-loss improvement on 2024; Jeffreys is opt-in generative coverage, not an accuracy upgrade',
        'posterior_support_policy':'Jeffreys Beta(.5,.5) on legal states; structural mask first; legal generated retirements supplied',
        'pa_taxonomy':{'other_pa_training_count':sum(outcome_counts[str(y)].get('other_pa',0) for y in (2023,2024)),
                       'observed_counts_by_year':outcome_counts,'policy':'retire nonsemantic placeholder; unknown future labels quarantined, never mapped to out'},
        'distribution_changes':changes,'support_grid':support,
        'limits':['2025 known reference, never training or untouched test','Brier tiny improvement does not establish predictive superiority',
                  'generator coverage is distinct from observed empirical support','structural no-PA support excludes introducing a new batter-runner']})
