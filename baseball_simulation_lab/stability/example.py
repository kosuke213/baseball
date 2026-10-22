"""Stage 10: explicit generated-mode experiment; Python standard library only."""
from pathlib import Path
import argparse,json,sys
bundled=Path(__file__).resolve().parent/'code'
if bundled.exists():sys.path.insert(0,str(bundled))
from baseball_simulation_lab.stability.engine import Game,fictional_team
from baseball_simulation_lab.stability.model import GameModel
from baseball_simulation_lab.stability.storage import HistoryStore,replay_game
from baseball_simulation_lab.calibrated.rules import canonical


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-dir',type=Path,default=Path('.'));p.add_argument('--seed',type=int,default=310000)
    p.add_argument('--db',type=Path);p.add_argument('--journal',type=Path);p.add_argument('--empirical-only',action='store_true');a=p.parse_args()
    s7=a.model_dir/'stage7_model';s9=a.model_dir/'stage9_model'
    if not s7.exists():s7=Path(__file__).resolve().parents[2]/'data_sources/stage7'
    if not s9.exists():s9=Path(__file__).resolve().parents[2]/'data_sources/stage9'
    support=a.model_dir/'model/support_model.json'
    if not support.exists():support=a.model_dir/'support_model.json'
    policy='mle_baseline' if a.empirical_only else 'posterior_support'
    m=GameModel.load(s7,s9,support,policy)
    g=Game(m,(fictional_team('AWAY'),fictional_team('HOME')),seed=a.seed,allow_assumptions=not a.empirical_only,auto_relief_inning=7,journal_path=a.journal)
    r=g.run();assert canonical(replay_game(g.journal.rows))==canonical(r)
    if a.db:
        store=HistoryStore(a.db)
        try:store.save(g);store.load(g.game_id)
        finally:store.close()
    print(json.dumps({'game_id':g.game_id,'mode':'empirical_only' if a.empirical_only else 'generated_assumptions',
        **{k:r[k] for k in ('status','score','windows','linescore','team_totals','pitcher_decisions','scoring_status','timing_provenance','failure','model_version','rules_version')},'journal_replay_equal':True},ensure_ascii=False,indent=2))
    return 2 if r['status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())
