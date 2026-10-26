"""Local administrator demo. Public output is whitelisted; private DB stays local."""
from pathlib import Path
import argparse,json,secrets,sys
bundled=Path(__file__).resolve().parent/'code'
if bundled.exists():sys.path.insert(0,str(bundled))
from baseball_simulation_lab.stability.model import GameModel
from baseball_simulation_lab.careers.validation import new_world
from baseball_simulation_lab.careers.integration import prepare_game,apply_game
from baseball_simulation_lab.careers.storage import CareerStore
from baseball_simulation_lab.careers.views import export_public


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-dir',type=Path,default=Path('.'))
    p.add_argument('--admin-db',type=Path,required=True);p.add_argument('--seed',type=int);a=p.parse_args()
    base=a.model_dir;s7=base/'stage7_model';s9=base/'stage9_model';s10=base/'stage10_model'
    if not s7.exists():
        repo=Path(__file__).resolve().parents[2];s7=repo/'data_sources/stage7';s9=repo/'data_sources/stage9';s10=repo/'data_sources/stage10'
    model=GameModel.load(s7,s9,s10/'support_model.json');store=CareerStore(a.admin_db)
    try:
        exists=store.db.execute("SELECT 1 FROM career_worlds WHERE world_id='local-demo'").fetchone()
        if exists:
            world=store.restore('local-demo')
            if a.seed is not None and a.seed!=world.root_seed:raise ValueError('Existing private world uses another seed')
            gid=store.db.execute('SELECT game_id FROM games ORDER BY game_date,game_id LIMIT 1').fetchone()[0]
            result=store.load(gid)
        else:
            world=new_world('local-demo','2026-04-01',a.seed if a.seed is not None else secrets.randbits(256),['T01','T02']);store.commit(world)
            game,snaps=prepare_game(world,model,'T01','T02',season_id='local-demo:2026');result=game.run()
            if result['status']!='failed':apply_game(world,game)
            store.commit(world,game=game,snapshots=snaps,season_id='local-demo:2026',scheduled_number=1)
        public=export_public(store,world.world_id,world.now)
        print(json.dumps({'game_id':result['game_id'],'date':result['game_date'],'status':result['status'],'score':result['score'],
            'public_player_example':public.list_players()[0],'private_information_in_output':False},ensure_ascii=False,indent=2))
        return 2 if result['status']=='failed' else 0
    finally:store.close()
if __name__=='__main__':raise SystemExit(main())
