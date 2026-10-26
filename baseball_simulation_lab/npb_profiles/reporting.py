"""Shareable aggregate figures and source/assumption documentation."""
from pathlib import Path
from collections import defaultdict,Counter
import json,hashlib,math
import numpy as np
from data_collection.npb_profiles import ROOT,dump,new_stage_path
from .analysis import records,write_csv

def figures(root=None,output=None):
    import os
    root=new_stage_path(root or ROOT/'data/research/stage11_5')
    os.environ.setdefault('MPLCONFIGDIR',str(root/'plot-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=new_stage_path(root or ROOT/'data/research/stage11_5');out=new_stage_path(output or ROOT/'docs/data-stage11-5/figures');out.mkdir(parents=True,exist_ok=True)
    _,rows,_=records(root);primary=[r for r in rows if r['registration']=='primary']
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for position in ('P','C','IF','OF'):
        group=[r for r in primary if r['position']==position]
        for ax,field,label,width in zip(axes,('height_cm','weight_kg'),('Listed height (cm)','Listed weight (kg)'),(5,10)):
            values=[r[field] for r in group if r[field] is not None];weights=[r['weight'] for r in group if r[field] is not None]
            if values:ax.hist(values,bins=np.arange(math.floor(min(values)/width)*width,math.ceil(max(values)/width)*width+width,width),weights=weights,density=True,histtype='step',linewidth=1.8,label=position)
            ax.set_xlabel(label);ax.set_ylabel('Weighted density');ax.legend()
    fig.suptitle('Wikipedia-listed NPB membership sample (2021–2025); body profiles observed at retrieval')
    fig.tight_layout();fig.savefig(out/'body_histograms.svg');fig.savefig(out/'body_histograms.png',dpi=160);plt.close(fig)
    people={r['identity']:r for r in sorted(primary,key=lambda x:x['year'])}
    fig,ax=plt.subplots(figsize=(7,5))
    for position in ('P','C','IF','OF'):
        group=[r for r in people.values() if r['position']==position and r['height_cm'] is not None and r['weight_kg'] is not None]
        ax.scatter([r['height_cm'] for r in group],[r['weight_kg'] for r in group],s=20,alpha=.6,label=position)
    ax.set(xlabel='Listed height (cm)',ylabel='Listed weight (kg)',title='Sampled distinct players; no annual body-change claim');ax.legend();fig.tight_layout()
    fig.savefig(out/'height_weight.svg');fig.savefig(out/'height_weight.png',dpi=160);plt.close(fig)

def provenance(root=None,output=None):
    root=new_stage_path(root or ROOT/'data/research/stage11_5');output=new_stage_path(output or ROOT/'data_sources/stage11_5')
    _,rows,_=records(root);primary=[r for r in rows if r['registration']=='primary'];groups={'primary_player_year_sample':primary,
        'development_player_year_sample':[r for r in rows if r['registration']=='development']}
    latest={r['identity']:r for r in sorted(rows,key=lambda x:x['year'])};groups['unique_player_sample']=list(latest.values())
    for kind,key in [('year',lambda r:str(r['year'])),('position',lambda r:r['position']),
                     ('role',lambda r:'pitcher' if r['position']=='P' else 'batter'),
                     ('citizenship',lambda r:r['citizenship_group']),('age_band',lambda r:str(r['age']//5*5) if r['age'] is not None else 'unknown'),
                     ('height_band',lambda r:str(int(r['height_cm']//5*5)) if r['height_cm'] is not None else 'unknown')]:
        values=defaultdict(list)
        for r in primary:values[key(r)].append(r)
        for k,v in values.items():groups['strata.'+kind+'.'+k]=v
    mapping={name:{'profile_urls':sorted({r['source_url'] for r in group}),
                    'membership_urls':sorted({u for r in group for u in r['membership_urls']}),
                    'membership_years':sorted({r['year'] for r in group}),
                    'method':'inverse selection-probability weighted sampled listed player-years; complete cases per variable; latest listed year once for unique-player view',
                    'retrieval_metadata':'sources.json URL -> retrieved_at / sha256; original HTML private'} for name,group in groups.items()}
    parameters=json.loads((output/'parameters.json').read_text())
    for key in parameters['groups']:
        registration,position,citizenship=key.split(':')
        selected=[r for r in rows if r['year']<2025 and r['registration']==registration and (position=='all' or r['position']==position)
                  and (citizenship=='all' or r['citizenship_group']==citizenship)]
        mapping['parameters.groups.'+key]={'profile_urls':sorted({r['source_url'] for r in selected}),
            'membership_urls':sorted({u for r in selected for u in r['membership_urls']}),
            'membership_years':sorted({r['year'] for r in selected}),
            'method':'design-weighted joint body bins; hand priors additionally reference parent position/all groups in this map',
            'retrieval_metadata':'sources.json URL -> retrieved_at / sha256'}
    dump(output/'aggregate_provenance.json',mapping)
    # Audit original infoboxs at the empirical extremes. No value is removed on
    # the basis of size. No claim of fresh official measurements is made.
    audits=[]
    allp=json.loads((root/'profiles.json').read_text())
    for field in ('height_cm','weight_kg'):
        available=[p for p in allp.values() if p[field] is not None]
        for direction,fn in [('minimum',min),('maximum',max)]:
            p=fn(available,key=lambda x:x[field]);audits.append({'field':field,'extreme':direction,'value':p[field],
                'source_url':p['source_url'],'revision_link':p['article_revision_link'],
                'decision':'retained; value parsed from source infobox units, not a verified annual physical measurement'})
    dump(output/'quality.json',{'extreme_value_audits':audits,'extremes_mechanically_deleted':0,
       'missing_profiles_not_replaced':True,'nationality_not_inferred_from_name_or_birthplace':True,
       'unknown_hands_not_converted_to_R':True,'registration_definition':'separate Wikipedia season navbox sections; primary wins in a promotion year; not a reconstructed NPB official transaction ledger',
       'multiple_positions':'preserve membership labels; conflicting position in a player-year quarantined; private profile also retains full current position string',
       'measurement_differences':'Wikipedia may quote overseas/rounded dimensions and later weights; no official same-date cross-source concordance dataset was acquired'})
