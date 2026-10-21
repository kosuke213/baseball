"""Conditional update discovery. Never modifies a lock or a committed snapshot."""
from __future__ import annotations

from collections import Counter
from http.client import HTTPException
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
import uuid

from .fetch import CollectionError, Redirects, digest, safe_url, write_json


def repository_heads(plan):
    """Use Git's existing HTTPS/authentication flow; never parse credentials."""
    repositories=set()
    for spec in plan['artifacts']:
        match=re.match(r'^https://raw\.githubusercontent\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([0-9a-f]{40})/',spec['url'])
        if match:
            repositories.add(match.groups())
    results=[]
    for owner,repo,pinned in sorted(repositories):
        row={'repository':owner+'/'+repo,'pinned_commit':pinned}
        try:
            result=subprocess.run(['git','ls-remote',f'https://github.com/{owner}/{repo}.git','HEAD'],
                                  stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30,check=False)
            observed=re.fullmatch(r'([0-9a-f]{40})\s+HEAD\s*',result.stdout)
            if result.returncode or not observed:
                raise CollectionError('Remote HEAD unavailable')
            row.update(observed_commit=observed[1],status='unchanged_head' if observed[1]==pinned else 'new_head_available')
        except (OSError,subprocess.SubprocessError,CollectionError):
            # stderr/exception strings may contain authentication/proxy details.
            row.update(status='head_check_unavailable',observed_commit=None)
        results.append(row)
    return results


def probe(spec, previous, remaining, opener=None):
    """Return observed metadata + changed entity bytes; 304 is not a hash verification."""
    host=safe_url(spec['url'])
    if remaining<=0:
        raise CollectionError('Update check byte budget exhausted')
    headers={'User-Agent':'BaseballWarehouse/0.1 (conditional update check)','Accept-Encoding':'identity'}
    if previous.get('etag'):
        headers['If-None-Match']=previous['etag']
    elif previous.get('last_modified'):
        headers['If-Modified-Since']=previous['last_modified']
    opener=opener or build_opener(Redirects([host,*spec.get('redirect_hosts',[])]))
    size=0
    try:
        with opener.open(Request(spec['url'],headers=headers),timeout=30) as response:
            if response.status!=200 or safe_url(response.url) not in [host,*spec.get('redirect_hosts',[])]:
                raise CollectionError('Unexpected response/redirect during update check')
            limit=min(spec['max_bytes'],remaining)
            declared=int(response.headers.get('Content-Length','0'))
            if declared>limit:
                raise CollectionError('Update check exceeds its byte budget')
            chunks=[];deadline=time.monotonic()+120
            while chunk:=response.read(min(65536,limit-size+1)):
                size+=len(chunk)
                if size>limit or time.monotonic()>deadline:
                    raise CollectionError('Update check exceeds size/time limit')
                chunks.append(chunk)
            data=b''.join(chunks)
            if not data or (declared and len(data)!=declared):
                raise CollectionError('Empty/truncated update response')
            sha=digest(data)
            changed=sha!=previous['sha256']
            return {'status':'changed' if changed else 'unchanged_sha256','sha256':sha,'bytes_received':len(data),'http_status':200},data if changed else None
    except HTTPError as exc:
        code=exc.code;exc.close()
        if code==304:
            return {'status':'not_modified_http304','bytes_received':0,'http_status':304},None
        raise CollectionError(f'HTTP {code}') from None
    except CollectionError as exc:
        exc.bytes_received=size
        raise
    except (URLError,TimeoutError,OSError,HTTPException,ValueError):
        failure=CollectionError('Network/TLS/transport failure during update check')
        failure.bytes_received=size
        raise failure from None


def check_updates(args):
    from .warehouse import file_sha, now, snapshot, run_lock, validate_plan
    if args.offline:
        raise CollectionError('Update discovery requires network; offline run verifies the fixed snapshot instead')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    with run_lock(args.output):
        pointer=json.loads((args.output/'current.json').read_text());folder,_=snapshot(args.output,pointer)
        manifest=json.loads((folder/'manifest.json').read_text())
        if manifest['plan_sha256']!=file_sha(args.plan):
            raise CollectionError('Current snapshot and requested update plan differ')
        previous={m['id']:m for m in manifest['artifacts']}
        check_id=uuid.uuid4().hex;directory=args.output/'update_candidates'/check_id
        remaining=plan['budget_bytes'];results=[];last={};stopped=set();requests=0
        for spec in plan['artifacts']:
            row={'artifact_id':spec['id'],'url':spec['url'],'purpose':spec['purpose'],'previous_sha256':previous[spec['id']]['sha256']}
            if re.search(r'raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/',spec['url']):
                results.append({**row,'status':'immutable_commit_not_requested'});continue
            host=safe_url(spec['url'])
            if host in stopped:
                results.append({**row,'status':'skipped_after_rate_limit'});continue
            if remaining<=0:
                results.append({**row,'status':'failed','error':'Update check byte budget exhausted','bytes_received':0});continue
            time.sleep(max(0,last.get(host,0)+0.4-time.monotonic()));last[host]=time.monotonic();requests+=1
            try:
                result,data=probe(spec,previous[spec['id']],remaining)
                remaining-=result['bytes_received']
                if data is not None:
                    blob=directory/'blobs'/result['sha256'];blob.parent.mkdir(parents=True,exist_ok=True);blob.write_bytes(data)
                results.append({**row,**result})
            except CollectionError as exc:
                received=getattr(exc,'bytes_received',0);remaining-=received
                results.append({**row,'status':'failed','error':str(exc),'bytes_received':received})
                if str(exc)=='HTTP 429':stopped.add(host)
        states=dict(Counter(r['status'] for r in results))
        heads=repository_heads(plan)
        changed=bool(states.get('changed') or any(h['status']=='new_head_available' for h in heads))
        incomplete=bool(states.get('failed') or states.get('skipped_after_rate_limit') or any(h['status']=='head_check_unavailable' for h in heads))
        report={'checked_at':now(),'snapshot_id':pointer['snapshot_id'],'plan_sha256':file_sha(args.plan),
                'status':'incomplete' if incomplete else 'changes_detected' if changed else 'no_changes_detected',
                'network_requests':requests,'bytes_received':sum(r.get('bytes_received',0) for r in results),
                'repository_heads':heads,'git_head_requests':len(heads),
                'counts':states,'results':results,'promoted':False,
                'rights_evidence_changes':[r['artifact_id'] for r in results if r['status']=='changed' and r['purpose']=='evidence'],
                'limits':'HTTP 304 is a conditional server response, not independent byte verification. Fixed raw cache is separately verified during run. Remote HEAD changes are candidates, not proof of changed data. Git is required for the optional remote HEAD checks; an unavailable check is incomplete. New years need a new bounded plan. Candidate changes never overwrite prior snapshots/locks.'}
        write_json(directory/'report.json',report)
        write_json(args.output/'last_update_check.json',report)
        write_json(args.report_dir/'update_check.json',report)
        print(json.dumps({'status':report['status'],'counts':states,'network_requests':requests,'promoted':False},ensure_ascii=False))
        return 1 if incomplete else 0
