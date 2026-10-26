"""Private append-only career DB; public exports require an explicit whitelist."""
from dataclasses import asdict
from pathlib import Path
import hashlib,json,sqlite3,os

from ..stability.storage import HistoryStore as GameHistoryStore,replay_game
from ..calibrated.rules import canonical
from .domain import Profile,Talent,state_from_dict,state_dict,projected
from .world import World,digest,CAREER_VERSION

SCHEMA='''
CREATE TABLE career_worlds(world_id TEXT PRIMARY KEY,header_json TEXT NOT NULL,header_sha256 TEXT NOT NULL);
CREATE TABLE career_events(world_id TEXT REFERENCES career_worlds,sequence INTEGER,event_id TEXT,event_date TEXT,player_id TEXT,
 kind TEXT,record_json TEXT NOT NULL,record_sha256 TEXT NOT NULL,PRIMARY KEY(world_id,sequence),UNIQUE(world_id,event_id));
CREATE INDEX career_by_player_date ON career_events(world_id,player_id,event_date,sequence);
CREATE TABLE pregame_states(world_id TEXT REFERENCES career_worlds,game_id TEXT REFERENCES games,player_id TEXT,
 snapshot_json TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,PRIMARY KEY(world_id,game_id,player_id));
CREATE TABLE career_seasons(world_id TEXT REFERENCES career_worlds,season_id TEXT,completed_on TEXT,report_json TEXT NOT NULL,
 report_sha256 TEXT NOT NULL,PRIMARY KEY(world_id,season_id));
'''


def protect(path):
    root=Path(__file__).resolve().parents[2];path=Path(path).resolve()
    for prefix in ('data/research','data_sources'):
        for stage in ('pilot','warehouse','stage5','stage6','stage7','stage8','stage9','stage10'):
            old=root/prefix/stage
            if path.is_relative_to(old.resolve()):raise ValueError('Previous stage outputs are protected')
    return path


class CareerStore(GameHistoryStore):
    """Administrator-only local repository, not a public API or auth service."""
    def __init__(self,path):
        path=protect(path);new=not path.exists()
        if not new:
            with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
                try:version=db.execute('SELECT value FROM metadata WHERE key="career_schema"').fetchone()
                except sqlite3.Error:raise ValueError('Not a private career database')
                if version!=('careers-history-1',):raise ValueError('Existing database is preserved; create a new career DB')
        super().__init__(path)
        if new:
            os.chmod(path,0o600)
            self.db.executescript(SCHEMA)
            self.db.execute('INSERT INTO metadata VALUES(?,?)',('career_schema','careers-history-1'))
            self.db.execute('INSERT INTO metadata VALUES(?,?)',('privacy','administrator_private; never publish as public data'))
            for table in ('career_worlds','career_events','pregame_states','career_seasons'):
                for action in ('UPDATE','DELETE'):
                    self.db.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable career history'); END")
            self.db.commit()

    def _insert_game(self,game):
        if not game.journal or game.status=='in_progress':raise ValueError('Complete terminal game history required')
        result=game.result();rows=game.journal.rows
        if canonical(result)!=canonical(replay_game(rows)):raise ValueError('Game replay mismatch')
        sha=digest({'result':result,'journal':rows})
        existing=self.db.execute('SELECT payload_sha256 FROM games WHERE game_id=?',(game.game_id,)).fetchone()
        if existing:
            if existing!=(sha,):raise ValueError('Immutable game conflict')
            return False
        self.db.execute('INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(game.game_id,result['game_date'],*result['team_ids'],result['status'],
            *result['score'],result['model_version'],result['rules_version'],result['seed'],sha,canonical(result)))
        for kind in ('batting','pitching'):
            for pid,s in result[kind].items():
                self.db.execute('INSERT INTO appearances VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(game.game_id,pid,s['team_id'],kind,s.get('pa'),s.get('ab'),s['h'],s['hr'],s['r'],s.get('rbi'),s.get('outs'),canonical(s)))
        self.db.executemany('INSERT INTO journal_events VALUES(?,?,?)',((game.game_id,i,canonical(r)) for i,r in enumerate(rows)))
        return True

    def commit(self,world,*,game=None,snapshots=(),season_id=None,scheduled_number=None):
        pending=world.events[world.committed:]
        existing=self.db.execute('SELECT header_sha256 FROM career_worlds WHERE world_id=?',(world.world_id,)).fetchone()
        if existing and existing!=(digest(world.header),):raise ValueError('World ID/seed conflict')
        with self.db:
            if not existing:self.db.execute('INSERT INTO career_worlds VALUES(?,?,?)',(world.world_id,canonical(world.header),digest(world.header)))
            last=self.db.execute('SELECT sequence,record_sha256 FROM career_events WHERE world_id=? ORDER BY sequence DESC LIMIT 1',(world.world_id,)).fetchone()
            expected_seq=last[0]+1 if last else 1;previous=last[1] if last else digest(world.header)
            if game:
                game.model.validate_game_date(game.request['game_date'])
                if canonical(sorted((asdict(s) for s in snapshots),key=lambda s:s['player_id']))!=canonical(sorted((asdict(s) for s in game.model.snapshots.values()),key=lambda s:s['player_id'])):
                    raise ValueError('Saved pregame inputs differ from the probability adapter')
                self._insert_game(game)
                for snap in snapshots:
                    value=asdict(snap);text=canonical(value);sha=digest(value)
                    old=self.db.execute('SELECT snapshot_sha256 FROM pregame_states WHERE world_id=? AND game_id=? AND player_id=?',(world.world_id,game.game_id,snap.player_id)).fetchone()
                    if old and old!=(sha,):raise ValueError('Pregame snapshot conflict')
                    if not old:self.db.execute('INSERT INTO pregame_states VALUES(?,?,?,?,?)',(world.world_id,game.game_id,snap.player_id,text,sha))
                if season_id:
                    old=self.db.execute('SELECT game_id FROM season_games WHERE season_id=? AND scheduled_number=?',(season_id,scheduled_number)).fetchone()
                    if old and old!=(game.game_id,):raise ValueError('Schedule slot conflict')
                    if not old:self.db.execute('INSERT INTO season_games VALUES(?,?,?)',(season_id,scheduled_number,game.game_id))
            for row in pending:
                e=row['event']
                if e['sequence']!=expected_seq or e['previous']!=previous or digest(e)!=row['hash']:raise ValueError('Career chain mismatch before save')
                self.db.execute('INSERT INTO career_events VALUES(?,?,?,?,?,?,?,?)',(world.world_id,e['sequence'],e['event_id'],e['event_date'],e['player_id'],e['kind'],canonical(e),row['hash']))
                previous=row['hash'];expected_seq+=1
        world.committed=len(world.events)

    def restore(self,world_id):
        row=self.db.execute('SELECT header_json,header_sha256 FROM career_worlds WHERE world_id=?',(world_id,)).fetchone()
        if not row:raise KeyError(world_id)
        header=json.loads(row[0])
        if digest(header)!=row[1] or header['career_version']!=CAREER_VERSION:raise ValueError('World header/version mismatch')
        world=World(world_id,header['created_on'],header['private_root_seed'],header['team_ids'])
        for seq,record,sha in self.db.execute('SELECT sequence,record_json,record_sha256 FROM career_events WHERE world_id=? ORDER BY sequence',(world_id,)):
            e=json.loads(record);pid=e['player_id'];before=world.states.get(pid)
            if seq!=len(world.events)+1 or e['previous']!=world.previous or digest(e)!=sha or e['career_version']!=CAREER_VERSION:
                raise ValueError('Career event chain was modified')
            if e['before_sha256']!=(digest(state_dict(before)) if before else None):raise ValueError('Career prior state mismatch')
            if e['kind']=='enrolment':
                details=e['details'];p=Profile(**details['profile']).validate()
                if pid in world.profiles:raise ValueError('Duplicate player enrolment')
                world.profiles[pid]=p;world.talents[pid]=Talent(**details['private_talent']).validate(p);world.entry_abilities[pid]=details['entry_abilities']
            if e['after']:world.states[pid]=state_from_dict(e['after']).validate(world.profiles[pid])
            if e['kind']=='game_applied':world.applied_games.add(e['details']['game_id'])
            if e['kind']=='development_completed':world.grown_years.add(e['details']['year'])
            world.now=max(world.now,e['event_date']);world.previous=sha;world.events.append({'event':e,'hash':sha});world.event_ids.add(e['event_id'])
        world.committed=len(world.events)
        return world

    def state_at(self,world_id,pid,on):
        world=self.restore(world_id)
        if on>world.now or on<world.created_on:raise ValueError('Date is future or before simulated history')
        row=self.db.execute('SELECT record_json FROM career_events WHERE world_id=? AND player_id=? AND event_date<=? ORDER BY sequence DESC LIMIT 1',(world_id,pid,on)).fetchone()
        if not row:raise KeyError(pid)
        return projected(state_from_dict(json.loads(row[0])['after']),on)

    def save_season(self,world_id,season_id,on,report):
        text=canonical(report);sha=digest(report)
        row=self.db.execute('SELECT report_sha256 FROM career_seasons WHERE world_id=? AND season_id=?',(world_id,season_id)).fetchone()
        if row:
            if row!=(sha,):raise ValueError('Immutable season conflict')
            return False
        with self.db:self.db.execute('INSERT INTO career_seasons VALUES(?,?,?,?,?)',(world_id,season_id,on,text,sha))
        return True

    def seasons_at(self,world_id,on):
        reports=[]
        for text,sha in self.db.execute('SELECT report_json,report_sha256 FROM career_seasons WHERE world_id=? AND completed_on<=? ORDER BY completed_on,season_id',(world_id,on)):
            report=json.loads(text)
            if digest(report)!=sha:raise ValueError('Season aggregate modified')
            reports.append(report)
        return reports


    def states_at(self,world_id,on):
        world=self.restore(world_id)
        if on>world.now or on<world.created_on:raise ValueError('Only committed simulated dates are readable')
        rows=self.db.execute("""SELECT player_id,record_json FROM (
            SELECT player_id,record_json,row_number() OVER(PARTITION BY player_id ORDER BY sequence DESC) rn
            FROM career_events WHERE world_id=? AND player_id IS NOT NULL AND event_date<=?) WHERE rn=1""",(world_id,on))
        return world,{pid:projected(state_from_dict(json.loads(text)['after']),on) for pid,text in rows}
