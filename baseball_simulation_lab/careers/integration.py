"""The dated boundary between private careers and the unchanged Stage 10 Game."""
from dataclasses import asdict
from ..stability.engine import Game
from ..stability.rules import GameRules
from .adapter import AbilityModel
from .manager import select,post_game
from .randomness import event_seed


def prepare_game(world,base,away,home,*,on=None,number=1,season_id='experiment',enabled=True,record=True):
    on=on or world.now
    if on!=world.now:raise ValueError('Advance the world before preparing dated snapshots')
    ta,sa=select(world,away);th,sh=select(world,home);snapshots=(*sa,*sh)
    model=AbilityModel(base,snapshots,enabled=enabled);model.validate_game_date(on)
    seed=event_seed(world.root_seed,'game','league',f'{world.world_id}:{season_id}:{number}:{on}:{away}:{home}')
    game=Game(model,(ta,th),seed=seed,game_date=on,rules=GameRules(),allow_assumptions=True,auto_relief_inning=7,record=record)
    return game,snapshots


def apply_game(world,game):
    result=game.result()
    if game.request['game_date']!=world.now:raise ValueError('Game/current world date mismatch')
    selected={pid for t in game.teams for pid in (*t.lineup,*t.bench,t.starter,*t.bullpen)}
    if set(game.model.snapshots)!=selected:raise ValueError('Complete selected-roster snapshots required')
    for pid in (*result['batting'],*result['pitching']):
        if pid not in selected:raise ValueError('Unselected player appeared')
    post_game(world,result,{t.starter for t in game.teams})
    return result
