"""Whitelist-only public DTOs. This module exposes no private repository object."""
import copy,json,math
from .domain import BAT_SKILLS,PITCH_SKILLS
from .domain import age_on,availability

ALLOWED_PLAYER_FIELDS=frozenset(('player_id','name','team_id','age','role','position','throws','bats','entry_year','nationality',
    'ratings','rating_uncertainty','rating_observed_on','availability','injury_history_count','current_injury_severity',
    'career_status','season_stats','career_stats','as_of'))


STAT_FIELDS=frozenset(('season_id','player_id','team_id','kind','pa','ab','h','double','triple','hr','bb','hbp','k','r','rbi','sh','sf','ci',
    'outs','bf','ip_display','er','save','hold','w','l','games'))


def validate_public(player):
    if set(player)!=ALLOWED_PLAYER_FIELDS:raise ValueError('Unexpected public fields')
    allowed=BAT_SKILLS if player['role']=='batter' else PITCH_SKILLS if player['role']=='pitcher' else ()
    if set(player['ratings'])-set(allowed) or any(type(v) is not int or not 0<=v<=100 for v in player['ratings'].values()):
        raise ValueError('Ratings are noisy display values only')
    for stats in [*player['season_stats'],player['career_stats']]:
        if set(stats)-STAT_FIELDS:raise ValueError('Private/unknown statistic in public view')
        for k,v in stats.items():
            if k not in ('season_id','player_id','team_id','kind','ip_display') and v is not None and (type(v) is not int or v<0):
                raise ValueError('Public stats must be completed counts')
    return player


def player_view(profile,state,on,*,season_stats=None,career_stats=None):
    if state.as_of>on:raise ValueError('Future state in public output')
    report=state.scouting
    if report is None or report['observed_on']>on:raise ValueError('A committed past scouting report is required')
    result={'player_id':profile.player_id,'name':profile.name,'team_id':state.team_id,'age':age_on(profile.birth_date,on),
        'role':profile.role,'position':profile.position,'throws':profile.throws,'bats':profile.bats,'entry_year':profile.entry_year,
        'nationality':profile.nationality,'ratings':copy.deepcopy(report['ratings']),'rating_uncertainty':report['standard_error_points'],
        'rating_observed_on':report['observed_on'],'availability':availability(state),'injury_history_count':state.injury_history,
        'current_injury_severity':state.injury.severity if state.injury else None,'career_status':state.career_status,
        'season_stats':copy.deepcopy(season_stats or []),'career_stats':copy.deepcopy(career_stats or {}),'as_of':on}
    assert set(result)==ALLOWED_PLAYER_FIELDS
    return validate_public(result)


class PublicAPI:
    def __init__(self,players):
        for player in players:
            validate_public(player)
        self._public_json=json.dumps({p['player_id']:p for p in players},ensure_ascii=False)
    def get_player(self,player_id):return json.loads(self._public_json)[player_id]
    def list_players(self):return list(json.loads(self._public_json).values())
