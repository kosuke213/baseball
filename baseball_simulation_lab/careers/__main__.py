from pathlib import Path
import argparse,sys,json
from .pipeline import ROOT


def main():
    p=argparse.ArgumentParser(description='Fictional careers with local private state and explicit public views')
    s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('--config',type=Path,default=ROOT/'data_sources/stage11/config.json');b.add_argument('--output',type=Path,default=ROOT/'data/research/stage11')
    d=s.add_parser('demo');d.add_argument('--admin-db',type=Path,required=True);d.add_argument('--seed',type=int);d.add_argument('--model-dir',type=Path,default=ROOT/'data_sources/stage11')
    v=s.add_parser('public');v.add_argument('--admin-db',type=Path,required=True);v.add_argument('--world-id',required=True);v.add_argument('--as-of',required=True)
    a=p.parse_args()
    if a.command=='build':
        from .pipeline import run
        print(run(a.config,a.output));return 0
    if a.command=='demo':
        from .example import main as example
        sys.argv=['example.py','--model-dir',str(a.model_dir),'--admin-db',str(a.admin_db),*(['--seed',str(a.seed)] if a.seed is not None else [])]
        return example()
    from .storage import CareerStore
    from .views import export_public
    if not a.admin_db.exists():raise FileNotFoundError(a.admin_db)
    store=CareerStore(a.admin_db)
    try:print(json.dumps(export_public(store,a.world_id,a.as_of).list_players(),ensure_ascii=False,indent=2))
    finally:store.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
