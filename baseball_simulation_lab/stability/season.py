"""The old season accumulator with a versioned game/history executor."""
from pathlib import Path
import json
from data_collection.fetch import write_json
from ..completion.season import Season
from ..fullgame.league import validate_schedule,league_gate
from ..calibrated.rules import canonical
from .engine import Game,fictional_team
from .rules import GameRules
from .storage import HistoryStore


def run_league(model,output,fixture,config,validation):
    if not league_gate(validation):raise ValueError('League start gate failed')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    ids=sorted({g['away'] for g in fixture}|{g['home'] for g in fixture});validate_schedule(fixture,ids)
    teams={t:fictional_team(t) for t in ids};season=Season(ids);replayed=Season(ids)
    store=HistoryStore(output/'history.sqlite3');reason=None;rows=[]
    try:
        for item in fixture:
            g=Game(model,(teams[item['away']],teams[item['home']]),seed=config['league_seed_start']+item['number'],
                game_date=item['date'],rules=GameRules(**config['rules']),allow_assumptions=config['allow_assumptions'],auto_relief_inning=config['auto_relief_inning'])
            r=g.run();store.save(g);store.bind_season(g.game_id,config['season_id'],item['number'])
            rows.append({'number':item['number'],'game_id':g.game_id,'seed':g.seed,'date':item['date'],'away':item['away'],
                         'home':item['home'],'score':r['score'],'status':r['status']})
            if r['status']=='failed':reason='game_failed';write_json(output/'failure.json',r['failure']);break
            season.add(r);replayed.add(store.load(g.game_id))
            if (not r['scoring_status']['rbi_complete'] or not r['scoring_status']['run_responsibility_complete'] or r['pitcher_decisions']['status'].startswith('manual')):
                reason='priority_record_incomplete';break
            if item['number']%100==0:print(f'League stored/replayed {item["number"]}/858',flush=True)
        result=season.export()
        assert canonical(result)==canonical(replayed.export())
        table=result['standings'];complete=len(season.results)==858 and reason is None
        checks={'game_count_858':len(season.results)==858,'each_team_143':all(r['games']==143 for r in table),
            'wins_equal_losses':sum(r['w'] for r in table)==sum(r['l'] for r in table),
            'draws_counted_twice':sum(r['d'] for r in table)==2*sum(r['status']=='draw' for r in season.results.values()),
            'runs_for_equal_against':sum(r['runs_for'] for r in table)==sum(r['runs_against'] for r in table),
            'replay_same_standings_and_players':True,
            'batting_runs_equal_scores':sum(r['r'] for r in result['players'] if r['kind']=='batting')==sum(sum(r['score']) for r in season.results.values()),
            'no_duplicate_games':len(rows)==len({r['game_id'] for r in rows})}
        if complete and not all(checks.values()):raise ValueError('Season conservation check failed')
        result.update(status='completed' if complete else 'stopped',scheduled_games=858,executed_games=len(rows),
            season_id=config['season_id'],reason=reason,full_season_completed=complete,checks=checks,
            assumptions='same league probabilities, generated timing, no fictional ability differences; experimental integration season')
        write_json(output/'season.json',result);write_json(output/'games.json',rows)
        from .validation import csv_file
        csv_file(output/'standings.csv',table);csv_file(output/'players.csv',result['players'],fields=sorted({k for r in result['players'] for k in r}))
        return result
    finally:store.close()
