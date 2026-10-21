from pathlib import Path
import argparse
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description='Offline Stage 7 calibration and ID transition foundation')
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--config', type=Path, default=root / 'data_sources/stage7/config.json')
    parser.add_argument('--source5', type=Path)
    parser.add_argument('--source6', type=Path)
    parser.add_argument('--cache', type=Path, default=root / 'data/research/pilot/raw')
    parser.add_argument('--output', type=Path, default=root / 'data/research/stage7')
    parser.add_argument('--report-dir', type=Path, default=root / 'data_sources/stage7')
    args = parser.parse_args()
    try:
        from .pipeline import run
        return run(args)
    except KeyboardInterrupt:
        print('Stage 7 interrupted; previous snapshots retained', file=sys.stderr)
        return 130
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Inspect fixed inputs, schemas and ledger'
        print(f'Stage 7 failed ({type(exc).__name__}): {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
