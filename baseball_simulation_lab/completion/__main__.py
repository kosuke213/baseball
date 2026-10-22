from pathlib import Path
import argparse
import json
from .paths import ROOT


def main():
    parser=argparse.ArgumentParser(description='Stage 9 experimental game completion and frozen histories')
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--config',type=Path,default=ROOT/'data_sources/stage9/config.json');b.add_argument('--output',type=Path,default=ROOT/'data/research/stage9')
    s=sub.add_parser('simulate');s.add_argument('--model-dir',type=Path,default=ROOT/'data_sources/stage9');s.add_argument('--seed',type=int,default=90000);s.add_argument('--db',type=Path,default=ROOT/'data/completion/history.sqlite3');s.add_argument('--journal',type=Path);s.add_argument('--allow-assumptions',action='store_true')
    r=sub.add_parser('replay');r.add_argument('--db',type=Path,required=True);r.add_argument('--game-id',required=True)
    args=parser.parse_args()
    if args.command=='build':
        from .pipeline import run
        print(run(args.config,args.output));return 0
    if args.command=='simulate':
        import sys
        from .example import main as simulate
        sys.argv=['example.py','--model-dir',str(args.model_dir),'--seed',str(args.seed),'--db',str(args.db),
                  *(['--journal',str(args.journal)] if args.journal else []),*(['--allow-assumptions'] if args.allow_assumptions else [])]
        return simulate()
    from .storage import HistoryStore
    if not args.db.exists():raise FileNotFoundError(args.db)
    store=HistoryStore(args.db)
    try:print(json.dumps(store.load(args.game_id),ensure_ascii=False,indent=2))
    finally:store.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
