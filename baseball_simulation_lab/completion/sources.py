"""Frozen inputs, explicit end classifications and audit of all 670 old gaps."""
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from data_collection import adapters
from data_collection.fetch import write_json
from ..calibrated.identity import recover, example_frame
from ..calibrated.rules import canonical
from ..fullgame.sources import input_paths, sha, enrich, recover_with_evidence
from .model import bind, GameModel
from .paths import new_output
from .rules import apply_play

ROOT = Path(__file__).resolve().parents[2]


def end_kind(w):
    if not w['transition_observed']:
        return 'walkoff_game_end' if w['censor_reason'] == 'walkoff' else 'special_censored_end'
    return 'pa_complete' if w['completed_pa'] else 'half_end_no_pa' if w['post_state'] == 24 else 'unknown'


def recover_multi_force(row):
    try:
        return recover_with_evidence(row)
    except ValueError as exc:
        match = re.fullmatch(r'[1-9]+\(([123])\)[1-9]+\(([123])\)/GDP(?:/[^.]*)?\.B-1', row['event'])
        if (not match or match[1] == match[2] or row['outs_pre'] != '1' or row['outs_post'] != '3'
                or row['runs'] != '0' or row['pa'] != '1'):
            raise exc
        retired = {row['br' + i + '_pre'] for i in match.groups()}
        people = {row['batter'], *(row[f'br{i}_pre'] for i in (1,2,3) if row[f'br{i}_pre'])}
        survivors = people - retired
        known = {row[f'lob_id{i}'] for i in (1,2,3) if row[f'lob_id{i}']}
        if '' in retired or not known <= survivors or len(survivors) > 3:
            raise exc
        fixed = dict(row)
        for i, pid in enumerate(sorted(survivors) + [''] * (3-len(survivors)), 1):
            fixed[f'lob_id{i}'] = pid
        a = recover(fixed)
        a['recovery_note'] = 'two_explicit_retirements_identify_omitted_LOB'
        return a


def build(output, *, progress=print):
    output = new_output(output)
    if output.exists(): raise FileExistsError('Stage 9 build never overwrites a directory')
    output.mkdir(parents=True)
    s5, s6, raw, config = input_paths()
    if sha(s5) != config['stage5_database_sha256'] or sha(s6) != config['stage6_observations_sha256']:
        raise ValueError('Frozen input database changed')
    old_path = ROOT / 'data_sources/stage8/routes.json.gz'
    old = json.loads(gzip.decompress(old_path.read_bytes()))
    routes = json.loads(canonical(old)); routes['version'] = 'scoring-routes-2'
    audit=[]; ends=Counter(); risk={str(i): {'pa_complete':0,'half_end_no_pa':0} for i in range(24)}
    with closing(sqlite3.connect('file:'+str(s6)+'?mode=ro',uri=True)) as db, closing(sqlite3.connect('file:'+str(s5)+'?mode=ro',uri=True)) as db5:
        db.row_factory=sqlite3.Row
        for year in (2023,2024,2025):
            progress(f'Stage 9 original end/substitution audit {year}')
            meta=json.loads(db5.execute('select metadata_json from artifacts where artifact_id=?',(f'retro_plays_{year}',)).fetchone()[0])
            blob=raw/'blobs'/meta['sha256']
            if sha(blob)!=meta['sha256']: raise ValueError('Raw checksum mismatch')
            iterator=iter(adapters.zipped_csv(blob.read_bytes(),f'{year}plays.csv')); current=next(iterator,None)
            for w in db.execute('select * from windows where season=? order by first_source_row',(year,)):
                kind=end_kind(w); ends[f'{year}:{kind}']+=1
                if year in (2023,2024) and (w['completed_pa'] or kind=='half_end_no_pa'):
                    risk[str(w['pre_state'])]['pa_complete' if w['completed_pa'] else 'half_end_no_pa']+=1
                while current and current[0]<w['first_source_row']: current=next(iterator,None)
                rows=[]
                while current and current[0]<=w['last_source_row']:
                    rows.append(current);current=next(iterator,None)
                plays=[(n,r) for n,r in rows if r['event']!='NP']
                first=plays[0][1]; roles={first['batter']:'B',**{first[f'br{i}_pre']:str(i) for i in (1,2,3) if first[f'br{i}_pre']}}
                reason=None
                if w['actor_changed']: reason='actor_changed_requires_lineup_parser'
                elif not w['transition_observed']: reason='censored_end_requires_game_context_not_regular_template'
                else:
                    try:
                        for _,r in plays: enrich(r,recover_with_evidence(r),roles)
                    except (ValueError,KeyError) as exc: reason=str(exc)
                if reason is None: continue
                record={'season':year,'game_id':w['game_id'],'first_source_row':w['first_source_row'],
                        'last_source_row':w['last_source_row'],'artifact_sha256':meta['sha256'],
                        'end_kind':kind,'old_reason':reason,'new_status':'retained_exclusion',
                        'category':[2] if w['actor_changed'] or 'participant' in reason else [2,4] if not w['transition_observed'] else [2],
                        'raw_rows':[{'source_row':n,'row':r} for n,r in rows]}
                if 'Unique missing participant' in reason:
                    actions=[enrich(r,recover_multi_force(r),roles) for _,r in plays]
                    f=example_frame(w['pre_state']); mapping={'B':f.batter,**{str(i):r.player_id for i,r in enumerate(f.bases,1) if r}}
                    for a in actions:f=apply_play(f,bind(a,mapping,'empirical','multi-force-audit')).transition.after
                    if f.outs!=3 or f.score[0]!=w['runs']:raise ValueError('Force repair disagrees with source')
                    record.update(new_status='resolved_explicit_force_LOB',category=[1,2],actions=actions)
                    if year in (2023,2024):
                        key=f'{w["pre_state"]}:{w["outcome"]}:{w["extra_innings"]}'; digest=hashlib.sha256(canonical(actions).encode()).hexdigest()
                        group=routes['groups'].setdefault(key,[])
                        group.append({'sha256':digest,'n':1,'actions':actions});group.sort(key=lambda x:x['sha256'])
                        routes['sources'][digest]={'artifact_id':f'retro_plays_{year}','sha256':meta['sha256'],'game_id':w['game_id'],'first_source_row':w['first_source_row'],'last_source_row':w['last_source_row']}
                # Actual ID/count changes are retained, not recast as missing raw data.
                record['actor_sequence']=[{'source_row':n,'event':r['event'],'batter':r['batter'],'pitcher':r['pitcher'],
                    'runners':[r[f'br{i}_pre'] for i in (1,2,3)],'balls':r.get('balls'),'strikes':r.get('strikes')} for n,r in rows]
                audit.append(record)
    if len(audit)!=670:raise ValueError(f'Expected all 670 old gaps, got {len(audit)}')
    for counts in risk.values():
        n=counts['pa_complete']+counts['half_end_no_pa']; k=counts['half_end_no_pa']
        p=k/n if n else 0
        # Wilson interval documents sampling uncertainty, including zero counts.
        z=1.959963984540054; center=(p+z*z/(2*n))/(1+z*z/n); half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
        counts.update(exposure=n,p_half_end_no_pa=p,wilson_95=[max(0,center-half),min(1,center+half)])
    terminal={'version':'terminal-risk-1','training_seasons':[2023,2024],'states':risk,
              'estimator':'state-stratified binomial MLE; conditional PA probabilities remain frozen Stage 7',
              'denominator':'completed PA windows (including recorded walkoff PAs) + observed normal no-PA half endings',
              'exclusions':'no-PA game-ending and shortened windows are censored, not normal half endings',
              'limits':['zero empirical hazard is not proof of impossibility; intervals retain positive upper bounds',
                        'no cross-state pseudocount for terminal events; sparse identities cannot be fabricated',
                        'standalone runner-only walkoff hazard not separately estimated; incomplete game-context model']}
    write_json(output/'terminal_model.json',terminal)
    (output/'routes.json.gz').write_bytes(gzip.compress(canonical(routes).encode(),mtime=0))
    write_json(output/'source_audit.json',{'end_counts':dict(ends),'old_gaps':len(audit),'resolved_gaps':2,'remaining_gaps':668,
        'details':audit,'new_training_routes':1,'new_2025_training_routes':0,'new_data_requests':0,
        'input_sha256':{'stage5':sha(s5),'stage6':sha(s6),'stage8_routes':sha(old_path)}})
    from ..calibrated.api import CalibratedModel
    model=GameModel(CalibratedModel.load(ROOT/'data_sources/stage7'),routes,terminal)
    write_json(output/'model_manifest.json',{'model_version':model.version,'files':{
        name:sha(output/name) for name in ('routes.json.gz','terminal_model.json')}})
    return routes,terminal
