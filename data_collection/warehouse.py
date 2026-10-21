"""Stage 3/4: versioned normalized snapshots, resumable acquisition and update checks."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile

from . import adapters
from .fetch import Collector, CollectionError, digest, safe_url, write_json
from .__main__ import export_csv
from . import warehouse_store as store

ROOT=Path(__file__).resolve().parents[1]


def file_sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def code_sha():
    files=[Path(__file__),Path(store.__file__),store.SCHEMA,Path(adapters.__file__),Path(__file__).with_name('fetch.py')]
    return digest(b''.join(p.name.encode()+b'\0'+p.read_bytes()+b'\0' for p in files))


def validate_plan(plan):
    years=plan['years']
    if years != sorted(set(years)) or not years or len(years)>5 or any(not isinstance(y,int) or not 1900<=y<=2100 for y in years):
        raise CollectionError('Specify one to five distinct ascending years')
    if not 1<=plan['budget_bytes']<=250_000_000:
        raise CollectionError('Warehouse network budget exceeds 250 MB scope')
    artifacts={s['id']:s for s in plan['artifacts']}
    if len(artifacts) != len(plan['artifacts']):
        raise CollectionError('Duplicate artifact IDs')
    for s in artifacts.values():
        if not re.fullmatch(r'[a-z0-9_-]+',s['id']) or s['purpose'] not in ('data','evidence') or not 1<=s['max_bytes']<=20_000_000:
            raise CollectionError('Invalid artifact specification')
        safe_url(s['url'])
        rights=plan['rights'][s['rights']]
        if not rights.get('attribution') or not rights.get('evidence_artifacts'):
            raise CollectionError('Missing rights evidence or attribution')
        for key in rights['evidence_artifacts']:
            if key not in artifacts or artifacts[key]['purpose']!='evidence':
                raise CollectionError('Invalid policy evidence dependency')
        if s['purpose']=='data' and not rights.get('warehouse_collection_allowed'):
            raise CollectionError('Warehouse use is deferred by the plan rights decision')
    for key in ['retro_park_codes','jpl_draft_2026','jma_tokyo_20240329',*[f'register_{x}' for x in '0123456789abcdef'],
                *[f'retro_{kind}_{y}' for y in years for kind in ['gl','plays']]]:
        if key not in artifacts:
            raise CollectionError('Missing required warehouse partition: '+key)


@contextmanager
def run_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(root/'run.lock.sqlite3',timeout=0)) as db:
        try:
            db.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:
            raise CollectionError('Another warehouse operation holds the process lock') from None
        try:
            yield
        finally:
            db.rollback()


class Ledger:
    def __init__(self, root):
        self.path=root/'ledger.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,
                    plan_sha256 TEXT NOT NULL,status TEXT NOT NULL,snapshot_id TEXT,message TEXT);
                CREATE TABLE IF NOT EXISTS jobs(run_id TEXT REFERENCES runs,artifact_id TEXT,status TEXT NOT NULL,
                    sha256 TEXT,error TEXT,PRIMARY KEY(run_id,artifact_id));
            ''')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            yield db

    def start(self, plan_sha):
        key=uuid.uuid4().hex
        with self.connect() as db:
            # The OS/SQLite process lock guarantees no previous process is live here.
            db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'",(now(),))
            db.execute("INSERT INTO runs VALUES(?,?,NULL,?,'running',NULL,NULL)",(key,now(),plan_sha))
        return key

    def job(self, run, artifact, status, sha=None, error=None):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',(run,artifact,status,sha,error))

    def finish(self,run,status,snapshot=None,message=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET status=?,finished_at=?,snapshot_id=?,message=? WHERE run_id=?',(status,now(),snapshot,message,run))


def now():
    return datetime.now(timezone.utc).isoformat()


def acquire(args, plan, ledger, run_id):
    plan_sha=file_sha(args.plan)
    lock_path=args.plan.with_name('lock.json')
    lock=json.loads(lock_path.read_text()) if lock_path.exists() else None
    if not lock and not args.record_lock:
        raise CollectionError('Missing lock; reviewed first acquisition requires --record-lock')
    if lock and lock['plan_sha256']!=plan_sha:
        raise CollectionError('Plan differs from immutable lock; use a new versioned plan directory')
    if lock and set(lock['artifacts'])!={s['id'] for s in plan['artifacts']}:
        raise CollectionError('Lock artifact membership differs from plan')
    collector=Collector(args.cache,plan['rights'],offline=args.offline,budget=plan['budget_bytes'])
    payloads={};metas=[];failures=[]
    for original in sorted(plan['artifacts'],key=lambda s:s['purpose']=='data'):
        s=dict(original)
        try:
            if s['purpose']=='data' and any(key not in payloads for key in plan['rights'][s['rights']]['evidence_artifacts']):
                raise CollectionError('Rights evidence unavailable; dependent data skipped')
            if lock:
                pin=lock['artifacts'][s['id']]
                if pin['url']!=s['url']:
                    raise CollectionError('URL differs from pinned artifact')
                s['expected_sha256']=pin['sha256']
            before=collector.cache_hits
            data,meta=collector.fetch(s)
            if lock and len(data)!=pin['bytes']:
                raise CollectionError('Artifact length differs from lock')
            payloads[s['id']]=data;metas.append(meta)
            ledger.job(run_id,s['id'],'cached' if collector.cache_hits>before else 'downloaded',meta['sha256'])
        except CollectionError as exc:
            failures.append({'artifact_id':s['id'],'error':str(exc)})
            ledger.job(run_id,s['id'],'failed',error=str(exc))
    write_json(args.output/'last_acquisition.json',{'run_id':run_id,'checked_at':now(),'failures':failures,
                'network_requests':collector.network_requests,'cache_hits':collector.cache_hits})
    if failures:
        raise CollectionError(f'{len(failures)} acquisition failures; successful artifacts retained for resume')
    if not lock:
        lock={'schema_version':1,'plan_sha256':plan_sha,'artifacts':{m['id']:{k:m[k] for k in ['url','sha256','bytes']} for m in metas}}
        write_json(lock_path,lock)
    return payloads,metas,file_sha(lock_path),collector.network_requests,collector.cache_hits


def snapshot(root, pointer):
    key=pointer['snapshot_id']
    if not re.fullmatch(r'[0-9a-f]{24}',key):
        raise CollectionError('Invalid snapshot identifier')
    folder=root/'snapshots'/key
    info=json.loads((folder/'snapshot.json').read_text())
    for name,sha in info['files'].items():
        if name not in ('warehouse.sqlite3','quality.json','manifest.json','policy.json','plan.json','lock.json') or file_sha(folder/name)!=sha:
            raise CollectionError('Committed snapshot checksum mismatch')
    if pointer['database_sha256']!=info['files']['warehouse.sqlite3']:
        raise CollectionError('Snapshot pointer differs from committed manifest')
    return folder,info


def publish_reports(folder, report_dir, plan):
    report_dir.mkdir(parents=True,exist_ok=True)
    for name in ['quality.json','manifest.json','snapshot.json','policy.json']:
        shutil.copyfile(folder/name,report_dir/name)
    with closing(sqlite3.connect(folder/'warehouse.sqlite3')) as db:
        db.row_factory=sqlite3.Row
        exports={
            'games.csv':'SELECT * FROM game_results ORDER BY season,start_date,game_id',
            'teams.csv':'SELECT * FROM team_seasons ORDER BY season,team_id',
            'parks.csv':"SELECT park_id,source_code,name_as_published,city,region,metadata_status FROM parks ORDER BY park_id",
            'quarantine.csv':"SELECT * FROM game_checks WHERE status!='pass' ORDER BY game_id",
        }
        for name,query in exports.items():
            rows=[dict(r) for r in db.execute(query)]
            if rows:
                export_csv(report_dir/name,rows)
            else:
                # Explicit header for a genuinely empty quarantine, never a blank failure file.
                (report_dir/name).write_text('game_id,status,play_rows,counters_json,failures_json\n',encoding='utf-8-sig')
    mandatory=['README.md','ATTRIBUTIONS.md']
    for name in mandatory:
        if not (report_dir/name).exists():
            raise CollectionError('Download documentation missing: '+name)
    path=report_dir/'database_bundle.zip'
    fd,tmp=tempfile.mkstemp(dir=report_dir,suffix='.zip');os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            files={'warehouse.sqlite3':folder/'warehouse.sqlite3',**{n:report_dir/n for n in [*mandatory,'quality.json','manifest.json','snapshot.json','policy.json','games.csv','teams.csv','parks.csv','quarantine.csv']}}
            for name in ('plan.json','lock.json'):
                if (folder/name).exists():
                    files[name]=folder/name
            for name,p in sorted(files.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                # Stream the database to avoid making another in-memory copy.
                with p.open('rb') as src,z.open(info,'w',force_zip64=True) as target:
                    shutil.copyfileobj(src,target,1024*1024)
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    write_json(report_dir/'bundle.json',{'file':path.name,'bytes':path.stat().st_size,'sha256':file_sha(path),
                'database_sha256':file_sha(folder/'warehouse.sqlite3')})


def run(args):
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    with run_lock(args.output):
        ledger=Ledger(args.output);run_id=ledger.start(file_sha(args.plan));staging=None
        try:
            payloads,metas,lock_sha,requests,hits=acquire(args,plan,ledger,run_id)
            meta={'schema_version':1,'plan_sha256':file_sha(args.plan),'lock_sha256':lock_sha,'transform_sha256':code_sha(),
                  'rule_context':store.RULE_CONTEXT,
                  'runtime':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version}}
            key=digest(store.js(meta).encode())[:24]
            target=args.output/'snapshots'/key
            if target.exists():
                old={'snapshot_id':key,'database_sha256':json.loads((target/'snapshot.json').read_text())['files']['warehouse.sqlite3']}
                folder,info=snapshot(args.output,old)
                # Recover publication after interruption between snapshot commit and pointer update.
                publish_reports(folder,args.report_dir,plan)
                write_json(args.output/'current.json',old)
                ledger.finish(run_id,'reused',key)
                print(store.js({'status':'reused','snapshot_id':key,'network_requests':requests,'cache_hits':hits}))
                return 0
            parent=args.output/'snapshots';parent.mkdir(exist_ok=True)
            staging=Path(tempfile.mkdtemp(dir=parent,prefix='.building-'))
            report=store.build(staging/'warehouse.sqlite3',plan,payloads,metas,meta,lambda s:print(s,flush=True))
            report.update(meta,snapshot_id=key)
            write_json(staging/'quality.json',report)
            write_json(staging/'manifest.json',{'snapshot_id':key,**meta,'artifacts':metas})
            write_json(staging/'policy.json',plan['rights'])
            shutil.copyfile(args.plan,staging/'plan.json')
            shutil.copyfile(args.plan.with_name('lock.json'),staging/'lock.json')
            files={n:file_sha(staging/n) for n in ['warehouse.sqlite3','quality.json','manifest.json','policy.json','plan.json','lock.json']}
            info={'snapshot_id':key,'status':report['status'],'files':files,**meta}
            write_json(staging/'snapshot.json',info)
            os.replace(staging,target);staging=None
            publish_reports(target,args.report_dir,plan)
            pointer={'snapshot_id':key,'database_sha256':files['warehouse.sqlite3']}
            write_json(args.output/'current.json',pointer)
            ledger.finish(run_id,'committed',key)
            print(store.js({'status':report['status'],'snapshot_id':key,'counts':report['counts'],'network_requests':requests,'cache_hits':hits}))
            return 0
        except BaseException as exc:
            ledger.finish(run_id,'interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',message=type(exc).__name__)
            if staging is not None:
                shutil.rmtree(staging)
            raise


def status(args):
    pointer=json.loads((args.output/'current.json').read_text());folder,info=snapshot(args.output,pointer)
    report=json.loads((folder/'quality.json').read_text())
    print(json.dumps({'snapshot':pointer,'status':report['status'],'counts':report['counts'],'by_year':report['by_year']},ensure_ascii=False,indent=2))
    return 0


def source_row(args):
    pointer=json.loads((args.output/'current.json').read_text());folder,_=snapshot(args.output,pointer)
    with closing(sqlite3.connect(folder/'warehouse.sqlite3')) as db:
        key=args.game_id if args.game_id.startswith('retrosheet:game:') else store.entity('game',args.game_id)
        row=db.execute('SELECT artifact_id,source_row FROM plays WHERE game_id=? AND play_number=?',(key,args.play)).fetchone()
        if not row:
            raise CollectionError('Play not found')
        meta=json.loads(db.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?',(row[0],)).fetchone()[0])
        schema=db.execute('SELECT member FROM source_schemas WHERE artifact_id=?',(row[0],)).fetchone()[0]
    blob=args.cache/'blobs'/meta['sha256']
    if not blob.exists() or file_sha(blob)!=meta['sha256']:
        raise CollectionError('Original archive missing/corrupt; run locked acquisition to restore')
    for number,values in adapters.zipped_csv(blob.read_bytes(),schema):
        if number==row[1]:
            print(json.dumps({'artifact_id':row[0],'sha256':meta['sha256'],'source_row':number,'values':values},ensure_ascii=False,indent=2))
            return 0
    raise CollectionError('Original source row not found')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','status','source-row','check-updates'])
    parser.add_argument('--plan',type=Path,default=ROOT/'data_sources/warehouse/plan.json')
    parser.add_argument('--output',type=Path,default=ROOT/'data/research/warehouse')
    parser.add_argument('--cache',type=Path,default=ROOT/'data/research/pilot/raw')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'data_sources/warehouse')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--record-lock',action='store_true')
    parser.add_argument('--game-id')
    parser.add_argument('--play',type=int,default=1)
    args=parser.parse_args()
    try:
        if args.command=='run':return run(args)
        if args.command=='status':return status(args)
        if args.command=='source-row':
            if not args.game_id:raise CollectionError('--game-id is required')
            return source_row(args)
        from .warehouse_updates import check_updates
        return check_updates(args)
    except KeyboardInterrupt:
        print('Warehouse interrupted; cached artifacts retained for resume',file=sys.stderr);return 130
    except Exception as exc:
        # No raw network exception chains or environment values in logs.
        message=str(exc) if isinstance(exc,CollectionError) else 'Check input schema, constraints, cache and ledger'
        print(f'Warehouse failed ({type(exc).__name__}): {message}',file=sys.stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
