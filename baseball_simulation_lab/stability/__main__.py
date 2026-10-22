import argparse,json,sys
from pathlib import Path
from .paths import ROOT

def main():
    p=argparse.ArgumentParser(description='Stage 10 generated event chronology and immutable season experiment')
    s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('--config',type=Path,default=ROOT/'data_sources/stage10/config.json');b.add_argument('--output',type=Path,default=ROOT/'data/research/stage10')
    g=s.add_parser('simulate');g.add_argument('--model-dir',type=Path,default=ROOT/'data_sources/stage10');g.add_argument('--seed',type=int,default=310000);g.add_argument('--db',type=Path,default=ROOT/'data/stability/history.sqlite3');g.add_argument('--journal',type=Path);g.add_argument('--empirical-only',action='store_true')
    r=s.add_parser('replay');r.add_argument('--db',type=Path,required=True);r.add_argument('--game-id',required=True)
    a=p.parse_args()
    if a.command=='build':
        from .pipeline import run
        print(run(a.config,a.output));return 0
    if a.command=='simulate':
        from .example import main as example
        sys.argv=['example.py','--model-dir',str(a.model_dir),'--seed',str(a.seed),'--db',str(a.db),
            *(['--journal',str(a.journal)] if a.journal else []),*(['--empirical-only'] if a.empirical_only else [])]
        return example()
    from .storage import HistoryStore
    if not a.db.exists():raise FileNotFoundError(a.db)
    store=HistoryStore(a.db)
    try:print(json.dumps(store.load(a.game_id),ensure_ascii=False,indent=2))
    finally:store.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
