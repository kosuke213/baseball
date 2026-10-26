"""Immutable physical sidecar; never migrates or mutates career/game databases."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import json,sqlite3,os,copy
from ..careers.world import digest
from ..careers.storage import protect
from ..careers.public import validate_public
from .model import Physical,BODY_VERSION

SCHEMA='physical-sidecar-1'

def protected(path):
    p=protect(path);root=Path(__file__).resolve().parents[2]
    for prefix in ('data/research','data_sources'):
        if p.is_relative_to((root/prefix/'stage11').resolve()):raise ValueError('Stage 11 history is protected')
    return p

class PhysicalStore:
    def __init__(self,path,*,world_id=None,created_on=None):
        p=protected(path);new=not p.exists()
        if not new:
            with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as check:
                try:version=check.execute('SELECT value FROM physical_metadata WHERE key="schema"').fetchone()
                except sqlite3.Error:raise ValueError('Existing nonphysical database is preserved')
                if version!=(SCHEMA,):raise ValueError('Unknown physical schema')
        elif not world_id or not created_on:raise ValueError('New sidecar requires explicit world and start date')
        if new:date.fromisoformat(created_on)
        p.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(p)
        if new:
            os.chmod(p,0o600)
            self.db.executescript('''CREATE TABLE physical_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE physical_events(sequence INTEGER PRIMARY KEY,record_json TEXT NOT NULL,sha256 TEXT NOT NULL);''')
            header={'schema':SCHEMA,'world_id':world_id,'created_on':created_on,'body_version':BODY_VERSION}
            self.db.executemany('INSERT INTO physical_metadata VALUES(?,?)',[('schema',SCHEMA),('header',json.dumps(header,sort_keys=True)),('header_sha',digest(header))])
            for table in ('physical_metadata','physical_events'):
                for action in ('UPDATE','DELETE'):
                    self.db.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable physical history'); END")
            self.db.commit()
        self.restore()
        if world_id is not None and self.header['world_id']!=world_id:raise ValueError('World mismatch')

    def close(self):self.db.close()

    def restore(self):
        header=json.loads(self.db.execute('SELECT value FROM physical_metadata WHERE key="header"').fetchone()[0])
        sha=self.db.execute('SELECT value FROM physical_metadata WHERE key="header_sha"').fetchone()[0]
        if digest(header)!=sha or header['body_version']!=BODY_VERSION:raise ValueError('Physical header modified/version mismatch')
        self.header=header;self.now=header['created_on'];self.profiles={};self.weight_values={};self.rows=[];previous=sha
        for seq,text,sha in self.db.execute('SELECT sequence,record_json,sha256 FROM physical_events ORDER BY sequence'):
            r=json.loads(text)
            if seq!=len(self.rows)+1 or r['sequence']!=seq or digest(r)!=sha or r['previous']!=previous or r['on']<self.now or r['version']!=SCHEMA:
                raise ValueError('Physical event history modified')
            pid=r['player_id'];kind=r['kind']
            if kind=='profile_registered':
                p=Physical(**r['details']['physical']).validate()
                if p.player_id!=pid or p.registered_on!=r['on'] or pid in self.profiles:raise ValueError('Invalid physical registration')
                if r['details']['profile']['player_id']!=pid or r['details']['profile']['birth_date']!=p.birth_date:raise ValueError('Physical/core identity mismatch')
                if digest(r['details']['profile'])!=r['details']['core_profile_sha256']:raise ValueError('Core profile fingerprint differs')
                self.profiles[pid]=copy.deepcopy(r['details']);self.weight_values[pid]=p.baseline_weight_kg
            elif kind=='weight_registered':
                if pid not in self.profiles or r['details']['previous_weight_kg']!=self.weight_values[pid]:raise ValueError('Weight prior differs')
                self._weight(r['details']['weight_kg']);self.weight_values[pid]=r['details']['weight_kg']
            elif kind!='clock_advanced':raise ValueError('Unknown physical event type')
            self.now=r['on'];previous=sha;self.rows.append(r)
        self.previous=previous
        return self

    def _append(self,kind,on,pid,details):
        date.fromisoformat(on)
        if on<self.now:raise ValueError('Cannot backdate physical history')
        r={'sequence':len(self.rows)+1,'kind':kind,'on':on,'player_id':pid,'details':details,'previous':self.previous,'version':SCHEMA}
        with self.db:self.db.execute('INSERT INTO physical_events VALUES(?,?,?)',(r['sequence'],json.dumps(r,ensure_ascii=False,sort_keys=True),digest(r)))
        self.restore()

    def advance(self,on):
        if on!=self.now:self._append('clock_advanced',on,None,{})

    def register(self,physical,profile):
        physical.validate();profile.validate()
        if physical.player_id!=profile.player_id or physical.birth_date!=profile.birth_date:raise ValueError('Body/core mismatch')
        if (physical.source_position=='P')!=(profile.role=='pitcher'):raise ValueError('Body/core pitching role differs')
        if profile.role=='batter' and profile.position not in (physical.source_position,'DH'):raise ValueError('Body/core position differs')
        if physical.registered_on!=self.now or profile.player_id in self.profiles:raise ValueError('Registration requires current date and new ID')
        self._append('profile_registered',self.now,profile.player_id,{'physical':asdict(physical),'profile':asdict(profile),
            'core_profile_sha256':digest(asdict(profile))})

    @staticmethod
    def _weight(value):
        import math
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid registered weight')

    def register_weight(self,pid,value,on,*,reason,version='manual-weight-registration-1'):
        self._weight(value)
        if pid not in self.profiles or on!=self.now or type(reason) is not str or type(version) is not str or not reason or not version:
            raise ValueError('Committed date, player and textual reason/version required')
        self._append('weight_registered',on,pid,{'weight_kg':value,'previous_weight_kg':self.weight_values[pid],
                    'year':int(on[:4]),'reason':reason,'model_version':version,'measured_real_player_value':False})

    def at(self,pid,on):
        self.restore();date.fromisoformat(on)
        if not self.header['created_on']<=on<=self.now:raise ValueError('Only committed dates may be viewed')
        base=None;weight=None;years={};events=[]
        for r in self.rows:
            if r['player_id']!=pid or r['on']>on:continue
            if r['kind']=='profile_registered':
                base=Physical(**r['details']['physical']);weight=base.baseline_weight_kg;years[str(int(r['on'][:4]))]=weight
            elif r['kind']=='weight_registered':
                weight=r['details']['weight_kg'];years[str(r['details']['year'])]=weight
                events.append({'on':r['on'],'weight_kg':weight,'reason':r['details']['reason'],'version':r['details']['model_version']})
        if base is None:raise KeyError(pid)
        return {'player_id':pid,'birth_date':base.birth_date,'height_cm':base.height_cm,'baseline_weight_kg':base.baseline_weight_kg,
                'registered_weight_kg':weight,'annual_registered_weights':years,'weight_changes':events,
                'registered_on':base.registered_on,'origin':base.origin,'body_version':base.body_version,
                'calibration_sha256':base.calibration_sha256,'as_of':on}

PHYSICAL_FIELDS=frozenset(('player_id','birth_date','height_cm','baseline_weight_kg','registered_weight_kg','annual_registered_weights',
    'weight_changes','registered_on','origin','body_version','calibration_sha256','as_of'))

def public_player(core_public,physical_view=None):
    # The legacy validator fixes keys and numerical ratings/counts. Tighten
    # textual metadata at this new boundary as well, so an accidental nested
    # administrator object cannot be hidden in a name or statistic identity.
    for key in ('player_id','name','team_id','role','position','throws','bats','nationality','availability',
                'career_status','rating_observed_on','as_of'):
        if type(core_public.get(key)) is not str:raise ValueError('Public player metadata must be plain text')
    if type(core_public.get('ratings')) is not dict or type(core_public.get('season_stats')) is not list or type(core_public.get('career_stats')) is not dict:
        raise ValueError('Invalid public evaluation/statistic container')
    for key in ('age','entry_year','injury_history_count'):
        if type(core_public.get(key)) is not int or core_public[key]<0:raise ValueError('Invalid public age/year/count')
    import math
    uncertainty=core_public.get('rating_uncertainty');severity=core_public.get('current_injury_severity')
    if type(uncertainty) not in (int,float) or not math.isfinite(uncertainty) or uncertainty<0:raise ValueError('Invalid public uncertainty')
    if severity is not None and (type(severity) is not int or severity not in (1,2,3)):raise ValueError('Invalid public injury severity')
    date.fromisoformat(core_public['as_of']);date.fromisoformat(core_public['rating_observed_on'])
    if core_public['entry_year']>int(core_public['as_of'][:4]) or core_public['rating_observed_on']>core_public['as_of']:raise ValueError('Future public profile metadata')
    for stats in [*core_public['season_stats'],core_public['career_stats']]:
        if type(stats) is not dict:raise ValueError('Invalid public statistics')
        for key in ('season_id','player_id','team_id','kind','ip_display'):
            if key in stats and stats[key] is not None and type(stats[key]) is not str:raise ValueError('Private object in public statistic metadata')
    validate_public(core_public)
    if physical_view is not None:
        if set(physical_view)!=PHYSICAL_FIELDS or physical_view['as_of']!=core_public['as_of']:raise ValueError('Unknown/private or differently dated physical field')
        if physical_view['player_id']!=core_public['player_id']:raise ValueError('Physical/core identity differs')
        for key in ('player_id','birth_date','registered_on','origin','body_version','calibration_sha256','as_of'):
            if type(physical_view[key]) is not str:raise ValueError('Textual physical metadata required')
        for key in ('birth_date','registered_on','as_of'):date.fromisoformat(physical_view[key])
        if not physical_view['birth_date']<=physical_view['registered_on']<=physical_view['as_of']:raise ValueError('Future/inconsistent physical registration')
        if physical_view['body_version']!=BODY_VERSION or physical_view['origin'] not in ('fictional_generation_from_sampled_distribution','explicit_late_fictional_supplement','stock_age_conditioned_proxy'):
            raise ValueError('Unknown body provenance/version')
        from ..careers.domain import age_on
        if age_on(physical_view['birth_date'],physical_view['as_of'])!=core_public['age']:raise ValueError('Physical/core age differs')
        if not all(set(e)=={'on','weight_kg','reason','version'} for e in physical_view['weight_changes']):raise ValueError('Unexpected physical event fields')
        for e in physical_view['weight_changes']:
            date.fromisoformat(e['on']);PhysicalStore._weight(e['weight_kg'])
            if type(e['reason']) is not str or type(e['version']) is not str or e['on']>physical_view['as_of']:raise ValueError('Invalid/future weight event')
        for k,v in physical_view['annual_registered_weights'].items():
            if type(k) is not str or not k.isdigit() or int(k)>int(physical_view['as_of'][:4]):raise ValueError('Invalid/future annual weight year')
            PhysicalStore._weight(v)
        for key in ('height_cm','baseline_weight_kg','registered_weight_kg'):PhysicalStore._weight(physical_view[key])
    return {'player':copy.deepcopy(core_public),'physical':copy.deepcopy(physical_view),
            'profile_extension_status':'recorded' if physical_view else 'not_recorded_in_legacy_history'}
