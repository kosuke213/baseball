from pathlib import Path
import argparse
import json


def main():
    from .paths import ROOT
    parser = argparse.ArgumentParser(description='Experimental window-based full games and immutable histories')
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('--config', type=Path, default=ROOT / 'data_sources/stage8/config.json')
    b.add_argument('--output', type=Path, default=ROOT / 'data/research/stage8')
    b.add_argument('--report-dir', type=Path, default=ROOT / 'data_sources/stage8')
    s = sub.add_parser('simulate'); s.add_argument('--model-dir', type=Path, default=ROOT / 'data_sources/stage8')
    s.add_argument('--seed', type=int, default=8000); s.add_argument('--db', type=Path, default=ROOT / 'data/fullgame/history.sqlite3')
    s.add_argument('--allow-assumptions', action='store_true'); s.add_argument('--journal', type=Path)
    r = sub.add_parser('replay'); r.add_argument('--db', type=Path, required=True); r.add_argument('--game-id', required=True)
    args = parser.parse_args()
    if args.command == 'build':
        from .pipeline import run
        run(args.config, args.output, args.report_dir); return 0
    if args.command == 'simulate':
        from . import example
        import sys
        sys.argv = ['example.py', '--model-dir', str(args.model_dir), '--seed', str(args.seed), '--db', str(args.db),
                    *(['--journal', str(args.journal)] if args.journal else []),
                    *(['--allow-assumptions'] if args.allow_assumptions else [])]
        return example.main()
    from .storage import HistoryStore
    if not args.db.exists(): raise FileNotFoundError(args.db)
    store = HistoryStore(args.db)
    try: print(json.dumps(store.load(args.game_id), ensure_ascii=False, indent=2))
    finally: store.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Stage 8 interrupted; previous snapshots retained')
        raise SystemExit(130)
