"""Exploratory fit-data comparison; same frozen seeds, not independent testing."""
from pathlib import Path
from collections import Counter
import sys,copy,json,hashlib,random
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from baseball_simulation_lab.npb_profiles.analysis import records,fit_group,summary
from baseball_simulation_lab.npb_profiles.model import Distribution
from data_collection.npb_profiles import dump

root=ROOT/'data/research/stage11_5';output=ROOT/'data_sources/stage11_5'
_,rows,_=records(root);train=[r for r in rows if r['year']<2025]
base=json.loads((output/'parameters.json').read_text())
primary=[r for r in train if r['registration']=='primary'];mass=Counter()
for r in primary:mass[r['position']]+=r['weight']
target=summary([{**r,'weight':r['weight']*base['position_weights'][r['position']]/mass[r['position']]} for r in primary])
results=[];candidates=[(5,10),(2.5,5)]
for hb,wb in candidates:
    p=copy.deepcopy(base);p['config']['body_height_bin_cm']=hb;p['config']['body_weight_bin_kg']=wb;p.pop('parameter_sha256')
    for key in list(p['groups']):
        registration,position,citizenship=key.split(':')
        selected=[r for r in train if r['registration']==registration and (position=='all' or r['position']==position) and (citizenship=='all' or r['citizenship_group']==citizenship)]
        p['groups'][key]=fit_group(selected,p['config'])
    p=json.loads(json.dumps(p));p['parameter_sha256']=hashlib.sha256(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    model=Distribution(p);draws=[]
    for seed in p['config']['generation_seeds']:
        rng=random.Random(seed)
        for i in range(p['config']['players_per_seed']):
            d=model.sample(rng);draws.append({**d,'position':d['source_position'],'identity':str(seed)+':'+str(i),'weight':1.})
    actual=summary(draws)
    results.append({'height_bin_cm':hb,'weight_bin_kg':wb,'n':len(draws),'height_mean_cm':actual['height_cm']['mean'],
        'weight_mean_kg':actual['weight_kg']['mean'],'height_sd':actual['height_cm']['sd_population'],'weight_sd':actual['weight_kg']['sd_population'],
        'pearson':actual['pearson_height_weight'],'reference_pearson':target['pearson_height_weight'],
        'absolute_correlation_error':abs(actual['pearson_height_weight']-target['pearson_height_weight']),
        'body_cells':sum(len(g['body_cells']) for g in p['groups'].values())})
winner=min(results,key=lambda r:r['absolute_correlation_error'])
dump(output/'method_comparison.json',{'candidate_results':results,'chosen':winner,'seeds_unchanged':base['config']['generation_seeds'],
    'status':'exploratory calibration-data comparison, not independent validation','selection':'smaller absolute height/weight correlation distortion; all seeds retained',
    'tradeoff':'finer cells retain correlation better but have smaller cell support and greater overfit risk; no source person rows published'})
config=json.loads((output/'config.json').read_text());config['body_height_bin_cm']=winner['height_bin_cm'];config['body_weight_bin_kg']=winner['weight_bin_kg']
dump(output/'config.json',config)
print(json.dumps(results,ensure_ascii=False,indent=2))
