"""Reproducible research build. Private career databases are never published."""
from pathlib import Path
import hashlib,json,platform,shutil,sqlite3,uuid,zipfile

from data_collection.fetch import write_json
from ..calibrated.rules import canonical
from ..completion.pipeline import code_files,code_sha,lock,verify_snapshot
from ..fullgame.sources import sha
from ..stability.model import GameModel
from .validation import contrasts,frozen_games,seasons,annual_cohort
from .storage import protect

ROOT=Path(__file__).resolve().parents[2]


def new_output(path):
    p=protect(path)
    for prefix in ('data_sources','data/research'):
        for old in ('pilot','warehouse','stage5','stage6','stage7','stage8','stage9','stage10'):
            old=(ROOT/prefix/old).resolve()
            if old.is_relative_to(p):raise ValueError('Cannot write an ancestor of historical output')
    return p


def load_base():return GameModel.load(ROOT/'data_sources/stage7',ROOT/'data_sources/stage9',ROOT/'data_sources/stage10/support_model.json')


def run(config_path=None,output=None):
    config_path=Path(config_path or ROOT/'data_sources/stage11/config.json');config=json.loads(config_path.read_text())
    output=new_output(output or ROOT/'data/research/stage11');output.mkdir(parents=True,exist_ok=True)
    base=load_base();fingerprint={'code_sha256':code_sha(),'config':config,'parent_model_version':base.version,
        'runtime':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform()}}
    key=hashlib.sha256(canonical(fingerprint).encode()).hexdigest()[:24];snapshots=output/'snapshots';snapshots.mkdir(exist_ok=True);dest=snapshots/key
    with lock(output/'build.lock'):
        if dest.exists():verify_snapshot(dest);print('Reusing immutable career snapshot '+key,flush=True);return dest
        work=snapshots/(key+'.'+uuid.uuid4().hex[:8]+'.building');work.mkdir()
        try:
            audits=work/'audits';audits.mkdir()
            contrasts(base,audits,config['contrast_pa_trials'])
            validation=frozen_games(base,work/'frozen_games',config)
            gate=validation['attempted_games']>=1000 and not validation['failed_games'] and not validation['record_integrity_failures'] and not validation['unresolved_priority_records']
            if gate:integration=seasons(base,work/'integrated',config)
            else:integration={'status':'not_run','reason':'frozen-game stability gate failed','executed_games':0}
            cohort=annual_cohort(work/'cohort20',config)
            if code_sha()!=fingerprint['code_sha256']:raise ValueError('Code changed during verification; no snapshot published')
            write_json(work/'build.json',{'snapshot_id':key,**fingerprint,'frozen_game_gate':gate,
                'integrated_status':integration['status'],'cohort_years':cohort['annual_steps'],
                'private_databases_are_admin_only':True,'published_player_data_is_scouting_only':True})
            files={str(p.relative_to(work)):sha(p) for p in sorted(work.rglob('*')) if p.is_file()}
            write_json(work/'snapshot_manifest.json',{'files':files,'privacy':'administrator-only internal snapshot; do not publish databases/private CSVs'})
            work.rename(dest);temp=output/'current.json.tmp';write_json(temp,{'snapshot_id':key});temp.replace(output/'current.json')
        except BaseException as exc:
            write_json(work/'build_failure.json',{'exception':type(exc).__name__,'reason':str(exc),'published':False});raise
    return dest


PUBLIC_FILES={
 'audits/ability_contrasts.json':'ability_contrasts.json',
 'frozen_games/validation.json':'validation.json','frozen_games/games.csv':'games.csv',
 'frozen_games/neutral_games.csv':'neutral_games.csv','frozen_games/failures.json':'failures.json',
 'integrated/summary.json':'integrated_summary.json','integrated/public_players.json':'public_players.json',
 'integrated/public_seasons.json':'public_seasons.json','integrated/games.csv':'integrated_games.csv',
 'cohort20/summary.json':'cohort20_summary.json','cohort20/anonymous_age_curves.csv':'anonymous_age_curves.csv',
 'cohort20/public_sample_scouted_curves.csv':'public_sample_scouted_curves.csv'}


def publish_public(snapshot,destination):
    snapshot=Path(snapshot);verify_snapshot(snapshot);destination=new_output(destination);destination.mkdir(parents=True,exist_ok=True)
    for source,target in PUBLIC_FILES.items():
        if (snapshot/source).exists():shutil.copy2(snapshot/source,destination/target)
    # Build config consists of explicitly public research-fixture seeds. It is
    # never used as the source of an operational private world's random key.
    shutil.copy2(snapshot/'build.json',destination/'build.json')


def package(snapshot,destination):
    snapshot=Path(snapshot);verify_snapshot(snapshot);destination=new_output(destination)
    if destination.exists():raise FileExistsError('Distribution destination must be new')
    destination.mkdir(parents=True);publish_public(snapshot,destination)
    for p in code_files():
        target=destination/'code'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    for stage,names in [('stage7',('manifest.json','base_model.json','kernels.json','identity_model.json','calibration.json')),
                        ('stage9',('routes.json.gz','terminal_model.json','model_manifest.json')),
                        ('stage10',('support_model.json','support_manifest.json'))]:
        target=destination/(stage+'_model');target.mkdir()
        for name in names:shutil.copy2(ROOT/'data_sources'/stage/name,target/name)
    shutil.copy2(ROOT/'baseball_simulation_lab/careers/example.py',destination/'example.py')
    for name in ('README.md','STAGE12.md','MODEL.md','ATTRIBUTIONS.md','model_assumptions.json','config.json'):
        shutil.copy2(ROOT/'data_sources/stage11'/name,destination/name)
    shutil.copy2(ROOT/'docs/data-stage11/README.md',destination/'REPORT.md')
    # Only these public files and source/model dependencies enter the ZIP. No
    # private career DB, raw pregame snapshot, private event or internal curve.
    if any(p.suffix=='.sqlite3' or 'private_' in p.name for p in destination.rglob('*') if p.is_file()):raise ValueError('Private file in public distribution')
    write_json(destination/'manifest.json',{'format':'career-public-delivery-1','private_databases_included':False,
        'files':{str(p.relative_to(destination)):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}})
    archive=destination.parent/'stage11_bundle.zip'
    if archive.exists():raise FileExistsError('Existing ZIP is immutable')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                info=zipfile.ZipInfo(str(p.relative_to(destination)),date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
                z.writestr(info,p.read_bytes())
    write_json(destination.parent/'bundle.json',{'file':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'private_career_data_included':False})
    return archive
