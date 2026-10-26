from pathlib import Path
import argparse,json,secrets

def main():
    p=argparse.ArgumentParser(description='Additive sampled NPB physical profiles; no ability/platoon correction')
    p.add_argument('command',choices=['analyze','validate','demo'])
    p.add_argument('--admin-dir',type=Path,default=Path('data/careers/physical-demo'))
    p.add_argument('--seed',type=int)
    args=p.parse_args()
    if args.command=='analyze':
        from .analysis import export
        from .reporting import provenance,figures
        report,model=export();provenance();figures()
        print(json.dumps({'model_version':model['version'],'sample':report['primary_player_year_sample']['rows']},ensure_ascii=False))
    elif args.command=='validate':
        from .validation import generation_validation,compatibility,legacy_replay
        a=generation_validation();b=compatibility();c=legacy_replay()
        print(json.dumps({'generation_errors':a['errors'],'new_games':b,'old_replay':c},ensure_ascii=False))
    else:
        from data_collection.npb_profiles import new_stage_path
        from .model import initial_rosters
        from .storage import PhysicalStore,public_player
        from ..careers.world import World
        from ..careers.storage import CareerStore
        from ..careers.public import player_view
        from ..careers.integration import prepare_game,apply_game
        from ..careers.pipeline import load_base
        args.admin_dir=new_stage_path(args.admin_dir)
        if args.admin_dir.exists():raise FileExistsError('Demo destination must be new; preserve the saved history')
        seed=args.seed if args.seed is not None else secrets.randbits(256)
        entries=initial_rosters('npb-physical-demo','2026-04-01',seed,team_ids=['A','B'])
        w=World('npb-physical-demo','2026-04-01',seed,['A','B'])
        store=CareerStore(args.admin_dir/'private_careers.sqlite3');body=PhysicalStore(args.admin_dir/'physical.sqlite3',world_id=w.world_id,created_on=w.now)
        for e in entries:w.enrol(e.profile,e.talent,e.state);body.register(e.physical,e.profile)
        game,snaps=prepare_game(w,load_base(),'A','B');result=game.run()
        if result['status'] in ('completed','draw'):apply_game(w,game)
        store.commit(w,game=game,snapshots=snaps)
        first=entries[0];view=public_player(player_view(first.profile,w.current(first.profile.player_id),w.now),body.at(first.profile.player_id,w.now))
        print(json.dumps({'game_id':game.game_id,'status':result['status'],'score':result['score'],'public_example':view},ensure_ascii=False,indent=2))
        store.close();body.close()

if __name__=='__main__':main()
