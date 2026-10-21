"""Streaming typed warehouse transforms. Originals remain in the content-addressed cache."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime
import io
import itertools
import json
from pathlib import Path
import re
import sqlite3
import uuid

from . import adapters as a
from .fetch import CollectionError

SCHEMA = Path(__file__).with_name('warehouse_schema.sql')
RULE_CONTEXT = {
    'league': 'MLB', 'game_type': 'regular', 'seasons': [2023, 2024, 2025],
    'automatic_runner': 'At the start of each half-inning after the ninth, a runner is placed on second.',
    'evidence_url': 'https://www.mlb.com/glossary/rules/designated-runner',
    'reviewed_on': '2026-10-21',
    'reviewed_document_sha256': '7a063334b7634a5c55ff86877861550121f2420f25be21480c76ad40c064a633',
    'scope': 'Recognize placement after leading NP rows; not independent validation of which runner is eligible.',
}
UNITS = dict(zip(a.WEATHER_COLUMNS[1:], ['hPa','hPa','mm','degC','degC','hPa','percent','m/s','compass','h','MJ/m2','cm','cm','source_code','source_code','km']))
IDS = {'key_retro':'retrosheet','key_mlbam':'mlbam','key_npb':'npb','key_bbref':'bbref',
       'key_bbref_minors':'bbref_minors','key_fangraphs':'fangraphs','key_wikidata':'wikidata'}
PLAY_COLUMNS = ('game_id','play_number','inning','half','batting_side','event_date','batting_team_id','pitching_team_id',
                'park_id','batter_retro_id','pitcher_retro_id','event_raw','pbp_type','visiting_score_pre','home_score_pre',
                'outs_pre','outs_post','runs','runner1_pre','runner2_pre','runner3_pre','runner1_post','runner2_post','runner3_post',
                'balls','strikes','count_raw','pitches_raw','pitch_count','plate_appearance','at_bat','single','double','triple',
                'home_run','walk','strikeout','intentional_walk','batter_hand','pitcher_hand','artifact_id','source_row')


def js(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)


def integer(text, *, optional=False):
    if optional and text == '':
        return None
    if not isinstance(text,str) or not re.fullmatch(r'-?\d+',text):
        raise CollectionError('Integer field is missing, flagged, or malformed; no implicit imputation')
    return int(text)


def date(text):
    return datetime.strptime(text,'%Y%m%d').date().isoformat()


def entity(kind, code):
    if not code or ':' in code or not re.fullmatch(r'[A-Za-z0-9]+',code):
        raise CollectionError('Missing or invalid source entity ID')
    return f'retrosheet:{kind}:{code}'


def remember_schema(db, artifact, member, columns, count):
    db.execute('INSERT INTO source_schemas VALUES(?,?,?,?)',(artifact,member,js(columns),count))


def ensure_park(db, code, artifact, row):
    key=entity('park',code)
    db.execute("INSERT OR IGNORE INTO parks(park_id,namespace,source_code,metadata_status,artifact_id,source_row) VALUES(?,'retrosheet',?,'unresolved',?,?)",(key,code,artifact,row))
    return key


def park_reference(db, data):
    rows=list(a.csv_rows(io.StringIO(data.decode('utf-8-sig'),newline='')))
    if not rows or not {'PARKID','NAME','CITY','STATE','START','END'} <= rows[0][1].keys():
        raise CollectionError('Park reference schema changed or empty')
    for n,v in rows:
        db.execute('INSERT INTO parks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(
            entity('park',v['PARKID']),'retrosheet',v['PARKID'],v['NAME'] or None,v['CITY'] or None,
            v['STATE'] or None,v['START'] or None,v['END'] or None,'documented','retro_park_codes',n,js(v)))
    remember_schema(db,'retro_park_codes','CSV',list(rows[0][1]),len(rows))


def load_games(db, data, year, needed):
    artifact=f'retro_gl_{year}';member=f'gl{year}.txt'
    columns=[f'field_{n:03}' for n in range(1,162)]
    originals={}
    for n,g in a.zipped_csv(data,member,header=columns):
        gid=g['field_007']+g['field_001']+g['field_002']
        if not g['field_001'].startswith(str(year)):
            raise CollectionError('Game Log year differs from its partition')
        g['game_id']=gid
        key=entity('game',gid)
        for code,league in [(g['field_004'],g['field_005']),(g['field_007'],g['field_008'])]:
            team=entity('team',code)
            db.execute("INSERT OR IGNORE INTO teams VALUES(?,'retrosheet',?,NULL)",(team,code))
            db.execute('INSERT OR IGNORE INTO team_seasons VALUES(?,?,?,?,?)',(team,year,league,artifact,n))
            if db.execute('SELECT league_code FROM team_seasons WHERE team_id=? AND season=?',(team,year)).fetchone()[0] != league:
                raise CollectionError('Inconsistent league code within team-season')
        park=ensure_park(db,g['field_017'],artifact,n)
        db.execute('INSERT INTO games VALUES('+','.join(['?']*21)+')',(
            key,gid,year,date(g['field_001']),g['field_002'],entity('team',g['field_004']),entity('team',g['field_007']),park,
            integer(g['field_010']),integer(g['field_011']),integer(g['field_012']),integer(g['field_018'],optional=True),
            integer(g['field_019'],optional=True),g['field_020'],g['field_021'],g['field_014'] or None,g['field_161'],g['field_160'],
            artifact,n,js(g)))
        for side,start,teamfield in [(0,22,'field_004'),(1,50,'field_007')]:
            stats=[integer(g[f'field_{x:03}'],optional=True) for x in [start,start+1,start+2,start+3,start+4,start+9,start+11]]
            db.execute('INSERT INTO game_team_stats VALUES(?,?,?,?,?,?,?,?,?,?)',(key,side,entity('team',g[teamfield]),*stats))
        for x in [*range(78,105,2),*range(106,160,3)]:
            if g[f'field_{x:03}']:
                needed.add(g[f'field_{x:03}'])
        originals[gid]=a.record(artifact,member,n,g)
    if not originals:
        raise CollectionError('Empty Game Logs partition')
    remember_schema(db,artifact,member,columns,len(originals))
    return originals


def play_tuple(db, p, n, artifact):
    return (entity('game',p['gid']),integer(p['pn']),integer(p['inning']),integer(p['top_bot']),integer(p['vis_home']),
            date(p['date']),entity('team',p['batteam']),entity('team',p['pitteam']),ensure_park(db,p['site'],artifact,n),
            p['batter'],p['pitcher'],p['event'],p['pbp'],integer(p['score_v']),integer(p['score_h']),
            integer(p['outs_pre']),integer(p['outs_post']),integer(p['runs']),
            *(p[f'br{b}_{state}'] or None for state in ['pre','post'] for b in (1,2,3)),
            integer(p['balls'],optional=True),integer(p['strikes'],optional=True),p['count'],p['pitches'],integer(p['nump'],optional=True),
            *(integer(p[k]) for k in ['pa','ab','single','double','triple','hr','walk','k','iw']),
            p['bathand'],p['pithand'],artifact,n)


def batting_checks(log, seq):
    failures=[]
    for side,start in [(0,22),(1,50)]:
        rows=[r['values'] for r in seq if r['values']['vis_home']==str(side)]
        for label,source,column in [('at_bats','ab',start),('home_runs','hr',start+4),('walks','walk',start+9),('strikeouts','k',start+11)]:
            actual=sum(integer(p[source]) for p in rows)
            expected=integer(log['values'][f'field_{column:03}'])
            if actual != expected:
                failures.append({'check':'batting_'+label,'side':side,'expected':expected,'observed':actual})
        hits=sum(integer(p[k]) for p in rows for k in ['single','double','triple','hr'])
        expected=integer(log['values'][f'field_{start+1:03}'])
        if hits != expected:
            failures.append({'check':'batting_hits','side':side,'expected':expected,'observed':hits})
    return failures


def load_plays(db, data, year, logs, needed, progress):
    artifact=f'retro_plays_{year}';member=f'{year}plays.csv'
    scanned=imported=0;columns=None
    statement='INSERT INTO plays('+','.join(PLAY_COLUMNS)+') VALUES('+','.join('?' for _ in PLAY_COLUMNS)+')'
    required={'gid','pn','inning','top_bot','vis_home','score_v','score_h','runs','outs_pre','outs_post','date','gametype','pbp'}
    for gid,group in itertools.groupby(a.zipped_csv(data,member),key=lambda pair:pair[1]['gid']):
        raw=list(group);scanned+=len(raw)
        if columns is None:
            columns=list(raw[0][1])
            if not required <= set(columns):
                raise CollectionError('Parsed plays required columns missing')
        kinds={v['gametype'] for _,v in raw}
        if kinds != {'regular'} or gid not in logs:
            reason='non_regular_season' if kinds != {'regular'} else 'missing_game_log'
            db.execute('INSERT INTO excluded_game_groups VALUES(?,?,?,?,?)',(artifact,gid,','.join(sorted(kinds)),reason,len(raw)))
            continue
        seq=[a.record(artifact,member,n,v) for n,v in raw]
        validation=a.validate_plays([logs[gid]],seq,{gid:['all_regular_games']})
        validation['failures'].extend(batting_checks(logs[gid],seq))
        for n,v in raw:
            needed.update(v[k] for k in ['batter','pitcher',*(f'br{b}_{s}' for s in ['pre','post'] for b in (1,2,3))] if v[k])
        db.executemany(statement,[play_tuple(db,v,n,artifact) for n,v in raw])
        status='review_required' if validation['failures'] else 'pass'
        db.execute('INSERT INTO game_checks VALUES(?,?,?,?,?)',(entity('game',gid),status,len(raw),js(validation['counters']),js(validation['failures'])))
        imported+=len(raw)
        if imported%25000 < len(raw):
            progress(f'{year}: {imported:,} regular-season play records')
    if not scanned or not imported:
        raise CollectionError('Empty plays partition or no matching regular-season records')
    remember_schema(db,artifact,member,columns,scanned)
    for gid in logs:
        db.execute("INSERT OR IGNORE INTO game_checks VALUES(?,'missing_plays',0,'{}','[]')",(entity('game',gid),))
    return scanned,imported


def load_people(db, payloads, needed):
    scanned=retained=0
    for artifact in sorted(k for k in payloads if k.startswith('register_') and k != 'register_readme'):
        count=0;columns=None
        for n,p in a.csv_rows(io.StringIO(payloads[artifact].decode('utf-8-sig'),newline='')):
            count+=1;scanned+=1
            columns=columns or list(p)
            if not {'key_uuid','key_retro','key_npb'} <= p.keys():
                raise CollectionError('Register schema changed')
            if p['key_retro'] not in needed and not p['key_npb']:
                continue
            u=str(uuid.UUID(p['key_uuid']))
            key='chadwick:person:'+u
            db.execute('INSERT INTO people VALUES(?,?,?,?,?,?,?,?)',(key,u,p['name_first'],p['name_last'],integer(p['birth_year'],optional=True),artifact,n,js(p)))
            for field,namespace in IDS.items():
                if p[field]:
                    db.execute('INSERT INTO identifiers VALUES(?,?,?,?,?)',(namespace,p[field],key,artifact,n))
            retained+=1
        if not count:
            raise CollectionError('Empty Register shard')
        remember_schema(db,artifact,'data/people-'+artifact[-1]+'.csv',columns,count)
    for retro in sorted(needed):
        matches=db.execute("SELECT person_id FROM identifiers WHERE namespace='retrosheet' AND identifier=?",(retro,)).fetchall()
        status='matched' if len(matches)==1 else 'unmatched' if not matches else 'ambiguous'
        db.execute('INSERT INTO player_matches VALUES(?,?,?,?)',(retro,status,matches[0][0] if status=='matched' else None,len(matches)))
    return scanned,retained


def load_context(db, payloads):
    rows=a.japan_board(payloads['jpl_draft_2026'])
    for r in rows:
        p=r['values']
        db.execute('INSERT INTO secondary_claims VALUES(?,?,?,?,?,?,?,?)',(
            'jpl:2026-draft:'+p['rank'],p['name_jp'],'secondary_draft_board','no_external_id',None,r['artifact_id'],r['source_row'],js(p)))
    remember_schema(db,'jpl_draft_2026','boards/2026-npb-draft-board.csv',list(rows[0]['values']),len(rows))
    db.execute("INSERT INTO stations VALUES('jma:station:47662','jma','47662','東京','Asia/Tokyo')")
    weather=a.weather(payloads['jma_tokyo_20240329'])
    for r in weather:
        v=r['values']
        for metric,unit in UNITS.items():
            raw=v[metric]
            numeric=bool(re.fullmatch(r'-?\d+(?:\.\d+)?',raw))
            categorical = metric in ('wind_direction','weather','cloud_cover') and raw not in ('','--','///','×')
            status='numeric' if numeric else 'empty' if raw=='' else 'categorical' if categorical else 'symbol_or_flagged'
            db.execute('INSERT INTO weather_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)',(
                'jma:station:47662',v['timestamp_utc'],v['timestamp_jst'],metric,unit,float(raw) if numeric else None,
                raw,status,js(v['cell_attributes'][metric]),r['artifact_id'],r['source_row']))
    remember_schema(db,'jma_tokyo_20240329','HTML#tablefix1',list(weather[0]['values']),len(weather))


def quality(db, scans, metas):
    tables=['games','plays','analysis_plays','teams','team_seasons','parks','people','identifiers','player_matches',
            'secondary_claims','stations','weather_observations','game_checks','excluded_game_groups']
    counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
    by_year=[dict(zip(['season','games','play_rows'],r)) for r in db.execute('SELECT g.season,count(*),sum(q.play_rows) FROM games g JOIN game_checks q USING(game_id) GROUP BY g.season ORDER BY g.season')]
    states=dict(db.execute('SELECT status,count(*) FROM game_checks GROUP BY status'))
    failures=[{'game_id':g,'failures':json.loads(f)} for g,f in db.execute("SELECT game_id,failures_json FROM game_checks WHERE status!='pass' ORDER BY game_id")]
    player_states=dict(db.execute('SELECT status,count(*) FROM player_matches GROUP BY status'))
    referenced_players={r[0] for r in db.execute('SELECT batter_retro_id FROM plays UNION SELECT pitcher_retro_id FROM plays')}
    player_only=Counter()
    for retro in referenced_players:
        player_only[db.execute('SELECT status FROM player_matches WHERE retrosheet_id=?',(retro,)).fetchone()[0]]+=1
    unresolved=[{'park_id':r[0],'source_code':r[1]} for r in db.execute("SELECT park_id,source_code FROM parks WHERE metadata_status='unresolved' ORDER BY park_id")]
    exclusions=[dict(zip(['game_type','reason','games','rows'],r)) for r in db.execute('SELECT game_type,reason,count(*),sum(row_count) FROM excluded_game_groups GROUP BY game_type,reason ORDER BY game_type,reason')]
    counters=Counter()
    for row in db.execute('SELECT counters_json FROM game_checks'):
        counters.update(json.loads(row[0]))
    missing_regular=sum(r['games'] for r in exclusions if r['reason']=='missing_game_log')
    status='validated_with_exclusions' if failures or player_states.get('ambiguous') or missing_regular else 'pass'
    return {'schema_version':1,'stages':[3,4],'status':status,'counts':counts,'by_year':by_year,'scanned_rows':scans,
            'raw_bytes':sum(m['bytes'] for m in metas),'artifact_count':len(metas),'checks':dict(counters),
            'game_validation_status':states,'game_failures':failures,'identity_status_all_roles':player_states,
            'identity_status_batters_pitchers':dict(player_only),'unresolved_park_metadata':unresolved,
            'excluded_input_groups':exclusions,
            'weather_parse_status':dict(db.execute('SELECT parse_status,count(*) FROM weather_observations GROUP BY parse_status')),
            'integrity_check':db.execute('PRAGMA integrity_check').fetchone()[0],
            'foreign_key_errors':db.execute('PRAGMA foreign_key_check').fetchall(),
            'limits':['Retrosheet parsed plays and Game Logs share provenance; these are consistency checks, not independent verification.',
                      'Raw artifacts preserve every original column; typed plays expose selected defined fields with exact source-row references.',
                      'Park names are as published in an older reference, not historical season-specific names. Unresolved codes remain explicit.',
                      'No join from JPL names or from Tokyo weather to MLB parks; no imputation, model training or calibration.',
                      'analysis_plays excludes games failing validation and non-full PBP. Raw typed records remain available.',
                      'Only 2023-2025 MLB regular extra innings recognize leading NP -> runner-on-second placement. The count is explicit; runner eligibility is not independently verified.']}


def build(path, plan, payloads, metas, metadata, progress=print):
    scans={};needed=set()
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        for key,value in metadata.items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,js(value)))
        for m in metas:
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(m['id'],m['sha256'],m['bytes'],js(m)))
        park_reference(db,payloads['retro_park_codes'])
        for year in plan['years']:
            progress(f'Importing {year}')
            logs=load_games(db,payloads[f'retro_gl_{year}'],year,needed)
            # Keep log disagreements in the per-game quarantine too.
            lines=a.validate_games(list(logs.values()))['line_score_failures']
            scanned,imported=load_plays(db,payloads[f'retro_plays_{year}'],year,logs,needed,progress)
            scans[str(year)]={'game_logs':len(logs),'all_plays':scanned,'regular_plays':imported}
            for failure in lines:
                key=entity('game',failure['game_id'])
                old=json.loads(db.execute('SELECT failures_json FROM game_checks WHERE game_id=?',(key,)).fetchone()[0])
                db.execute("UPDATE game_checks SET status='review_required',failures_json=? WHERE game_id=?",(js([*old,{'check':'line_score',**failure}]),key))
        scanned,retained=load_people(db,payloads,needed)
        scans['register']={'scanned':scanned,'retained':retained}
        load_context(db,payloads)
        report=quality(db,scans,metas)
        if report['integrity_check'] != 'ok' or report['foreign_key_errors']:
            raise CollectionError('Warehouse integrity/foreign-key validation failed')
        return report
