"""Atomic, immutable Stage 10 experiment with mandatory scale/league gates."""
import hashlib,json,os,platform,shutil,sqlite3,uuid,zipfile
from pathlib import Path

from data_collection.fetch import write_json
from ..calibrated.rules import canonical
from ..completion.pipeline import code_files,code_sha,lock,verify_snapshot
from ..fullgame.sources import input_paths,sha
from ..fullgame.league import schedule,league_gate
from .paths import ROOT,new_output


def run(config_path=None,output=None):
    from .model import GameModel
    from .probability import fit
    from .audit import reproduce,audit_routes,original_rows
    from .evaluation import evaluate
    from .validation import run_validation
    from .season import run_league
    config_path=Path(config_path or ROOT/'data_sources/stage10/config.json')
    config=json.loads(config_path.read_text());output=new_output(output or ROOT/'data/research/stage10');output.mkdir(parents=True,exist_ok=True)
    s5,s6,_,old_config=input_paths()
    pinned={'stage5':sha(s5),'stage6':sha(s6)}
    if pinned['stage5']!=old_config['stage5_database_sha256'] or pinned['stage6']!=old_config['stage6_observations_sha256']:
        raise ValueError('Frozen source databases changed')
    prior_paths=[ROOT/'data_sources/stage9'/n for n in ('routes.json.gz','terminal_model.json','model_manifest.json','failures.json')]
    fingerprint={'code_sha256':code_sha(),'config':config,'frozen_database_sha256':pinned,
        'stage9_inputs':{p.name:sha(p) for p in prior_paths},
        'runtime':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform()}}
    key=hashlib.sha256(canonical(fingerprint).encode()).hexdigest()[:24]
    snapshots=output/'snapshots';snapshots.mkdir(exist_ok=True);dest=snapshots/key
    with lock(output/'build.lock'):
        if dest.exists():verify_snapshot(dest);print('Reusing Stage 10 snapshot '+key,flush=True);return dest
        work=snapshots/(key+'.'+uuid.uuid4().hex[:8]+'.building');work.mkdir()
        try:
            parent=json.loads((ROOT/'data_sources/stage9/terminal_model.json').read_text())
            model_dir=work/'model';model_dir.mkdir()
            support=fit(parent['states']);write_json(model_dir/'support_model.json',support)
            # Parent inputs are immutable and already checksum-verified by the loader.
            from ..completion.model import GameModel as ParentModel
            previous=ParentModel.load(ROOT/'data_sources/stage7',prior_paths[0],prior_paths[1])
            write_json(model_dir/'support_manifest.json',{'format':'stability-model-inputs-1','support_sha256':sha(model_dir/'support_model.json'),
                'parent_stage9_model_version':previous.version})
            model=GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9',model_dir/'support_model.json',config['probability_policy'])
            audits=work/'audits';audits.mkdir()
            reproduce(model,audits,ROOT);print('62 old failures reproduced',flush=True)
            original_rows(audits,ROOT);audit_routes(model,audits);print('All grouped routes audited',flush=True)
            evaluate(model,audits)
            main=run_validation(model,work/'main',config)
            strict_config={**config,'allow_assumptions':False,'probability_policy':'mle_baseline',
                'milestones':config['strict_milestones'],'seed_start':config['strict_seed_start'],'sample_histories':2}
            strict_model=GameModel(previous,support,'mle_baseline')
            run_validation(strict_model,work/'empirical_only',strict_config)
            fixture=schedule([f'T{i:02}' for i in range(1,13)],config['game_date'])
            if league_gate(main) and main['attempted_games']==10000:
                league=run_league(model,work/'league',fixture,config,main)
            else:league={'status':'not_run','executed_games':0,'scheduled_games':858,
                'reason':'full primary stability/records gate failed; unplayed games not fabricated'}
            write_json(work/'league.json',league)
            if code_sha()!=fingerprint['code_sha256']:raise ValueError('Code changed during benchmark; no snapshot published')
            write_json(work/'build.json',{'snapshot_id':key,**fingerprint,'model_version':model.version,
                'rules_version':'stability-rules-1','engine_version':'stability-engine-1','parent_stage9_commit':'03a02714ab5779fd18d3fe5cdaad9a2f767dfec4'})
            files={str(p.relative_to(work)):sha(p) for p in sorted(work.rglob('*')) if p.is_file()}
            write_json(work/'snapshot_manifest.json',{'files':files});work.rename(dest)
            temp=output/'current.json.tmp';write_json(temp,{'snapshot_id':key});temp.replace(output/'current.json')
        except BaseException as exc:
            write_json(work/'build_failure.json',{'exception':type(exc).__name__,'reason':str(exc),'published':False});raise
    return dest


def package(snapshot,destination):
    snapshot=Path(snapshot);verify_snapshot(snapshot);destination=new_output(destination)
    if destination.exists():raise FileExistsError('Delivery never overwrites an existing directory')
    destination.mkdir(parents=True)
    for group in ('model','main','audits'):
        shutil.copytree(snapshot/group,destination/group)
    for group in ('empirical_only','league'):
        if (snapshot/group).exists():shutil.copytree(snapshot/group,destination/group)
    for p in ('build.json','snapshot_manifest.json','league.json'):shutil.copy2(snapshot/p,destination/p)
    for p in code_files():
        target=destination/'code'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    for stage,names in [('stage7',('manifest.json','base_model.json','kernels.json','identity_model.json','calibration.json')),
                         ('stage9',('routes.json.gz','terminal_model.json','model_manifest.json'))]:
        target=destination/(stage+'_model');target.mkdir()
        for name in names:shutil.copy2(ROOT/'data_sources'/stage/name,target/name)
    shutil.copy2(ROOT/'baseball_simulation_lab/stability/example.py',destination/'example.py')
    for name in ('README.md','TRANSITIONS.md','STAGE11.md','ATTRIBUTIONS.md','config.json','record_coverage.json'):
        shutil.copy2(ROOT/'data_sources/stage10'/name,destination/name)
    shutil.copy2(ROOT/'docs/data-stage10/README.md',destination/'REPORT.md')
    write_json(destination/'manifest.json',{'format':'stability-delivery-1','files':{str(p.relative_to(destination)):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}})
    archive=destination.parent/'stage10_bundle.zip'
    if archive.exists():raise FileExistsError('Existing delivery ZIP is immutable')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                info=zipfile.ZipInfo(str(p.relative_to(destination)),date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
                z.writestr(info,p.read_bytes())
    write_json(destination.parent/'bundle.json',{'file':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size})
    return archive
