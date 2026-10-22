"""Paired old failures: deterministic repairs and generated counterfactuals differ."""
from collections import Counter
from pathlib import Path
import json,random

from data_collection.fetch import write_json
from ..calibrated.rules import frame_from_dict,canonical
from ..completion.engine import Game as PreviousGame,fictional_team
from ..completion.model import bind
from .timeline import generate
from .rules import realize,apply_play


def reproduce(model,output,root):
    cases=json.loads((root/'data_sources/stage9/failures.json').read_text())['failures'];rows=[]
    for index,c in enumerate(cases):
        old=PreviousGame(model.previous,(fictional_team('LAB_A'),fictional_team('LAB_H')),
            seed=c['seed'],allow_assumptions=True,auto_relief_inning=7,record=False)
        assert canonical(old.run()['failure'])==canonical(c)
        record={'seed':c['seed'],'old_exact_reproduced':True,'old_reason':c['reason'],
                'old_frame':c['frame'],'batter_id':c['batter'],'pitcher_id':c['pitcher'],
                'sampled_outcome':c['sampled_outcome'],'original_context':c['context']}
        if c['sampled_outcome']=='other_pa':
            record.update(same_play_deterministic_repair=False,generative_resolution='placeholder_removed_from_outcome_alphabet',
                interpretation='no actual other_pa rows in training/reference; unknown future ingestion is quarantined, not arbitrarily mapped')
        else:
            context=c['context'];initial=frame_from_dict(c['frame']);frame=frame_from_dict(context['attempted_frame'])
            mapping={'B':initial.batter,**{str(i):r.player_id for i,r in enumerate(initial.bases,1) if r}}
            p=bind(context['attempted_action'],mapping,'empirical',context['route_ref'])
            try:
                apply_play(frame,p);record['same_play_deterministic_repair']=True
            except ValueError as exc:record.update(same_play_deterministic_repair=False,unresolved_original_reason=str(exc))
            # One draw, fixed seed; no retry and no outcome replacement.
            rng=random.Random(1000000+index)
            timeline=generate(frame,p,rng);generated=realize(frame,p,timeline);applied=apply_play(frame,generated)
            record.update(generative_resolution='legal_generated_order',generated_timeline=timeline.to_dict(),
                generated_score=list(applied.transition.after.score),generated_out_ids=list(applied.transition.out_ids),
                cancelled_out_ids=list(applied.cancelled_out_ids),generated_rbi_ids=applied.credit.rbi_ids,
                actual_result=applied.actual_result,
                missing_information=['original timing of home touch relative to base/catch/tag outs',
                                     'whether a planned out happened after the hypothetical game-ending run'],
                interpretation='selected outcome and endpoints retained; missing chronology is generated, not reconstructed as an observed fact')
        rows.append(record)
    report={'old_failures_exact_reproduced':len(rows),'walkoff_cases':61,'other_pa_cases':1,
        'same_play_deterministic_repairs':sum(r['same_play_deterministic_repair'] for r in rows),
        'generated_future_paths_covered':sum(r.get('generative_resolution')=='legal_generated_order' for r in rows),
        'original_chronology_still_unknown':61,'resampled_outcomes':0,'cases':rows}
    write_json(Path(output)/'old62_comparison.json',report)
    return report


def audit_routes(model,output):
    from dataclasses import replace
    from ..calibrated.identity import example_frame
    counts=Counter();failures=[]
    for key,rows in model.routes['groups'].items():
        pre=int(key.split(':')[0])
        for row in rows:
            for situation in ('ordinary','walkoff_possible'):
                frame=example_frame(pre)
                if situation=='walkoff_possible':
                    frame=replace(frame,inning=9,half=1,lineups=frame.lineups[::-1],pitchers=frame.pitchers[::-1])
                mapping={'B':frame.batter,**{str(i):r.player_id for i,r in enumerate(frame.bases,1) if r}}
                rng=random.Random(904)
                try:
                    for action in row['actions']:
                        if frame.finished:break
                        p=bind(action,mapping,'empirical',row['sha256'])
                        frame=apply_play(frame,realize(frame,p,generate(frame,p,rng))).transition.after
                    counts[situation+':supported']+=1
                except ValueError as exc:
                    failures.append({'key':key,'sha256':row['sha256'],'situation':situation,'reason':str(exc),'actions':row['actions']})
    report={'grouped_route_tests':sum(counts.values())+len(failures),'counts':dict(counts),'failed':len(failures),
            'failures':failures,'seed':904,'limit':'one generated linear extension per route/context; not every possible chronology'}
    write_json(Path(output)/'route_support_audit.json',report)
    if failures:raise ValueError(f'Route/time compatibility failures: {len(failures)}')
    return report


def original_rows(output,root):
    from contextlib import closing
    import sqlite3
    from data_collection import adapters
    from ..fullgame.sources import input_paths,sha
    cases=json.loads((root/'data_sources/stage9/failures.json').read_text())['failures']
    wanted={}
    for c in cases:
        source=(c['context'] or {}).get('original_source')
        if source:
            year=int(source['artifact_id'][-4:])
            for n in range(source['first_source_row'],source['last_source_row']+1):wanted.setdefault(year,set()).add(n)
    wanted.setdefault(2025,set()).update((123552,123553))
    s5,_,raw,_=input_paths();artifacts=[];selected=[]
    with closing(sqlite3.connect('file:'+str(s5)+'?mode=ro',uri=True)) as db:
        for year in sorted(wanted):
            meta=json.loads(db.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?',(f'retro_plays_{year}',)).fetchone()[0])
            blob=raw/'blobs'/meta['sha256']
            if sha(blob)!=meta['sha256']:raise ValueError('Source original checksum mismatch')
            artifacts.append(meta)
            for n,row in adapters.zipped_csv(blob.read_bytes(),f'{year}plays.csv'):
                if n in wanted[year]:selected.append({'season':year,'source_row':n,'raw':row,'artifact_sha256':meta['sha256']})
    if len(selected)!=sum(len(v) for v in wanted.values()):raise ValueError('Requested raw source rows missing')
    write_json(Path(output)/'source_case_review.json',{'artifacts':artifacts,'selected_rows':selected,
        'new_data_requests':0,'limits':'original recorded endpoints/IDs; missing timing is never replaced with generated facts'})
