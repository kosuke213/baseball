"""Design-weighted descriptions and coarse, joint empirical calibration.

This is a sample of Wikipedia-listed NPB members, not an official census.
Annual memberships and retrieval-time physical measurements are distinct.
"""
from collections import defaultdict, Counter
from datetime import date
from pathlib import Path
import csv, json, math, statistics, hashlib
import numpy as np
from data_collection.npb_profiles import ROOT, dump, new_stage_path
from ..careers.domain import age_on

MODEL_VERSION = 'npb-wikipedia-sample-physical-1'
HANDS = ('RR','RL','RS','LL','LR','LS')

def weighted_quantile(values, weights, q):
    pairs=sorted(zip(values,weights)); total=sum(weights); target=total*q; run=0.
    for value, weight in pairs:
        run+=weight
        if run>=target: return float(value)
    return float(pairs[-1][0])

def describe(values, weights=None):
    if not values:return {'n':0,'missing':0}
    weights=weights or [1.]*len(values); total=sum(weights); mean=sum(v*w for v,w in zip(values,weights))/total
    # Population dispersion of this weighted sample; not a finite-sample CI.
    return {'n':len(values),'weight_sum':total,'effective_n':total**2/sum(w*w for w in weights),
            'mean':mean,'median':weighted_quantile(values,weights,.5),
            'sd_population':math.sqrt(sum(w*(v-mean)**2 for v,w in zip(values,weights))/total),
            'min':min(values),'max':max(values),
            **{'p'+str(q):weighted_quantile(values,weights,q/100) for q in (5,25,75,95)}}

def correlation(x,y,w):
    if len(x)<2:return None
    mx=sum(a*b for a,b in zip(x,w))/sum(w);my=sum(a*b for a,b in zip(y,w))/sum(w)
    xx=sum(c*(a-mx)**2 for a,c in zip(x,w));yy=sum(c*(b-my)**2 for b,c in zip(y,w))
    return sum(c*(a-mx)*(b-my) for a,b,c in zip(x,y,w))/math.sqrt(xx*yy) if xx*yy else None

def summary(rows):
    result={'rows':len(rows),'unique_people':len({r['identity'] for r in rows}),
            'estimated_population_weight':sum(r['weight'] for r in rows)}
    for field in ('height_cm','weight_kg','age'):
        selected=[r for r in rows if r.get(field) is not None]
        result[field]={**describe([r[field] for r in selected],[r['weight'] for r in selected]),'missing':len(rows)-len(selected)}
    pairs=[r for r in rows if r.get('height_cm') is not None and r.get('weight_kg') is not None]
    w=[r['weight'] for r in pairs];x=[r['height_cm'] for r in pairs];y=[r['weight_kg'] for r in pairs]
    result['pearson_height_weight']=correlation(x,y,w)
    if len(pairs)>2:
        def weighted_ranks(values):
            mass=Counter()
            for v,weight in zip(values,w):mass[v]+=weight
            ranks={};acc=0.
            for v,weight in sorted(mass.items()):ranks[v]=acc+weight/2;acc+=weight
            return [ranks[v] for v in values]
        result['spearman_height_weight']=correlation(weighted_ranks(x),weighted_ranks(y),w)
        a=np.array([[1.,r['age'] or 0] for r in pairs]);sw=np.sqrt(w)
        bx=np.linalg.lstsq(a*sw[:,None],np.array(x)*sw,rcond=None)[0]
        by=np.linalg.lstsq(a*sw[:,None],np.array(y)*sw,rcond=None)[0]
        result['age_adjusted_pearson']=correlation((np.array(x)-a@bx).tolist(),(np.array(y)-a@by).tolist(),w)
    hands=Counter();unweighted=Counter()
    for r in rows:
        hand=(r.get('throws') or '?')+(r.get('bats') or '?'); hands[hand]+=r['weight'];unweighted[hand]+=1
    hands['unclassified']=sum(v for k,v in hands.items() if k not in HANDS)
    unweighted['unclassified']=sum(v for k,v in unweighted.items() if k not in HANDS)
    denominator=sum(hands[k] for k in (*HANDS,'unclassified'))
    result['handedness']={k:{'observed_rows':unweighted[k],'weighted_count':hands[k],
                            'weighted_share':hands[k]/denominator if denominator else None} for k in (*HANDS,'unclassified')}
    result['unclassified_hand_rows']=unweighted['unclassified']
    return result

def records(root):
    root=Path(root);members=json.loads((root/'memberships.json').read_text());profiles=json.loads((root/'profiles.json').read_text())
    # Article-link identity, not fuzzy matching on display names. Redirect aliases
    # verified among fetched profiles share canonical URL. Unresolved links stay separate.
    identity={t:p.get('canonical_url',p['source_url']) for t,p in profiles.items()}
    unique={}
    for m in members:
        ident=identity.get(m['title'],'article:'+m['title']);key=(ident,m['year'])
        r=unique.setdefault(key,{'identity':ident,'year':m['year'],'teams':set(),'registrations':set(),'positions':set(),'titles':set(),'membership_urls':set()})
        r['teams'].add(m['team']);r['registrations'].add(m['registration']);r['positions'].add(m['position']);r['titles'].add(m['title']);r['membership_urls'].add(m['source_url'])
    observed=[];frame=[];quarantine=[]
    for (ident,year),m in sorted(unique.items()):
        registration='primary' if 'primary' in m['registrations'] else 'development'
        position=next(iter(m['positions'])) if len(m['positions'])==1 else None
        base={'identity':ident,'year':year,'registration':registration,'position':position,
              'teams':sorted(m['teams']),'both_registrations':len(m['registrations'])>1,'membership_urls':sorted(m['membership_urls'])}
        frame.append(base)
        p=next((profiles[t] for t in sorted(m['titles']) if t in profiles),None)
        if not p:continue
        row={**base,**p,'weight':1/p['inclusion_probability']}
        row['age']=age_on(p['birth_date'],f'{year}-07-01') if p.get('birth_date') else None
        if not position:quarantine.append({'reason':'conflicting_position','row':row});continue
        if row['age'] is not None and not 16<=row['age']<=60:
            quarantine.append({'reason':'implausible_age_requires_review','row':row});continue
        # Keep all body extremes; parsing ranges are audit signals, not exclusions.
        observed.append(row)
    dump(root/'normalized_private.json',observed);dump(root/'quarantine_private.json',quarantine)
    return frame,observed,quarantine

def fit_group(rows, config):
    complete=[r for r in rows if all(r.get(k) is not None for k in ('height_cm','weight_kg','age'))]
    hands=Counter({k:0. for k in HANDS});body=Counter();months=Counter();days=Counter();ages=Counter()
    for r in rows:
        hand=(r.get('throws') or '?')+(r.get('bats') or '?')
        if hand in hands:hands[hand]+=r['weight']
        if r.get('birth_date'):
            d=date.fromisoformat(r['birth_date']);months[d.month]+=r['weight'];days[d.day]+=r['weight']
    hb=config['body_height_bin_cm'];wb=config['body_weight_bin_kg'];ab=config['body_age_bin_years']
    for r in complete:
        body[(math.floor(r['height_cm']/hb)*hb, math.floor(r['weight_kg']/wb)*wb, math.floor(r['age']/ab)*ab)]+=r['weight']
        ages[r['age']]+=r['weight']
    if not complete:return None
    # Repeated member-years are a composition target, not independent body
    # measurements. Normalize hand-prior counts to person-cluster effective n.
    clustered=Counter()
    for r in rows:
        if (r.get('throws') or '?')+(r.get('bats') or '?') in hands:clustered[r['identity']]+=r['weight']
    hand_total=sum(hands.values());effective_n=sum(clustered.values())**2/sum(v*v for v in clustered.values()) if clustered else 0.
    hands=Counter({k:v*effective_n/hand_total if hand_total else 0. for k,v in hands.items()})
    total=sum(r['weight'] for r in complete)
    height_bias=sum(r['weight']*(r['height_cm']-(math.floor(r['height_cm']/hb)*hb+hb/2)) for r in complete)/total
    weight_bias=sum(r['weight']*(r['weight_kg']-(math.floor(r['weight_kg']/wb)*wb+wb/2)) for r in complete)/total
    return {'rows':len(rows),'unique_people':len({r['identity'] for r in rows}),
            'complete_rows':len(complete),'complete_unique_people':len({r['identity'] for r in complete}),
            'hands':dict(hands),'hands_person_cluster_effective_n':effective_n,
            'body_cells':[{'height_lower':h,'weight_lower':w,'age_lower':a,'weight':v} for (h,w,a),v in sorted(body.items())],
            'height_bias':height_bias,'weight_bias':weight_bias,
            'age_min':min(ages),'age_max':max(ages),'months':dict(months),'days':dict(days),
            'citizenship_counts':dict(sum((Counter({r['citizenship_group']:r['weight']}) for r in rows),Counter()))}

def export(root=None, output=None):
    root=new_stage_path(root or ROOT/'data/research/stage11_5');output=new_stage_path(output or ROOT/'data_sources/stage11_5');output.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'data_sources/stage11_5/config.json').read_text());frame,rows,quarantine=records(root)
    primary=[r for r in rows if r['registration']=='primary'];development=[r for r in rows if r['registration']=='development']
    # Unique-player descriptors use latest listed year once; annual descriptors
    # count each member-year once. A promoted player is primary for that year.
    latest={}
    for r in rows:
        if r['identity'] not in latest or r['year']>latest[r['identity']]['year']:latest[r['identity']]=r
    by={}
    for name,key in [('year',lambda r:str(r['year'])),('position',lambda r:r['position']),
                     ('role',lambda r:'pitcher' if r['position']=='P' else 'batter'),
                     ('age_band',lambda r:str(r['age']//5*5) if r['age'] is not None else 'unknown'),
                     ('height_band',lambda r:str(int(r['height_cm']//5*5)) if r['height_cm'] is not None else 'unknown'),
                     ('citizenship',lambda r:r['citizenship_group'])]:
        groups=defaultdict(list)
        for r in primary:groups[key(r)].append(r)
        by[name]={k:summary(v) for k,v in sorted(groups.items())}
    coverage=json.loads((root/'coverage.json').read_text())
    coverage_rows=[]
    for c in coverage:
        for registration in ('primary','development'):
            target=[r for r in frame if r['year']==c['year'] and c['team'] in r['teams'] and r['registration']==registration]
            measured=[r for r in rows if r['year']==c['year'] and c['team'] in r['teams'] and r['registration']==registration]
            coverage_rows.append({**c,'registration':registration,'listed_player_years':len(target),'sampled_profile_rows':len(measured),
                                  'body_complete_rows':sum(all(r.get(k) is not None for k in ('height_cm','weight_kg')) for r in measured)})
    report={'scope':'Wikipedia-listed 2021–2025 season members, stratified profile sample observed at retrieval; not official NPB census',
            'primary_player_year_sample':summary(primary),'development_player_year_sample':summary(development),
            'unique_player_sample':summary(list(latest.values())),'strata':by,
            'listed_frame':{'player_years':len(frame),'unique_article_identities':len({r['identity'] for r in frame}),
              'multi_team_player_years':sum(len(r['teams'])>1 for r in frame),'both_registration_player_years':sum(r['both_registrations'] for r in frame)},
            'quarantined_rows':len(quarantine),'coverage':coverage_rows,
            'measurement_timing':'retrieval-time article body values; annual changes are not observed',
            'weights':'inverse probability of selection from independent fixed team/position/registration union strata; no nonresponse imputation',
            'new_entrants':{'status':'not_calibrated','reason':'first listed year is not verified first NPB entry'},
            'ability_effect':{'enabled':False,'reason':'body/outcome causal effect not established'},
            'platoon_effect':{'enabled':False,'reason':'roster handedness is not matchup outcome data'}}
    dump(output/'statistics.json',report)
    # Fit to 2021–2024 memberships; inspect 2025 separately, including an honest
    # disjoint-person slice. All body values were observed later: not temporal validation.
    train=[r for r in rows if r['year']<2025];groups={}
    for registration in ('primary','development'):
        base=[r for r in train if r['registration']==registration]
        for position in ('all','P','C','IF','OF'):
            pos=[r for r in base if position=='all' or r['position']==position]
            for citizenship in ('all','japan','non_japan','multiple','unknown'):
                selected=[r for r in pos if citizenship=='all' or r['citizenship_group']==citizenship]
                fit=fit_group(selected,config)
                if fit:groups[f'{registration}:{position}:{citizenship}']=fit
    fit_model={'version':MODEL_VERSION,'membership_fit_years':[2021,2022,2023,2024],
               'body_observation_timing':'retrieved article profile, not historical season measurement',
               'profile_population':'existing stock only; no automatic rookie reuse','config':config,'groups':groups,
               'position_weights':dict(Counter(r['position'] for r in frame if r['year']<2025 and r['registration']=='primary' and r['position'])),
               'ability_correction':False,'platoon_correction':False,'annual_weight_change':False}
    # Normalize integer histogram keys to their JSON string representation
    # before hashing, so loaded and in-memory parameters canonicalize equally.
    fit_model=json.loads(json.dumps(fit_model,ensure_ascii=False))
    fit_model['parameter_sha256']=hashlib.sha256(json.dumps(fit_model,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    dump(output/'parameters.json',fit_model)
    # Public CSVs contain aggregates only, not the source roster or person rows.
    csv_rows=[]
    for kind,groups in by.items():
        for group,stats in groups.items():
            for metric in ('height_cm','weight_kg','age'):
                csv_rows.append({'stratum_type':kind,'stratum':group,'metric':metric,**stats[metric]})
    write_csv(output/'body_statistics.csv',csv_rows)
    write_csv(output/'coverage.csv',coverage_rows)
    hand_rows=[]
    for kind,groups in {'all':{'all':summary(primary)},**by}.items():
        for group,stats in groups.items():
            for combo,v in stats['handedness'].items():hand_rows.append({'stratum_type':kind,'stratum':group,'throws_bats':combo,**v})
    write_csv(output/'handedness.csv',hand_rows)
    raw_manifest=[]
    for p in sorted((root/'raw').glob('*.json')):
        m=json.loads(p.read_text());raw_manifest.append(m)
    dump(output/'sources.json',{'license':'Wikipedia contributors, CC BY-SA 4.0; aggregate transformations by this project',
          'raw_html_and_real_player_rows_redistributed':False,'requests':raw_manifest,
          'all_aggregate_provenance':'statistics/parameters use sampled profile URLs and corresponding roster article URLs listed here; see private memberships/profile linkage for per-row joins'})
    dump(root/'analysis_report.json',{'train_people':len({r['identity'] for r in train}),'observed_rows':len(rows)})
    return report,fit_model

def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)

if __name__=='__main__':export()
