"""Replaceable pitch and batted-ball probabilities; coefficients are hypotheses."""

from dataclasses import asdict, dataclass
from math import cos, radians, isfinite
from typing import Protocol
import numpy as np

from .domain import Environment, GameState, Player

PITCH_OUTCOMES = ("ball", "called_strike", "swinging_strike", "foul", "in_play")
CONTACT_OUTCOMES = ("single", "double", "triple", "home_run", "ground_out", "fly_out", "line_out", "double_play", "sac_fly")


def validate_probabilities(probabilities: dict[str, float], expected: tuple[str, ...]) -> None:
    if set(probabilities) != set(expected):
        raise ValueError("Model outcome keys do not match the engine contract")
    if any(not isfinite(p) or p < 0 or p > 1 for p in probabilities.values()):
        raise ValueError("Invalid probability")
    if abs(sum(probabilities.values()) - 1) > 1e-9:
        raise ValueError("Model probabilities must sum to 1")


def normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if not isfinite(total) or total <= 0 or any(not isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("Invalid probability weights")
    return {key: float(value / total) for key, value in weights.items()}


class PitchOutcomeModel(Protocol):
    version: str

    def metadata(self) -> dict: ...

    def predict_probabilities(self, batter: Player, pitcher: Player, game_state: GameState, environment: Environment) -> dict[str, float]: ...

    def contact_probabilities(self, batter: Player, pitcher: Player, game_state: GameState, environment: Environment, defense: float) -> dict[str, float]: ...


@dataclass(frozen=True)
class ModelSettings:
    home_run_scale: float = 1.0
    fatigue_scale: float = 1.0

    def __post_init__(self) -> None:
        if not (isfinite(self.home_run_scale) and 0.1 <= self.home_run_scale <= 3):
            raise ValueError("home_run_scale must be between 0.1 and 3")
        if not (isfinite(self.fatigue_scale) and 0 <= self.fatigue_scale <= 3):
            raise ValueError("fatigue_scale must be between 0 and 3")


class RuleBasedModel:
    version = "hypothesis-pitch-1"

    def __init__(self, settings: ModelSettings | None = None):
        self.settings = settings or ModelSettings()

    def metadata(self) -> dict:
        return {"version": self.version, "settings": asdict(self.settings), "calibrated": False}

    def predict_probabilities(self, batter, pitcher, game_state, environment):
        b, p = batter.ability, pitcher.ability
        fatigue = pitcher.state.fatigue * self.settings.fatigue_scale
        same_hand = batter.bats != "S" and batter.bats == pitcher.throws
        weights = dict(zip(PITCH_OUTCOMES, (0.34, 0.17, 0.10, 0.18, 0.21)))
        weights["ball"] *= float(np.exp(np.clip(0.18*b.discipline - 0.18*p.control + 0.16*fatigue - 0.03*game_state.balls, -2, 2)))
        weights["swinging_strike"] *= float(np.exp(np.clip(0.25*p.strikeout - 0.3*b.contact + 0.10*same_hand - 0.18*fatigue, -2, 2)))
        weights["in_play"] *= float(np.exp(np.clip(0.2*b.contact - 0.12*p.strikeout - 0.06*same_hand + 0.08*game_state.strikes + 0.10*fatigue, -2, 2)))
        return normalize(weights)

    def contact_probabilities(self, batter, pitcher, game_state, environment, defense):
        b, p = batter.ability, pitcher.ability
        fatigue = pitcher.state.fatigue * self.settings.fatigue_scale
        weights = dict(zip(CONTACT_OUTCOMES, (0.245, 0.075, 0.009, 0.042, 0.28, 0.23, 0.119, 0, 0)))
        quality = float(np.exp(np.clip(0.12*b.contact - 0.06*p.strikeout + 0.12*fatigue - 0.08*defense, -2, 2)))
        weights["single"] *= quality
        weights["double"] *= quality * float(np.exp(np.clip(0.16*b.power, -2, 2)))
        weights["triple"] *= float(np.exp(np.clip(0.35*b.speed, -2, 2)))
        weather = environment.weather
        # Outdoor temperature/wind affect only HR probability, not batter ability.
        weather_factor = 1.0 if environment.park.indoor else float(np.exp(np.clip(0.006*(weather.temperature_c-20) + 0.025*weather.wind_m_s*cos(radians(weather.wind_direction_deg)), -0.5, 0.5)))
        weights["home_run"] *= self.settings.home_run_scale * environment.park.home_run_factor * weather_factor * float(np.exp(np.clip(0.4*b.power + 0.015*(b.launch_angle-12) + 0.15*fatigue, -2, 2)))
        if game_state.outs < 2 and game_state.bases[0] is not None:
            weights["double_play"] = weights["ground_out"] * 0.42
            weights["ground_out"] *= 0.58
        if game_state.outs < 2 and game_state.bases[2] is not None:
            weights["sac_fly"] = weights["fly_out"] * 0.45
            weights["fly_out"] *= 0.55
        return normalize(weights)
