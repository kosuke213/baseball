from argparse import Namespace
from contextlib import closing
import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
import uuid
import zipfile

import pytest

from data_collection import adapters as a
from data_collection import warehouse as w
from data_collection import warehouse_store as s
from data_collection import warehouse_updates as u
from data_collection.fetch import CollectionError, digest


def csv_bytes(rows,fields=None,header=True):
    out=io.StringIO(newline='');writer=csv.writer(out,lineterminator='\n')
    if fields and header:writer.writerow(fields)
    for r in rows:writer.writerow([r[k] for k in fields] if isinstance(r,dict) else r)
    return out.getvalue().encode('utf-8')


def archive(member,data):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr(member,data)
    return out.getvalue()


def fixture_data():
    gid='HOM202404010';g={f'field_{n:03}':'' for n in range(1,162)}
    g.update(field_001='20240401',field_002='0',field_004='AWY',field_005='AL',field_007='HOM',field_008='NL',
             field_010='0',field_011='1',field_012='51',field_017='TST01',field_018='1000',field_019='120',
             field_020='000000000',field_021='000000001',field_161='Y')
    for start in (22,50):
        for i in range(start,start+17):g[f'field_{i:03}']='0'
        g[f'field_{start:03}']='9'
    g['field_051']=g['field_054']='1'
    plays=[]
    for half in range(18):
        last=half==17;side=str(half%2)
        p=dict(gid=gid,event='HR' if last else '8/TP',inning=str(half//2+1),top_bot=side,vis_home=side,
               site='TST01',batteam='HOM' if half%2 else 'AWY',pitteam='AWY' if half%2 else 'HOM',
               score_v='0',score_h='0',batter='batta001',pitcher='pitch001',balls='0',strikes='0',count='00',
               pitches='X',nump='1',pa='1',ab='1',single='0',double='0',triple='0',hr='1' if last else '0',
               walk='0',k='0',iw='0',bathand='R',pithand='R',outs_pre='0',outs_post='0' if last else '3',
               runs='1' if last else '0',pn=str(half+1),date='20240401',gametype='regular',pbp='full',future_field='retain-me')
        p.update({f'br{b}_{state}':'' for b in (1,2,3) for state in ('pre','post')});plays.append(p)
    payload={'policy':b'Test open policy','retro_gl_2024':archive('gl2024.txt',csv_bytes([list(g.values())])),
             'retro_plays_2024':archive('2024plays.csv',csv_bytes(plays,list(plays[0]))),
             'retro_park_codes':b'PARKID,NAME,AKA,CITY,STATE,START,END,LEAGUE,NOTES\nTST01,Test Park,,Test,TS,01/01/2000,,NL,\n',
             'jpl_draft_2026':'rank,name_jp\n1,例の選手\n'.encode()}
    headers=['key_uuid','name_first','name_last','birth_year',*s.IDS]
    for i,ch in enumerate('0123456789abcdef'):
        person=dict.fromkeys(headers,'');person.update(key_uuid=str(uuid.UUID(int=i+1)),name_first='Test',name_last=str(i),birth_year='2000')
        person['key_retro']='batta001' if i==0 else 'pitch001' if i==1 else ''
        person['key_npb']=f'{i:010}' if i>=2 else ''
        payload['register_'+ch]=csv_bytes([person],headers)
    cells=['1']+['1.0']*16;cells[9]='北';cells[14]='晴'
    rows=[]
    for hour in range(1,25):
        cells[0]=str(hour);rows.append('<tr>'+''.join(f'<td class="data_0_0">{c}</td>' for c in cells)+'</tr>')
    payload['jma_tokyo_20240329']=('東京（東京都) 2024年3月29日<table id="tablefix1">'+''.join(rows)+'</table>').encode()
    metas=[{'id':key,'sha256':digest(data),'bytes':len(data),'url':'https://example.org/'+key,'purpose':'evidence' if key=='policy' else 'data'} for key,data in payload.items()]
    return g,plays,payload,metas


def fixture_run(tmp_path,monkeypatch):
    _,_,payload,metas=fixture_data();meta={x['id']:x for x in metas}
    specs=[{'id':key,'url':meta[key]['url'],'rights':'test','purpose':meta[key]['purpose'],'max_bytes':100000} for key in payload]
    policy={'warehouse_collection_allowed':True,'pilot_collection_allowed':True,'attribution':'Test','evidence_artifacts':['policy']}
    plan={'years':[2024],'budget_bytes':1000000,'rights':{'test':policy},'artifacts':specs}
    plan_path=tmp_path/'plan.json';plan_path.write_text(json.dumps(plan))
    reports=tmp_path/'reports';reports.mkdir();(reports/'README.md').write_text('Test');(reports/'ATTRIBUTIONS.md').write_text('Test')
    class Collector:
        network_requests=0
        def __init__(self,*args,**kwargs):self.cache_hits=0
        def fetch(self,spec):
            self.cache_hits+=1;key=spec['id'];return payload[key],meta[key]
    monkeypatch.setattr(w,'Collector',Collector)
    return Namespace(plan=plan_path,output=tmp_path/'warehouse',cache=tmp_path/'raw',report_dir=reports,offline=True,record_lock=True)


def test_full_typed_import_preserves_provenance_keys_units_and_original_schema(tmp_path):
    _,_,payload,metas=fixture_data();p=tmp_path/'db.sqlite3'
    report=s.build(p,{'years':[2024]},payload,metas,{'test':True},lambda _:None)
    assert report['status']=='pass' and report['counts']['games']==1 and report['counts']['plays']==18
    assert report['identity_status_batters_pitchers']=={'matched':2}
    with closing(sqlite3.connect(p)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT identifier FROM identifiers WHERE namespace='npb' ORDER BY identifier LIMIT 1").fetchone()[0]=='0000000002'
        schema=json.loads(db.execute("SELECT columns_json FROM source_schemas WHERE artifact_id='retro_plays_2024'").fetchone()[0])
        assert 'future_field' in schema
        assert db.execute('SELECT artifact_id,source_row FROM plays ORDER BY play_number LIMIT 1').fetchone()==('retro_plays_2024',2)
        assert db.execute("SELECT unit,value FROM weather_observations WHERE metric='temperature_c' LIMIT 1").fetchone()==('degC',1.0)
        assert db.execute("SELECT raw_text,value,parse_status FROM weather_observations WHERE metric='wind_direction' LIMIT 1").fetchone()==('北',None,'categorical')
        assert db.execute('SELECT person_id FROM secondary_claims').fetchone()==(None,)


def test_mismatched_stats_are_retained_but_quarantined_from_analysis(tmp_path):
    _,_,payload,metas=fixture_data()
    with zipfile.ZipFile(io.BytesIO(payload['retro_gl_2024'])) as z:values=list(csv.reader(io.StringIO(z.read('gl2024.txt').decode())))[0]
    values[21]='10' # expected 9 at-bats, keep score and outs valid
    payload['retro_gl_2024']=archive('gl2024.txt',csv_bytes([values]))
    p=tmp_path/'db';q=s.build(p,{'years':[2024]},payload,metas,{},lambda _:None)
    assert q['status']=='validated_with_exclusions' and q['counts']['plays']==18 and q['counts']['analysis_plays']==0
    assert q['game_failures'][0]['failures'][0]['check']=='batting_at_bats'


def test_snapshot_reuse_and_download_are_idempotent(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch)
    assert w.run(args)==0
    pointer=(args.output/'current.json').read_bytes();bundle=w.file_sha(args.report_dir/'database_bundle.zip')
    assert w.run(args)==0
    assert (args.output/'current.json').read_bytes()==pointer
    assert w.file_sha(args.report_dir/'database_bundle.zip')==bundle
    with closing(sqlite3.connect(args.output/'ledger.sqlite3')) as db:
        assert [r[0] for r in db.execute('SELECT status FROM runs ORDER BY started_at')]==['committed','reused']


def test_failed_transform_preserves_previous_snapshot_and_resume_ledger(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch);w.run(args)
    before=(args.output/'current.json').read_bytes()
    monkeypatch.setattr(w,'code_sha',lambda:'b'*64)
    def fail(*args,**kwargs):raise CollectionError('simulated parser failure')
    monkeypatch.setattr(s,'build',fail)
    with pytest.raises(CollectionError,match='simulated'):w.run(args)
    assert (args.output/'current.json').read_bytes()==before
    assert not list((args.output/'snapshots').glob('.building-*'))
    with closing(sqlite3.connect(args.output/'ledger.sqlite3')) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE status='cached'").fetchone()[0]>0
        assert db.execute("SELECT count(*) FROM runs WHERE status='failed'").fetchone()[0]==1


def test_changed_plan_is_rejected_without_replacing_current(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch);w.run(args);before=(args.output/'current.json').read_bytes()
    plan=json.loads(args.plan.read_text());plan['extra_note']='different version';args.plan.write_text(json.dumps(plan))
    with pytest.raises(CollectionError,match='immutable lock'):w.run(args)
    assert (args.output/'current.json').read_bytes()==before


def test_process_lock_recovers_after_release_and_excludes_parallel_runs(tmp_path):
    with w.run_lock(tmp_path):
        with pytest.raises(CollectionError,match='process lock'):
            with w.run_lock(tmp_path):pass
    with w.run_lock(tmp_path):pass


def test_unknown_park_has_no_invented_name_and_no_cross_namespace_key(tmp_path):
    db=sqlite3.connect(':memory:');db.executescript(s.SCHEMA.read_text())
    db.execute("INSERT INTO artifacts VALUES('test','abc',1,'{}')")
    key=s.ensure_park(db,'NEW01','test',2)
    assert key=='retrosheet:park:NEW01'
    assert db.execute('SELECT name_as_published,metadata_status FROM parks').fetchone()==(None,'unresolved')
    assert s.entity('team','NEW01')!=key
    with pytest.raises(CollectionError):s.entity('park','')
    db.close()


def validation_fixture():
    g,ps,_,_=fixture_data();g['game_id']=ps[0]['gid']
    return g,ps


def test_after_third_out_only_nonplaying_np_is_accepted():
    g,ps=validation_fixture();np=copy.deepcopy(ps[0]);np.update(event='NP',pa='0',ab='0',outs_pre='3',outs_post='3')
    ps.insert(1,np)
    for i,p in enumerate(ps):p['pn']=str(i+1)
    rows=[a.record('test','',i+2,p) for i,p in enumerate(ps)]
    def validate():return a.validate_plays([a.record('test','',1,g)],rows,{g['game_id']:['test']})
    assert not validate()['failures']
    np['event']='K'
    assert any(f['check']=='outs_range' for f in validate()['failures'])


def test_extra_runner_boundary_waiver_is_narrow_and_counted():
    g,ps=validation_fixture();ps[-1].update(event='8/TP',outs_post='3',hr='0',runs='0')
    top=copy.deepcopy(ps[-2]);top.update(inning='10',top_bot='0',vis_home='0',pn='19')
    np=copy.deepcopy(ps[-1]);np.update(inning='10',pn='20',event='NP',pa='0',ab='0',outs_post='0')
    hr=copy.deepcopy(ps[-1]);hr.update(inning='10',pn='21',event='HR',outs_post='0',hr='1',runs='2',br2_pre='runner01')
    ps.extend([top,np,hr]);g.update(field_011='2',field_012='57')
    def validate():return a.validate_plays([a.record('test','',1,g)],[a.record('test','',i+2,p) for i,p in enumerate(ps)],{g['game_id']:['test']})
    q=validate();assert not q['failures'];assert q['counters']['automatic_runner_np_boundary_observed']==1
    hr['br1_pre']='unexpected_runner'
    assert any(f['check']=='base_occupancy_transition' for f in validate()['failures'])


class Response(io.BytesIO):
    status=200;url='https://example.org/data'
    def __init__(self,data):super().__init__(data);self.headers={'Content-Length':str(len(data))}


class Opener:
    def __init__(self,result):self.result=result;self.request=None
    def open(self,req,timeout):
        self.request=req
        if isinstance(self.result,Exception):raise self.result
        return self.result


def test_update_probe_uses_conditional_etag_and_distinguishes_304_from_hash_verification():
    spec={'url':'https://example.org/data','max_bytes':100}
    prev={'etag':'"old"','sha256':digest(b'old')}
    opener=Opener(HTTPError(spec['url'],304,'not modified',{},None))
    result,data=u.probe(spec,prev,100,opener)
    assert result['status']=='not_modified_http304' and data is None
    assert opener.request.get_header('If-none-match')=='"old"'
    result,data=u.probe(spec,prev,100,Opener(Response(b'new')))
    assert result['status']=='changed' and data==b'new'
    assert prev['sha256']==digest(b'old')


def test_update_error_never_becomes_a_valid_empty_dataset():
    spec={'url':'https://example.org/data','max_bytes':100};prev={'sha256':digest(b'old')}
    for result in [Response(b''),HTTPError(spec['url'],403,'forbidden',{},None)]:
        with pytest.raises(CollectionError):u.probe(spec,prev,100,Opener(result))


def test_raw_row_lookup_recovers_additional_columns_from_verified_original(tmp_path,monkeypatch,capsys):
    args=fixture_run(tmp_path,monkeypatch);w.run(args);capsys.readouterr()
    _,_,payload,_=fixture_data();data=payload['retro_plays_2024']
    blobs=args.cache/'blobs';blobs.mkdir(parents=True);(blobs/digest(data)).write_bytes(data)
    args.game_id='HOM202404010';args.play=1
    assert w.source_row(args)==0
    result=json.loads(capsys.readouterr().out)
    assert result['values']['future_field']=='retain-me' and result['source_row']==2


def test_interrupted_acquisition_resumes_without_false_success(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch);base=w.Collector;failed=[False]
    class FailOnce(base):
        def fetch(self,spec):
            if spec['id']=='retro_gl_2024' and not failed[0]:
                failed[0]=True;raise CollectionError('temporary unavailable')
            return super().fetch(spec)
    monkeypatch.setattr(w,'Collector',FailOnce)
    with pytest.raises(CollectionError,match='acquisition failures'):w.run(args)
    assert not (args.output/'current.json').exists()
    assert w.run(args)==0
    with closing(sqlite3.connect(args.output/'ledger.sqlite3')) as db:
        assert [r[0] for r in db.execute('SELECT status FROM runs ORDER BY started_at')]==['failed','committed']
        assert db.execute("SELECT count(*) FROM jobs WHERE status='failed'").fetchone()[0]==1


def test_update_candidates_do_not_promote_and_changed_policy_is_visible(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch);w.run(args);args.offline=False
    pointer=(args.output/'current.json').read_bytes();lock=args.plan.with_name('lock.json').read_bytes()
    monkeypatch.setattr(u.time,'sleep',lambda _:None)
    def observed(spec,previous,remaining):
        data=b'changed policy' if spec['id']=='policy' else None
        return {'status':'changed' if data else 'unchanged_sha256','bytes_received':len(data) if data else 1,
                'sha256':digest(data) if data else previous['sha256'],'http_status':200},data
    monkeypatch.setattr(u,'probe',observed)
    assert u.check_updates(args)==0
    report=json.loads((args.report_dir/'update_check.json').read_text())
    assert report['status']=='changes_detected' and report['promoted'] is False
    assert report['rights_evidence_changes']==['policy']
    assert (args.output/'current.json').read_bytes()==pointer and args.plan.with_name('lock.json').read_bytes()==lock


def test_download_contains_every_snapshot_file_with_matching_hash(tmp_path,monkeypatch):
    args=fixture_run(tmp_path,monkeypatch);w.run(args)
    with zipfile.ZipFile(args.report_dir/'database_bundle.zip') as z:
        info=json.loads(z.read('snapshot.json'))
        for name,sha in info['files'].items():
            assert digest(z.read(name))==sha
        assert digest(z.read('plan.json'))==info['plan_sha256']
        assert digest(z.read('lock.json'))==info['lock_sha256']


def test_update_probe_accounts_for_failed_partial_transfer_and_zero_budget():
    spec={'url':'https://example.org/data','max_bytes':100};prev={'sha256':digest(b'old')}
    response=Response(b'short');response.headers['Content-Length']='9'
    with pytest.raises(CollectionError) as failure:u.probe(spec,prev,100,Opener(response))
    assert failure.value.bytes_received==5
    opener=Opener(Response(b'new'))
    with pytest.raises(CollectionError,match='budget exhausted'):u.probe(spec,prev,0,opener)
    assert opener.request is None


@pytest.mark.parametrize('available',[True,False])
def test_repository_head_discovery_is_separate_from_pinned_bytes_and_sanitizes_errors(monkeypatch,available):
    pinned='a'*40;latest='b'*40
    plan={'artifacts':[{'url':f'https://raw.githubusercontent.com/owner/repository/{pinned}/data.csv'}]*2}
    calls=[]
    def remote(args,**kwargs):
        calls.append(args)
        assert kwargs['capture_output'] and kwargs['timeout']==30
        return Namespace(returncode=0 if available else 1,stdout=latest+'\tHEAD\n',stderr='must not be logged')
    monkeypatch.setattr(u.subprocess,'run',remote)
    results=u.repository_heads(plan)
    assert len(calls)==len(results)==1
    assert results[0]['status']==('new_head_available' if available else 'head_check_unavailable')
    assert 'must not be logged' not in json.dumps(results)
    assert results[0]['pinned_commit']==pinned
