from copy import deepcopy
import pytest

from baseball_simulation_lab.domain import Rules, Runner
from baseball_simulation_lab.engine import Game, SimulationError


def strikeout(game):
    for _ in range(3):
        game.apply_pitch("called_strike")


def walk(game):
    for _ in range(4):
        game.apply_pitch("ball")


def runners(game, bases=(0, 1, 2)):
    lineup = game.lineups[game.batting_side]
    for index in bases:
        order = game.state.order[game.batting_side]
        game.state.bases[index] = Runner(lineup[(order-index-1) % 9], game.pitcher_id)


def reach_ninth(game):
    while game.state.inning < 9:
        strikeout(game)


def test_three_outs_switch_halves_and_continue_batting_order(game):
    for _ in range(3):
        strikeout(game)
    assert (game.state.half, game.state.outs, game.state.order) == ("bottom", 0, [3, 0])
    for _ in range(3):
        strikeout(game)
    assert (game.state.inning, game.state.half, game.batter_id) == (2, "top", game.lineups[0][3])


def test_four_balls_walk_and_force_only_required_runners(game):
    runners(game, (1, 2))
    old = deepcopy(game.state.bases)
    batter = game.batter_id
    walk(game)
    assert game.state.bases[0].player_id == batter
    assert game.state.bases[1:] == old[1:]
    assert game.state.score == [0, 0]
    assert game.batting[batter].PA == game.batting[batter].BB == 1
    assert game.batting[batter].AB == 0


def test_loaded_walk_forces_one_run(game):
    runners(game)
    walk(game)
    assert game.state.score == [1, 0]
    assert len({r.player_id for r in game.state.bases}) == 3


def test_three_strikes_and_two_strike_fouls(game):
    batter = game.batter_id
    game.apply_pitch("called_strike")
    game.apply_pitch("swinging_strike")
    for _ in range(8):
        game.apply_pitch("foul")
    assert game.state.strikes == 2 and game.state.outs == 0
    game.apply_pitch("swinging_strike")
    assert game.state.outs == 1
    assert game.batting[batter].SO == game.batting[batter].AB == 1


@pytest.mark.parametrize("outcome,bases,runs", [("single", 1, 1), ("double", 2, 2), ("triple", 3, 3), ("home_run", 4, 4)])
def test_hits_advance_and_score_without_duplicate_runners(game, outcome, bases, runs):
    runners(game)
    bid = game.batter_id
    game.apply_pitch("in_play", outcome)
    assert game.state.score[0] == runs
    assert game.batting[bid].RBI == runs
    assert sum(s.R for s in game.pitching.values()) == runs
    game.assert_invariants()
    if bases < 4:
        assert game.state.bases[bases-1].player_id == bid


@pytest.mark.parametrize("outs", [0, 1])
def test_double_play_never_scores_third_out_run(game, outs):
    runners(game)
    game.state.outs = outs
    game.apply_pitch("in_play", "double_play")
    assert game.state.score == [0, 0]
    if outs:
        assert game.state.half == "bottom" and game.state.bases == [None]*3
    else:
        assert game.state.outs == 2 and game.state.bases[0] is None


def test_sacrifice_fly_is_pa_but_not_ab(game):
    runners(game, (2,))
    bid = game.batter_id
    game.apply_pitch("in_play", "sac_fly")
    assert game.state.score == [1, 0]
    assert game.batting[bid].SF == game.batting[bid].PA == 1
    assert game.batting[bid].AB == 0


def test_invalid_contact_does_not_mutate_game(game):
    before = game.view()
    with pytest.raises(SimulationError):
        game.apply_pitch("in_play", "double_play")
    assert before == game.view()


def test_home_lead_skips_bottom_ninth(game):
    # Produce an actual home run, then only strikeouts to avoid artificial scores.
    for _ in range(3):
        strikeout(game)
    game.apply_pitch("in_play", "home_run")
    reach_ninth(game)
    for _ in range(3):
        strikeout(game)
    assert game.state.finished and game.state.half == "top"
    assert game.line_score[1][8] is None
    assert game.state.ending == "home_leads_after_top"


def test_walkoff_home_run_counts_all_runs(game):
    reach_ninth(game)
    for _ in range(3):
        strikeout(game)
    runners(game)
    game.apply_pitch("in_play", "home_run")
    assert game.state.finished and game.state.score == [0, 4]
    with pytest.raises(SimulationError):
        game.step()


def test_non_home_run_walkoff_counts_only_winning_run(game):
    reach_ninth(game)
    for _ in range(3):
        strikeout(game)
    runners(game)
    bid = game.batter_id
    event = game.apply_pitch("in_play", "triple")
    assert game.state.score == [0, 1]
    assert game.batting[bid].triples == 0
    assert event["result"] == "single"
    assert game.state.bases[0].player_id == bid
    assert all(game.state.bases)  # remaining runners do not disappear at game end


def test_away_lead_requires_bottom_ninth(game):
    game.apply_pitch("in_play", "home_run")
    reach_ninth(game)
    for _ in range(3):
        strikeout(game)
    assert game.state.half == "bottom" and not game.state.finished
    for _ in range(3):
        strikeout(game)
    assert game.state.finished and game.state.ending == "regulation"


def test_extra_innings_and_draw_limit(teams):
    g = Game(*teams, rules=Rules(max_innings=10))
    while not g.state.finished:
        strikeout(g)
    assert g.state.inning == 10 and g.state.ending == "draw_limit"
    assert sum(p.outs for p in g.pitching.values()) == 60


def test_tiebreaker_runner_is_unearned(teams):
    g = Game(*teams, rules=Rules(max_innings=10, extra_runner=True))
    while g.state.inning < 10:
        strikeout(g)
    assert g.state.bases[1] is not None and not g.state.bases[1].earned
    pid = g.pitcher_id
    g.apply_pitch("in_play", "double")
    assert g.pitching[pid].R == 1 and g.pitching[pid].ER == 0


def test_pitcher_changes_keep_inherited_run_responsibility(game):
    game.apply_pitch("in_play", "single")
    old = game.pitcher_id
    new = game.teams[1].players[21].player_id
    game.change_pitcher(new)
    game.apply_pitch("in_play", "home_run")
    assert game.pitching[old].R == 1 and game.pitching[new].R == 1
    with pytest.raises(ValueError):
        game.change_pitcher(old)


def test_batter_change_keeps_position_and_forbids_reentry(game):
    old = game.lineups[0][0]
    new = game.teams[0].players[8].player_id
    game.replace_batter(0, 0, new)
    assert game.batter_id == game.defenses[0]["C"] == new
    with pytest.raises(ValueError):
        game.replace_batter(0, 0, old)
    game.apply_pitch("ball")
    with pytest.raises(ValueError):
        game.change_pitcher(game.teams[1].players[21].player_id)


def test_invalid_duplicate_runner_is_not_silently_fixed(game):
    runner = Runner(game.lineups[0][-1], game.pitcher_id)
    game.state.bases = [runner, runner, None]
    with pytest.raises(SimulationError, match="more than one"):
        game.apply_pitch("ball")


def test_substitution_of_baserunner_transfers_run_but_not_hit(game):
    old = game.batter_id
    game.apply_pitch("in_play", "single")
    new = game.teams[0].players[8].player_id
    responsible = game.state.bases[0].responsible_pitcher
    game.replace_batter(0, 0, new)
    assert game.state.bases[0].player_id == new
    assert game.state.bases[0].responsible_pitcher == responsible
    game.apply_pitch("in_play", "home_run")
    assert game.batting[old].H == 1 and game.batting[old].R == 0
    assert game.batting[new].H == 0 and game.batting[new].R == 1


def test_pitch_safety_limit_is_diagnostic(teams):
    g = Game(*teams, rules=Rules(max_pitches=1))
    g.step()
    with pytest.raises(SimulationError, match="safety limit"):
        g.step()
