"""Run from the downloaded Stage 7 ZIP: python example.py --model-dir ."""
from pathlib import Path
import argparse
from dataclasses import asdict
import json
import random
import sys

# The distribution includes its exact source snapshot; installed packages also work.
bundled = Path(__file__).resolve().parent / 'code'
if bundled.exists():
    sys.path.insert(0, str(bundled))

from baseball_simulation_lab.calibrated.api import CalibratedModel
from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.replay import Journal, replay
from baseball_simulation_lab.calibrated.rules import fingerprint, frame_dict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, default=Path('.'))
    parser.add_argument('--seed', type=int, default=726)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--allow-assumptions', action='store_true')
    args = parser.parse_args()
    model = CalibratedModel.load(args.model_dir)
    before = example_frame(11)  # one out, first and second; fictional B/R1/R2
    result = model.resolve_outcome(before, 'double', random.Random(args.seed), allow_assumptions=args.allow_assumptions)
    if args.journal:
        journal = Journal(args.journal, before, model.version, seed=args.seed)
        journal.record_window(result)
        assert fingerprint(replay(args.journal)) == fingerprint(result.after)
    print(json.dumps({'seed': args.seed, 'model_version': model.version, 'rules_version': result.rules_version,
                      'before': frame_dict(before), 'after': frame_dict(result.after),
                      'scored': [asdict(r) for r in result.scored], 'out_ids': result.out_ids,
                      'completed_pa': result.completed_pa,
                      'route_sources': [{'source': t.plan.source, 'reference': t.plan.source_ref} for t in result.transitions],
                      'after_sha256': fingerprint(result.after)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
