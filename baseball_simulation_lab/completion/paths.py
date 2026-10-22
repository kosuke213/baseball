from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def new_output(path):
    path=Path(path).resolve()
    for prefix in ('data/research','data_sources'):
        for name in ('pilot','warehouse','stage5','stage6','stage7','stage8'):
            old=(ROOT/prefix/name).resolve()
            if path.is_relative_to(old) or old.is_relative_to(path):raise ValueError('Stages 3-8 are protected')
    return path
