"""Hypothetical, correlated player generation. No real player data."""

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
import numpy as np

from .domain import Player, Team, Traits

GENERATOR_VERSION = "fictional-correlated-1"


@dataclass(frozen=True)
class GenerationSettings:
    minimum_age: int = 18
    maximum_age: int = 38
    athletic_sd: float = 0.6
    skill_sd: float = 0.6
    velocity_mean_kmh: float = 145.0

    def __post_init__(self):
        if not 18 <= self.minimum_age <= self.maximum_age <= 45:
            raise ValueError("Generation age range must be within 18..45")
        if any(not isfinite(v) or not 0 < v <= 2 for v in (self.athletic_sd, self.skill_sd)):
            raise ValueError("Generation standard deviations must be within (0, 2]")
        if not isfinite(self.velocity_mean_kmh) or not 130 <= self.velocity_mean_kmh <= 155:
            raise ValueError("Mean pitch velocity must be within 130..155 km/h")


def generate_world(seed: int = 2026, settings: GenerationSettings | None = None) -> list[Team]:
    settings = settings or GenerationSettings()
    rng = np.random.default_rng(seed)
    teams = []
    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"] * 2
    for team_index, (tid, name, prefix) in enumerate((
        ("aonami", "蒼波オービッツ", "蒼波"),
        ("seikan", "星環コメッツ", "星環"),
    )):
        players = []
        for i in range(28):
            pitcher = i >= 16
            pos = "P" if pitcher else positions[i]
            age = int(rng.integers(settings.minimum_age, settings.maximum_age+1))
            athletic, eye, contact, power, arm = rng.normal(0, [settings.athletic_sd, *([settings.skill_sd]*4)])
            # Shared factors produce correlations, rather than independent ratings.
            speed = athletic + (0.35 if pos in ("CF", "SS", "2B") else -0.15)
            velocity = float(np.clip(settings.velocity_mean_kmh + arm * 7 + rng.normal(0, 2), 125, 163))
            traits = Traits(
                contact=float(contact + 0.25 * eye), discipline=float(eye),
                power=float(power - 0.2 * athletic), launch_angle=float(12 + 4 * power),
                speed=float(speed), fielding=float(athletic + rng.normal(0, 0.25)),
                handling=float(eye * 0.2 + rng.normal(0, 0.3)), velocity=velocity,
                control=float(0.4 * eye + rng.normal(0, 0.4)),
                strikeout=float((velocity - 145) / 8 + rng.normal(0, 0.25)),
                stamina=float(rng.uniform(80, 105) if i in (16, 17, 18, 19, 20) else rng.uniform(25, 45)),
                fatigue_sensitivity=float(rng.uniform(0.8, 1.2)),
                recovery=float(rng.uniform(0.2, 0.35)),
                growth_room=float(np.clip((30 - age) / 12 + rng.normal(0, 0.1), 0, 1)),
            )
            secondaries = [] if pitcher else (["2B", "SS", "3B"] if pos in ("2B", "SS", "3B") else ["LF", "CF", "RF"] if pos in ("LF", "CF", "RF") else [])
            players.append(Player(
                player_id=f"{tid}-{i+1:02}", name=f"{prefix}・{'投手' if pitcher else '野手'}{i+1:02}",
                age=age, throws=str(rng.choice(["R", "L"], p=[0.72, 0.28])),
                bats=str(rng.choice(["R", "L", "S"], p=[0.55, 0.40, 0.05])),
                position=pos, secondary_positions=[p for p in secondaries if p != pos],
                height_cm=int(np.clip(178 + 5 * arm + rng.normal(0, 3), 162, 202)),
                weight_kg=int(np.clip(79 + 7 * power + rng.normal(0, 3), 60, 115)),
                pro_years=max(0, age - 18 - int(rng.integers(0, min(5, age - 17)))),
                team_id=tid, category="pitcher" if pitcher else "batter", status="active",
                latent=traits, ability=deepcopy(traits),
            ))
        lineup = [p.player_id for p in players[:8]] + [players[9].player_id]
        defense = dict(zip(positions[:8] + ["DH"], lineup))
        team = Team(tid, name, players, lineup, defense, players[16].player_id)
        team.validate()
        teams.append(team)
    return teams
