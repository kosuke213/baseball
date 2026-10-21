from dataclasses import replace
import json
import random

import pytest

from baseball_simulation_lab.calibrated.identity import bind_action, example_frame, project, recover
from baseball_simulation_lab.calibrated.replay import Journal, replay
from baseball_simulation_lab.calibrated.rules import (
    Frame, Move, Plan, RunnerToken, UnsupportedRule, advance_half, apply_plan, change_pitcher,
    conservative_plan, count_event, fingerprint, plan_dict, runner_event, substitute)


@pytest.mark.parametrize('pre,outcome,expected_bases,expected_runs', [
    (0, 'single', 1, 0), (9, 'single', 3, 0), (11, 'double', 6, 1),
    (23, 'home_run', 0, 4), (7, 'walk', 7, 1), (12, 'sacrifice_fly', 0, 1),
])
def test_requested_hit_walk_and_sacrifice_cases(pre, outcome, expected_bases, expected_runs):
    before = example_frame(pre)
    result = apply_plan(before, conservative_plan(before, outcome))
    assert result.after.base_mask == expected_bases
    assert len(result.scored) == expected_runs
    assert len(set(r.player_id for r in result.after.bases if r)) == sum(r is not None for r in result.after.bases)
    assert result.plan.source == 'assumption'
    assert before.outs == pre // 8 and before.base_mask == pre % 8
    if outcome == 'single': assert result.after.bases[0].player_id == before.batter
    if outcome == 'double':
        assert result.after.bases[1].player_id == before.batter
        assert result.scored[0].player_id == before.bases[1].player_id
    if outcome == 'home_run': assert set(r.player_id for r in result.scored) == {before.batter, *(r.player_id for r in before.bases if r)}


def test_double_play_and_normal_strikeout_preserve_identified_outs_and_lob():
    before = example_frame(9)
    double = apply_plan(before, conservative_plan(before, 'double_play'))
    assert double.after.outs == 3 and not double.after.base_mask
    assert set(double.out_ids) == {before.batter, before.bases[0].player_id}
    assert double.completed_pa and double.after.orders[0] == 1
    before = example_frame(17)
    strikeout = apply_plan(before, conservative_plan(before, 'strikeout'))
    assert strikeout.out_ids == (before.batter,)
    assert strikeout.stranded_ids == (before.bases[0].player_id,)


def test_mid_pa_steal_and_caught_stealing_third_out_do_not_advance_batter():
    frame = replace(example_frame(1), balls=2, strikes=1)
    stolen = runner_event(frame, 'stolen_base', 1, '2')
    assert stolen.after.bases[1].player_id == frame.bases[0].player_id
    assert stolen.after.batter == frame.batter and (stolen.after.balls, stolen.after.strikes) == (2, 1)
    frame = replace(example_frame(17), balls=2, strikes=1)
    caught = runner_event(frame, 'caught_stealing', 1, 'OUT')
    assert caught.after.outs == 3 and caught.after.orders == frame.orders and not caught.completed_pa
    with pytest.raises(ValueError, match='third out'): apply_plan(caught.after, conservative_plan(example_frame(0), 'single'))
    next_half = advance_half(caught.after)
    assert next_half.outs == next_half.balls == next_half.strikes == 0


def test_extra_runner_is_explicit_eligible_id_with_unearned_status():
    frame = replace(example_frame(0), inning=9, half=1, outs=3)
    frame.validate()
    extra = advance_half(frame)
    assert (extra.inning, extra.half, extra.outs, extra.base_mask) == (10, 0, 0, 2)
    assert extra.bases[1].player_id == extra.lineups[0][-1]
    assert extra.bases[1].automatic and extra.bases[1].earned_eligible is False
    assert extra.bases[1].responsible_pitcher == extra.pitcher


def test_nonhr_walkoff_stops_scoring_and_home_run_counts_all():
    frame = example_frame(7)
    # Move the current batting roster to the home side for an explicit bottom ninth.
    frame = replace(frame, lineups=(frame.lineups[1], frame.lineups[0]), pitchers=('HP', 'AP'), half=1,
                    inning=9, score=(2, 2), bases=tuple(replace(r, responsible_pitcher='HP') if r else None for r in frame.bases))
    frame.validate()
    double = apply_plan(frame, conservative_plan(frame, 'double'))
    assert double.after.finished and double.after.score == (2, 3)
    assert double.scored[0].player_id == frame.bases[2].player_id
    assert frame.bases[1].player_id in double.halted_ids
    home_run = apply_plan(frame, conservative_plan(frame, 'home_run'))
    assert home_run.after.finished and home_run.after.score == (2, 6) and len(home_run.scored) == 4


def test_pitcher_and_pinch_runner_changes_preserve_responsibility_and_block_reentry():
    before = example_frame(1)
    changed = change_pitcher(before, 'NEW_P')
    assert changed.bases[0].responsible_pitcher == 'HP' and changed.pitcher == 'NEW_P'
    index = changed.lineups[0].index(changed.bases[0].player_id)
    pinch = substitute(changed, 0, index, 'NEW_R', pinch_runner=True)
    assert pinch.bases[0].player_id == 'NEW_R' and pinch.bases[0].responsible_pitcher == 'HP'
    result = apply_plan(pinch, conservative_plan(pinch, 'home_run'))
    assert next(r for r in result.scored if r.player_id == 'NEW_R').responsible_pitcher == 'HP'
    assert next(r for r in result.scored if r.player_id == pinch.batter).responsible_pitcher == 'NEW_P'
    with pytest.raises(ValueError): substitute(pinch, 0, index, before.bases[0].player_id, pinch_runner=True)
    with pytest.raises(UnsupportedRule): change_pitcher(pinch, 'HP')
    with pytest.raises(UnsupportedRule): substitute(replace(pinch, balls=1), 0, 0, 'X')


def test_observed_count_events_do_not_invent_pitch_probabilities():
    frame = example_frame(0)
    for _ in range(3): frame = count_event(frame, 'ball')
    result = count_event(frame, 'ball')
    assert result.completed_pa and result.plan.outcome == 'walk' and result.after.balls == 0
    frame = count_event(count_event(example_frame(0), 'called_strike'), 'swinging_strike')
    assert count_event(frame, 'foul').strikes == 2
    assert count_event(frame, 'called_strike').out_ids == (frame.batter,)


def test_malformed_dispositions_duplicate_ids_and_unsupported_rules_fail():
    frame = example_frame(9)
    with pytest.raises(ValueError): replace(frame, bases=(frame.bases[0], frame.bases[0], None)).validate()
    with pytest.raises(ValueError, match='exactly one'): apply_plan(frame, Plan('single', (), True, 'assumption', 'test'))
    with pytest.raises(ValueError, match='credited'): apply_plan(frame, Plan('double', (Move('R1', 1, '3'), Move('B', 0, '1')), True, 'assumption', 'test'))
    with pytest.raises(ValueError, match='same base'): apply_plan(frame, Plan('single', (Move('R1', 1, '1'), Move('B', 0, '1')), True, 'assumption', 'test'))
    with pytest.raises(UnsupportedRule): conservative_plan(example_frame(0), 'runner_only_end')
    with pytest.raises(UnsupportedRule): apply_plan(example_frame(20), Plan('other_out', (Move('R3', 3, 'H'), Move('B', 0, 'OUT')), True, 'empirical', 'test'))
    with pytest.raises(ValueError): runner_event(example_frame(3), 'stolen_base', 1, '2')


def test_recover_uses_id_fields_and_lob_not_fielder_position_codes():
    from test_empirical import raw
    row = raw('7/F7', pa=1, outcome='othout', pre=2, post=3, before=('runner1', '', ''))
    row.update(run_b='', run1='', run2='', run3='', lob_id1='runner1', lob_id2='', lob_id3='',
               brout_b='0', brout1='0', brout2='0', brout3='0', batout1='7', k_safe='0')
    action = recover(row)
    assert action['source_out_ids'] == ['b1']
    assert next(m for m in action['moves'] if m['role'] == '1')['destination'] == 'LOB'
    assert '7' not in action['source_out_ids']
    # A scorer ID is not interpreted as integer/bool.
    row = raw('HR', pa=1, outcome='hr', before=('runner1', '', ''), runs=2)
    row.update(run_b='b1', run1='runner1', run2='', run3='', lob_id1='', lob_id2='', lob_id3='', k_safe='0')
    assert recover(row)['source_scorers'] == ['b1', 'runner1']


def test_journal_replay_does_not_read_new_model_and_refuses_rewrite_or_tampering(tmp_path):
    frame = example_frame(0)
    journal = Journal(tmp_path / 'game.jsonl', frame, 'frozen-model-A')
    journal.append('play', plan_dict(conservative_plan(frame, 'single')))
    journal.append('play', plan_dict(conservative_plan(journal.current, 'strikeout')))
    assert replay(journal.path) == journal.current
    with pytest.raises(FileExistsError): Journal(journal.path, frame, 'updated-model-B')
    lines = journal.path.read_text().splitlines(); event = json.loads(lines[-1]); event['event']['model_version'] = 'B'
    lines[-1] = json.dumps(event); journal.path.write_text('\n'.join(lines) + '\n')
    with pytest.raises(ValueError): replay(journal.path)


@pytest.mark.parametrize('pre', range(24))
def test_all_supported_conservative_states_conserve_each_identity(pre):
    frame = example_frame(pre)
    for outcome in ('single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch', 'strikeout', 'other_out'):
        result = apply_plan(frame, conservative_plan(frame, outcome))
        assert 0 <= result.after.outs <= 3
        participants = {frame.batter, *(r.player_id for r in frame.bases if r)}
        dispositions = {r.player_id for r in result.after.bases if r} | {r.player_id for r in result.scored} | set(result.out_ids) | set(result.stranded_ids)
        assert dispositions == participants
