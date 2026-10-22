from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def new_output(path):
    candidate = Path(path).resolve()
    protected = [ROOT / prefix / name for prefix in ('data/research', 'data_sources')
                 for name in ('pilot', 'warehouse', 'stage5', 'stage6', 'stage7')]
    if any(candidate.is_relative_to(p.resolve()) or p.resolve().is_relative_to(candidate) for p in protected):
        raise ValueError('Previous stage outputs are protected')
    return candidate
