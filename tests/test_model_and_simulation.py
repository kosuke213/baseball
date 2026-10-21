from copy import deepcopy
from dataclasses import asdict
import numpy as np
import pytest

from baseball_simulation_lab.domain import Environment, PARKS, Rules, Weather, recover
from baseball_simulation_lab.engine import Game
from baseball_simulation_lab.generation import GenerationSettings, generate_world
from baseball_simulation_lab.model import CONTACT_OUTCOMES, PITCH_OUTCOMES, ModelSettings, RuleBasedModel, validate_probabilities
from baseball_simulation_lab.reporting import game_row, summarize


def test_generation_is_reproducible_and_public_view_hides_internal_state(teams):
    assert [asdict(t) for t in teams] == [asdict(t) for t in generate_world(2026)]
    for t in teams:
        t.validate()
        assert len(t.players) == 28
        assert sum(p.category == "pitcher" for p in t.players) == 12
        assert all(not {"latent", "ability", "state"} & p.public().keys() for p in t.players)


def test_generated_pitch_velocity_and_strikeout_are_correlated():
    players = [p for seed in range(15) for t in generate_world(seed) for p in t.players if p.category == "pitcher"]
    correlation = np.corrcoef([p.latent.velocity for p in players], [p.latent.strikeout for p in players])[0, 1]
    assert correlation > .8


def test_generator_distribution_is_configurable():
    teams = generate_world(3, GenerationSettings(minimum_age=18, maximum_age=20, skill_sd=.3))
    assert all(18 <= p.age <= 20 for t in teams for p in t.players)


def test_probability_contract_over_conditions(teams):
    model = RuleBasedModel()
    game = Game(*teams)
    for temperature in (-20, 20, 45):
        for count in ((0, 0), (3, 2), (0, 2)):
            for fatigue in (0, 1, 2.5):
                game.state.balls, game.state.strikes = count
                batter = teams[0].player(game.batter_id)
                pitcher = teams[1].player(game.pitcher_id)
                pitcher.state.fatigue = fatigue
                env = Environment(PARKS[0], Weather(temperature, 15))
                validate_probabilities(model.predict_probabilities(batter, pitcher, game.state, env), PITCH_OUTCOMES)
                validate_probabilities(model.contact_probabilities(batter, pitcher, game.state, env, 0), CONTACT_OUTCOMES)


def test_indoor_weather_has_no_effect(game):
    b = game.teams[0].player(game.batter_id)
    p = game.teams[1].player(game.pitcher_id)
    m = game.model
    assert m.contact_probabilities(b,p,game.state,Environment(PARKS[1],Weather(-20,20)),0) == m.contact_probabilities(b,p,game.state,Environment(PARKS[1],Weather(45,0)),0)


@pytest.mark.parametrize("invalid", [{"home_run_scale": float("nan")}, {"fatigue_scale": -1}, {"home_run_scale": 4}])
def test_model_rejects_invalid_settings(invalid):
    with pytest.raises(ValueError):
        ModelSettings(**invalid)


def test_identical_inputs_produce_identical_full_results(teams):
    before = deepcopy(teams)
    a = Game(*teams, seed=100).run()
    b = Game(*teams, seed=100).run()
    assert a.result() == b.result()
    assert teams == before  # experiments must not mutate the original world


def test_model_can_be_replaced(teams):
    class AlwaysCalledStrike(RuleBasedModel):
        version = "test-only"
        def predict_probabilities(self, *args):
            return {key: float(key == "called_strike") for key in PITCH_OUTCOMES}
    game = Game(*teams, model=AlwaysCalledStrike(), rules=Rules(max_innings=9)).run()
    assert game.state.ending == "draw_limit"
    assert game.state.pitches == 162
    assert sum(s.SO for s in game.batting.values()) == 54


def test_fatigue_recovery_is_separate_from_latent_ability(teams):
    game = Game(*teams).run()
    p = game.teams[1].player(game.teams[1].starter_id)
    fatigue = p.state.fatigue
    latent = deepcopy(p.latent)
    recover(game.teams)
    assert 0 <= p.state.fatigue < fatigue
    assert p.latent == latent


def test_hundred_games_end_with_consistent_records(teams):
    rows = []
    for seed in range(100):
        game = Game(*teams, seed=seed, record_events=False).run()
        game.assert_invariants()
        assert sum(s.R for s in game.batting.values()) == sum(game.state.score)
        assert sum(s.R for s in game.pitching.values()) == sum(game.state.score)
        assert sum(s.PA for s in game.batting.values()) == sum(s.BF for s in game.pitching.values())
        assert sum(s.pitches for s in game.pitching.values()) == game.state.pitches
        for s in game.batting.values():
            assert s.PA == s.AB+s.BB+s.SF
            assert 0 <= s.H <= s.AB
        assert sum(s.H for s in game.batting.values()) == sum(s.H for s in game.pitching.values())
        rows.append(game_row(game))
    summary = summarize(rows)
    assert summary["games"] == 100
    assert 0 < summary["mean_runs_per_team_game"] < 20
    assert summary["reference_data"] is None
