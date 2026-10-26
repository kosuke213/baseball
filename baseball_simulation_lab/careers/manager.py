"""Finite-roster, deterministic choices using noisy reports and known workload."""
from datetime import date
from ..stability.engine import Team
from .domain import can_play,availability
from .adapter import snapshot

class RosterShortage(ValueError):pass


def select(world,team_id):
    bats=[];pitchers=[]
    for pid,p in world.profiles.items():
        if world.states[pid].team_id!=team_id:continue
        s=world.current(pid)
        if not can_play(s):continue
        ratings=s.scouting['ratings'];fatigue=s.fatigue
        if p.role=='batter':
            score=sum(ratings[k] for k in ('contact','power','discipline','k_avoid'))/4-28*fatigue-(5 if s.injury else 0)
            bats.append((score,pid))
        else:
            start_rest=(date.fromisoformat(world.now)-date.fromisoformat(s.last_start)).days if s.last_start else 999
            score=sum(ratings[k] for k in ('strikeouts','control','hr_suppression','hit_suppression'))/4-30*fatigue-(6 if s.injury else 0)
            pitchers.append((score,pid,start_rest,ratings['starter_aptitude'],ratings['relief_aptitude']))
    bats.sort(key=lambda x:(-x[0],x[1]))
    starters=[p for p in pitchers if p[2]>=4 and world.current(p[1]).fatigue<.55]
    starters.sort(key=lambda p:(-(p[0]+.20*(p[3]-50)),p[1]))
    if len(bats)<9 or not starters:raise RosterShortage(f'{team_id}: eligible batters={len(bats)}, rested starters={len(starters)}')
    starter=starters[0][1]
    relievers=[p for p in pitchers if p[1]!=starter and world.current(p[1]).fatigue<.65]
    relievers.sort(key=lambda p:(-(p[0]+.20*(p[4]-50)),p[1]))
    if not relievers:raise RosterShortage(team_id+': no eligible reliever; no replacement auto-created')
    # DH batting-order experiment; fielding assignments beyond listed main positions
    # are not claimed to be the NPB defensive-registration system.
    lineup=tuple(pid for _,pid in bats[:9]);bench=tuple(pid for _,pid in bats[9:])
    team=Team(team_id,lineup,starter,bench,(relievers[0][1],)).validate()
    chosen=(*team.lineup,*team.bench,team.starter,*team.bullpen)
    snapshots=tuple(snapshot(world.profiles[pid],world.current(pid),world.now) for pid in chosen)
    return team,snapshots


def post_game(world,result,starters):
    if result['status'] not in ('completed','draw'):raise ValueError('Failed game cannot apply fictional workload as a complete game')
    if result['game_id'] in world.applied_games:raise ValueError('Duplicate postgame workload')
    if result['game_date']!=world.now:raise ValueError('Postgame date mismatch')
    for pid,s in result['batting'].items():
        world.load(pid,result['game_id'],pa=s['pa'],field_game=True)
    for pid,s in result['pitching'].items():
        # The only scheduled starter pitched at least one complete early half;
        # caller supplies explicit initial pitcher IDs on the result context.
        world.load(pid,result['game_id'],outs=s['outs'],bf=s['bf'],started=pid in starters)
    world.mark_game(result['game_id'])
