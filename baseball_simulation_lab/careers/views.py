"""Build dated public views from verified private events and completed seasons."""
from .public import PublicAPI,player_view


def export_public(store,world_id,on):
    world,states=store.states_at(world_id,on);reports=store.seasons_at(world_id,on)
    players=[]
    for pid,state in sorted(states.items()):
        seasons=[];total={};teams=set()
        for report in reports:
            for row in report['players']:
                if row['player_id']!=pid:continue
                seasons.append({'season_id':report['season_id'],**row});teams.add(row['team_id'])
                for k,v in row.items():
                    if k in ('player_id','kind','team_id','ip_display'):continue
                    total[k]=None if v is None or (k in total and total[k] is None) else total.get(k,0)+v
        if 'outs' in total:total['ip_display']=f'{total["outs"]//3}.{total["outs"]%3}'
        players.append(player_view(world.profiles[pid],state,on,season_stats=seasons,career_stats=total))
    return PublicAPI(players)
