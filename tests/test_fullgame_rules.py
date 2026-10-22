from dataclasses import replace

import pytest

from baseball_simulation_lab.calibrated.identity import example_frame
from baseball_simulation_lab.calibrated.rules import Move, Plan, UnsupportedRule
from baseball_simulation_lab.fullgame.model import assumed_play
from baseball_simulation_lab.fullgame.rules import Credit, GameRules, Play, apply_play, next_half


@pytest.mark.parametrize('pre,outcome,bases,runs', [
    (0, 'single', 1, 0), (9, 'single', 3, 0), (11, 'double', 6, 1),
    (23, 'home_run', 0, 4), (7, 'walk', 7, 1), (7, 'hit_by_pitch', 7, 1),
    (12, 'sacrifice_fly', 0, 1), (9, 'strikeout', 1, 0),
    (9, 'double_play', 0, 0), (20, 'fielders_choice', 0, 0),
])
def test_basic_plays_and_scoring_credit(pre, outcome, bases, runs):
    frame = example_frame(pre); play = assumed_play(frame, outcome); applied = apply_play(frame, play)
    assert applied.transition.after.base_mask == bases and len(applied.transition.scored) == runs
    assert set(applied.credit.rbi_ids) == {r.player_id for r in applied.transition.scored}
    assert applied.transition.plan.source == 'assumption'
    assert applied.credit.at_bat == (outcome not in ('walk', 'hit_by_pitch', 'sacrifice_fly'))


def test_credited_hit_followed_by_stretch_out_requires_evidence():
    frame = example_frame(0)
    plan = Plan('single', (Move('B', 0, 'OUT'),), True, 'empirical', 'verified-raw-row')
    with pytest.raises(UnsupportedRule): apply_play(frame, Play(plan, Credit(True, 1)))
    with pytest.raises(ValueError, match='evidence'): apply_play(frame, Play(plan, Credit(True, 1), certified=True))
    applied = apply_play(frame, Play(plan, Credit(True, 1), batter_reached=1, certified=True))
    assert applied.transition.out_ids == ('B',) and applied.credit.hit_bases == 1


def test_third_out_runs_need_a_source_adjudication_or_explicit_tag_order():
    frame = example_frame(20)
    p = Plan('single', (Move('R3', 3, 'H'), Move('B', 0, 'OUT')), True, 'empirical', 'raw-sha')
    credit = Credit(True, 1, ('R3',))
    for third in ('unspecified', 'force', 'batter_before_first', 'appeal_unknown'):
        with pytest.raises(UnsupportedRule): apply_play(frame, Play(p, credit, batter_reached=1, third_out=third, certified=True))
    result = apply_play(frame, Play(p, credit, 1, 'source_counted', True))
    assert result.transition.after.outs == 3 and result.transition.after.score[0] == 1
    assert not result.transition.official_scoring_complete
    result2 = apply_play(frame, Play(p, credit, 1, 'tag_after_runs'))
    assert result2.transition.after == result.transition.after
    with pytest.raises(ValueError): apply_play(frame, Play(replace(p, source='assumption'), credit, 1, 'source_counted', True))


def test_award_plus_extra_advance_and_safe_sacrifice_use_explicit_source():
    frame = example_frame(4)
    p = Plan('walk', (Move('R3', 3, 'H'), Move('B', 0, '2')), True, 'empirical', 'raw-W-WP')
    with pytest.raises(UnsupportedRule): apply_play(frame, Play(p, Credit(False)))
    a = apply_play(frame, Play(p, Credit(False, rbi_ids=()), 1, certified=True))
    assert a.transition.after.score[0] == 1 and a.credit.rbi_ids == ()
    p = Plan('sacrifice_fly', (Move('R3', 3, 'H'), Move('B', 0, '1')), True, 'empirical', 'dropped-fly')
    c = Credit(False, rbi_ids=('R3',), sacrifice_fly=True)
    a = apply_play(frame, Play(p, c, certified=True))
    assert a.transition.after.outs == 0 and a.credit.sacrifice_fly


def test_pinch_runner_responsibility_and_fielders_choice_replacement():
    frame = example_frame(1)
    frame = replace(frame, pitchers=('AP', 'NEW_P'), pitcher_history=('HP',))
    a = apply_play(frame, assumed_play(frame, 'fielders_choice'))
    assert a.transition.after.bases[0].player_id == 'B'
    assert a.transition.after.bases[0].responsible_pitcher == 'HP'


def test_walkoff_hit_value_and_home_run_scoring_are_distinct():
    top = example_frame(4)
    frame = replace(top, lineups=(top.lineups[1], top.lineups[0]), pitchers=('HP', 'AP'),
                    inning=9, half=1, score=(2, 2))
    a = apply_play(frame, assumed_play(frame, 'double'))
    assert a.transition.after.finished and a.transition.after.score == (2, 3)
    assert a.credit.hit_bases == 1 and a.transition.after.bases[0].player_id == 'B'
    hr = apply_play(frame, assumed_play(frame, 'home_run'))
    assert hr.credit.hit_bases == 4 and hr.transition.after.score == (2, 4)


def test_walkoff_with_unknown_out_timing_is_rejected():
    top = example_frame(4)
    frame = replace(top, lineups=(top.lineups[1], top.lineups[0]), pitchers=('HP', 'AP'), inning=9, half=1)
    p = Plan('single', (Move('R3', 3, 'H'), Move('B', 0, 'OUT')), True, 'empirical', 'source')
    with pytest.raises(UnsupportedRule, match='walkoff_out_timing'):
        apply_play(frame, Play(p, Credit(True, 1, ('R3',)), 1, certified=True))


def test_walkoff_caught_sacrifice_fly_out_precedes_tagup_run():
    top = example_frame(4)
    frame = replace(top, lineups=(top.lineups[1], top.lineups[0]), pitchers=('HP', 'AP'), inning=9, half=1)
    a = apply_play(frame, assumed_play(frame, 'sacrifice_fly'))
    assert a.transition.after.finished and a.transition.after.outs == 1 and a.transition.after.score == (0, 1)
    assert a.credit.sacrifice_fly and not a.credit.at_bat
    empirical = replace(assumed_play(frame, 'sacrifice_fly'),
                        plan=replace(assumed_play(frame, 'sacrifice_fly').plan, source='empirical'),
                        certified=True, event_text='8/SF/F8.3-H')
    assert apply_play(frame, empirical).transition.after == a.transition.after
    with pytest.raises(UnsupportedRule): apply_play(frame, replace(empirical, event_text='E8/SF.3-H;BX2(84)'))


@pytest.mark.parametrize('automatic', [None, 10, 11])
def test_configurable_extras_and_explicit_draw(automatic):
    frame = replace(example_frame(0), inning=9, half=1, outs=3)
    rules = GameRules(12, True, automatic)
    extra = next_half(frame, rules)
    assert extra.inning == 10 and extra.half == 0
    assert extra.base_mask == (2 if automatic == 10 else 0)
    if extra.base_mask:
        assert extra.bases[1].player_id == extra.lineups[0][-1] and extra.bases[1].automatic
    end = next_half(replace(frame, inning=12), rules)
    assert end.finished and end.score == (0, 0)


def test_winner_precedes_inning_cap_and_unlimited_no_draw():
    frame = replace(example_frame(0), inning=9, half=0, outs=3, score=(0, 1))
    assert next_half(frame, GameRules(9, True)).finished
    frame = replace(frame, half=1, score=(0, 0))
    with pytest.raises(UnsupportedRule): next_half(frame, GameRules(9, False))
    assert next_half(frame, GameRules(None, False)).inning == 10
    for r in (GameRules(8), GameRules(None, True), GameRules(12, True, 9), GameRules(max_windows=0)):
        with pytest.raises(ValueError): r.validate()


def test_scoring_contradictions_and_invalid_identity_are_not_bypassed():
    f = example_frame(0); p = assumed_play(f, 'single')
    with pytest.raises(ValueError): apply_play(f, replace(p, credit=Credit(False, 1)))
    with pytest.raises(ValueError): apply_play(f, replace(p, credit=Credit(True, 2)))
    with pytest.raises(ValueError): apply_play(f, replace(p, credit=Credit(True, 1, ('UNKNOWN',))))
    with pytest.raises(ValueError): apply_play(f, replace(p, plan=replace(p.plan, moves=())))
    with pytest.raises(ValueError): apply_play(f, replace(p, plan=replace(p.plan, moves=(Move('B', 0, '1'), Move('B', 0, '2')))))


def test_recorded_walkoff_sacrifice_fly_regressions_require_no_new_draw():
    import json
    from pathlib import Path
    from baseball_simulation_lab.calibrated.rules import frame_from_dict
    from baseball_simulation_lab.fullgame.rules import play_from_dict
    cases = json.loads((Path(__file__).parent / 'fixtures/stage8/walkoff_sf_regressions.json').read_text())['cases']
    assert len(cases) == 22
    for case in cases:
        before = frame_from_dict(case['frame']); applied = apply_play(before, play_from_dict(case['play']))
        assert applied.transition.after.finished and applied.transition.after.outs == before.outs + 1
        assert len(applied.transition.scored) == 1 and applied.credit.sacrifice_fly
        assert not applied.credit.at_bat and applied.credit.hit_bases == 0
