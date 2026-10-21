from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .api import EmpiricalModel
from .demo import simulate


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description='Offline Stage 6 observed-PA probability tables')
    parser.add_argument('command', choices=['run', 'demo'])
    parser.add_argument('--config', type=Path, default=root / 'data_sources/stage6/config.json')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--cache', type=Path, default=root / 'data/research/pilot/raw')
    parser.add_argument('--output', type=Path, default=root / 'data/research/stage6')
    parser.add_argument('--report-dir', type=Path, default=root / 'data_sources/stage6')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    try:
        if args.command == 'demo':
            result = simulate(EmpiricalModel.load(args.report_dir), args.seed)
            result['step_count'] = len(result.pop('steps'))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        from .pipeline import run
        return run(args)
    except KeyboardInterrupt:
        print('Stage 6 interrupted; prior snapshots and source files retained', file=sys.stderr)
        return 130
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Inspect source schema, fixed inputs and ledger'
        print(f'Stage 6 failed ({type(exc).__name__}): {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
