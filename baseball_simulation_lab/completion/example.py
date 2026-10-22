"""Standalone Stage 9 ZIP: python example.py --model-dir ."""
from pathlib import Path
import argparse
import json
import sys

bundled = Path(__file__).resolve().parent / 'code'
if bundled.exists(): sys.path.insert(0, str(bundled))

from baseball_simulation_lab.completion.engine import Game, fictional_team
from baseball_simulation_lab.completion.model import GameModel
from baseball_simulation_lab.completion.storage import HistoryStore, replay_game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, default=Path('.'))
    parser.add_argument('--seed', type=int, default=8000)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--allow-assumptions', action='store_true')
    args = parser.parse_args()
    parent = args.model_dir / 'stage7_model'
    if not parent.exists(): parent = Path(__file__).resolve().parents[2] / 'data_sources/stage7'
    model = GameModel.load(parent, args.model_dir / 'routes.json.gz', args.model_dir / 'terminal_model.json')
    g = Game(model, (fictional_team('AWAY'), fictional_team('HOME')), seed=args.seed,
             allow_assumptions=args.allow_assumptions, auto_relief_inning=7, journal_path=args.journal)
    result = g.run()
    assert json.dumps(replay_game(g.journal.rows), sort_keys=True) == json.dumps(result, sort_keys=True)
    if args.db:
        store = HistoryStore(args.db)
        try:
            store.save(g); store.load(g.game_id)
        finally: store.close()
    print(json.dumps({'game_id': g.game_id, 'status': g.status, 'score': result['score'], 'windows': g.windows,
                      'model_version': model.version, 'rules_version': result['rules_version'],
                      'linescore': result['linescore'], 'team_totals': result['team_totals'],
                      'pitcher_decisions': result['pitcher_decisions'], 'scoring_status': result['scoring_status'],
                      'source_actions': result['source_actions'], 'failure': result['failure'],
                      'journal_replay_equal': True}, ensure_ascii=False, indent=2))
    return 0 if g.status != 'failed' else 2


if __name__ == '__main__': raise SystemExit(main())
