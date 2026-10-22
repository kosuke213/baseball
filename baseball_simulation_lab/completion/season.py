"""Integration-season aggregation, never padding unplayed games."""
from collections import Counter
from pathlib import Path

from data_collection.fetch import write_json
from ..fullgame.league import Standings, validate_schedule, league_gate
from .engine import Game, fictional_team
from .rules import GameRules
from .storage import HistoryStore


class Season:
    def __init__(self, team_ids):
        self.standings=Standings(team_ids); self.players={}; self.results={}; self.unknown_decisions=set()

    def add(self, result):
        if not result['record_integrity']['passed']:raise ValueError('Inconsistent game cannot enter season')
        for kind in ('batting','pitching'):
            for pid,s in result[kind].items():
                previous=self.players.get(kind+':'+pid)
                if previous and previous['team_id']!=s['team_id']:
                    raise ValueError('Season team transfer requires an explicit roster policy')
                if any(v is not None and (type(v) is not int or v < 0) for k,v in s.items() if k not in ('team_id','ip_display')):
                    raise ValueError('Non-count season statistic')
        # Standings rejects duplicate or failed games before any player aggregation.
        self.standings.add(result)
        self.results[result['game_id']]=result
        for kind in ('batting','pitching'):
            for pid,s in result[kind].items():
                key=kind+':'+pid; row=self.players.setdefault(key,{'player_id':pid,'kind':kind,'team_id':s['team_id'],'games':0})
                if row['team_id']!=s['team_id']:raise ValueError('Season team transfer requires an explicit roster policy')
                row['games']+=1
                for field,value in s.items():
                    if field in ('team_id','ip_display'):continue
                    if value is not None and type(value) is not int:raise ValueError('Non-count season statistic')
                    row[field]=None if value is None or (field in row and row[field] is None) else row.get(field,0)+value
        if result['pitcher_decisions']['status'].startswith('manual'):
            self.unknown_decisions.update(result['pitching'])
        for pid,field in ((result['pitcher_decisions']['winner'],'w'),(result['pitcher_decisions']['loser'],'l')):
            if pid:self.players['pitching:'+pid][field]=self.players['pitching:'+pid].get(field,0)+1

    def export(self):
        players=[]
        for _,row in sorted(self.players.items()):
            r=dict(row)
            if r['kind']=='pitching':
                r['ip_display']=f'{r["outs"]//3}.{r["outs"]%3}'
                r.setdefault('w',0);r.setdefault('l',0)
                if r['player_id'] in self.unknown_decisions:r['w']=None;r['l']=None
            players.append(r)
        return {'games':len(self.results),'standings':self.standings.rows(),'players':players}


def run_league(model, output, fixture, config, validation):
    if not league_gate(validation):raise ValueError('League start gate failed')
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    ids=sorted({g['away'] for g in fixture}|{g['home'] for g in fixture});validate_schedule(fixture,ids)
    teams={t:fictional_team(t) for t in ids}; season=Season(ids); replayed=Season(ids)
    store=HistoryStore(output/'history.sqlite3');season_id=config['season_id']; reason=None
    try:
        for item in fixture:
            g=Game(model,(teams[item['away']],teams[item['home']]),seed=config['seed_start']+100000+item['number'],game_date=item['date'],
                   rules=GameRules(**config['rules']),allow_assumptions=config['allow_assumptions'],auto_relief_inning=config['auto_relief_inning'])
            r=g.run();store.save(g);store.bind_season(g.game_id,season_id,item['number'])
            if r['status']=='failed':reason='game_failed';break
            season.add(r);replayed.add(store.load(g.game_id))
            if (not r['scoring_status']['rbi_complete'] or not r['scoring_status']['run_responsibility_complete']
                    or r['pitcher_decisions']['status'].startswith('manual')):
                reason='priority_record_incomplete';break
        result=season.export()
        if result!=replayed.export():raise ValueError('Replayed season differs')
        table=result['standings']
        if sum(r['w'] for r in table)!=sum(r['l'] for r in table):raise ValueError('Win/loss conservation failed')
        if sum(r['d'] for r in table)!=2*sum(r['status']=='draw' for r in season.results.values()):raise ValueError('Draw conservation failed')
        complete=len(season.results)==858 and reason is None
        if complete and any(r['games']!=143 for r in table):raise ValueError('Team game count differs')
        result.update(status='completed' if complete else 'stopped',executed_games=store.db.execute('select count(*) from games').fetchone()[0],
                      scheduled_games=858,season_id=season_id,reason=reason,full_season_completed=complete,replay_equal=True)
        write_json(output/'season.json',result)
        return result
    finally:store.close()
