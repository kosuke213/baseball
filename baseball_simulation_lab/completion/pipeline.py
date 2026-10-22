"""Immutable Stage 9 build: source audit, paired regressions, staged benchmarks."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import time
import uuid
import zipfile

from data_collection.fetch import write_json
from ..calibrated.rules import canonical
from ..fullgame.sources import sha
from .paths import ROOT, new_output


def code_files():
    return sorted(p for package in ('baseball_simulation_lab','data_collection')
                  for p in (ROOT/package).rglob('*') if p.suffix in ('.py','.sql'))


def code_sha():
    return hashlib.sha256(canonical({str(p.relative_to(ROOT)):sha(p) for p in code_files()}).encode()).hexdigest()


@contextmanager
def lock(path):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally:path.unlink()


def run(config_path=None, output=None):
    from .sources import build
    from .model import GameModel
    from .regression import run as regress
    from .evaluation import run as compare, audit_old_rbi
    from .validation import run_validation
    config_path=Path(config_path or ROOT/'data_sources/stage9/config.json')
    output=new_output(output or ROOT/'data/research/stage9');output.mkdir(parents=True,exist_ok=True)
    config=json.loads(config_path.read_text());code=code_sha()
    fingerprint={'code_sha256':code,'config':config,'parent_stage8_sha256':sha(ROOT/'data_sources/stage8/manifest.json'),
                 'runtime':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform()}}
    key=hashlib.sha256(canonical(fingerprint).encode()).hexdigest()[:24]
    snapshots=output/'snapshots';snapshots.mkdir(exist_ok=True);dest=snapshots/key
    with lock(output/'build.lock'):
        if dest.exists():
            verify_snapshot(dest);print(f'Reusing immutable Stage 9 snapshot {key}');return dest
        work=snapshots/(key+'.'+uuid.uuid4().hex[:8]+'.building');work.mkdir()
        try:
            build(work/'model')
            m=GameModel.load(ROOT/'data_sources/stage7',work/'model/routes.json.gz',work/'model/terminal_model.json')
            audits=work/'audits';audits.mkdir()
            regress(m,audits,ROOT);audit_old_rbi(m,audits,ROOT);compare(m,audits,ROOT)
            main=run_validation(m,work/'main',config)
            strict={**config,'milestones':config['strict_milestones'],'seed_start':config['strict_seed_start'],
                    'allow_assumptions':False,'sample_histories':2}
            run_validation(m,work/'empirical_only',strict)
            write_json(work/'build.json',{'snapshot_id':key,**fingerprint,'model_version':m.version,
                       'new_play_data_requests':0,'main_completed':main['completed_games']})
            if code_sha()!=code:raise ValueError('Code changed during build; old snapshots retained')
            files={str(p.relative_to(work)):sha(p) for p in sorted(work.rglob('*')) if p.is_file()}
            write_json(work/'snapshot_manifest.json',{'files':files})
            work.rename(dest)
            temporary=output/'current.json.tmp';write_json(temporary,{'snapshot_id':key});temporary.replace(output/'current.json')
        except BaseException as exc:
            write_json(work/'build_failure.json',{'exception':type(exc).__name__,'reason':str(exc),'published':False});raise
    return dest


def verify_snapshot(path):
    manifest=json.loads((path/'snapshot_manifest.json').read_text())
    for n,digest in manifest['files'].items():
        if sha(path/n)!=digest:raise ValueError('Snapshot checksum mismatch: '+n)


def package(snapshot, destination):
    """Run after writing manuals. A fresh destination is mandatory."""
    snapshot=Path(snapshot);verify_snapshot(snapshot)
    destination=new_output(destination)
    if destination.exists():raise FileExistsError('Delivery never overwrites existing artifacts')
    destination.mkdir(parents=True)
    for directory in ('model','main','audits'):
        for p in (snapshot/directory).iterdir():
            target=destination/p.name
            if p.is_dir():shutil.copytree(p,target)
            else:shutil.copy2(p,target)
    shutil.copytree(snapshot/'empirical_only',destination/'empirical_only')
    for p in (snapshot/'build.json',snapshot/'snapshot_manifest.json'):shutil.copy2(p,destination/p.name)
    shutil.copy2(ROOT/'data_sources/stage9/config.json',destination/'config.json')
    for p in code_files():
        target=destination/'code'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    parent=destination/'stage7_model';parent.mkdir()
    for n in ('manifest.json','base_model.json','kernels.json','identity_model.json','calibration.json'):
        shutil.copy2(ROOT/'data_sources/stage7'/n,parent/n)
    shutil.copy2(ROOT/'baseball_simulation_lab/completion/example.py',destination/'example.py')
    for name in ('README.md','STAGE10.md','TRANSITIONS.md','ATTRIBUTIONS.md'):
        shutil.copy2(ROOT/'data_sources/stage9'/name,destination/name)
    shutil.copy2(ROOT/'docs/data-stage9/README.md',destination/'REPORT.md')
    files={str(p.relative_to(destination)):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    write_json(destination/'manifest.json',{'format':'completion-delivery-1','files':files})
    zip_path=destination.parent/'stage9_bundle.zip'
    if zip_path.exists():raise FileExistsError('Existing ZIP must remain immutable')
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                info=zipfile.ZipInfo(str(p.relative_to(destination)),date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                info.external_attr=0o644<<16;z.writestr(info,p.read_bytes())
    write_json(destination.parent/'bundle.json',{'zip_sha256':sha(zip_path),'bytes':zip_path.stat().st_size})
    return zip_path
