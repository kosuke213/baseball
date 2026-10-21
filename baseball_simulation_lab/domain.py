"""Serializable domain objects; no UI or database dependencies."""

from dataclasses import asdict, dataclass, field
import json
from typing import Any


def primitive(value: Any) -> Any:
    """Detach mutable values and reject non-JSON numbers."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


@dataclass
class Traits:
    contact: float
    discipline: float
    power: float
    launch_angle: float
    speed: float
    fielding: float
    handling: float
    velocity: float
    control: float
    strikeout: float
    stamina: float
    fatigue_sensitivity: float
    recovery: float
    growth_room: float


@dataclass
class PlayerState:
    fatigue: float = 0.0
    health: str = "healthy"
    experience: int = 0


@dataclass
class Player:
    player_id: str
    name: str
    age: int
    throws: str
    bats: str
    position: str
    secondary_positions: list[str]
    height_cm: int
    weight_kg: int
    pro_years: int
    team_id: str
    category: str
    status: str
    latent: Traits
    ability: Traits
    state: PlayerState = field(default_factory=PlayerState)

    def public(self) -> dict:
        data = primitive(self)
        for key in ("latent", "ability", "state"):
            del data[key]
        return data


@dataclass
class Team:
    team_id: str
    name: str
    players: list[Player]
    lineup: list[str]
    defense: dict[str, str]
    starter_id: str

    def player(self, player_id: str) -> Player:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise ValueError(f"Unknown player: {player_id}")

    def validate(self) -> None:
        ids = [p.player_id for p in self.players]
        if len(set(ids)) != len(ids) or any(p.team_id != self.team_id for p in self.players):
            raise ValueError("Duplicate player or incorrect team membership")
        if len(self.lineup) != 9 or len(set(self.lineup)) != 9:
            raise ValueError("A DH lineup needs nine distinct fielders")
        if set(self.defense) != {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"}:
            raise ValueError("Eight defensive positions and DH are required")
        if set(self.defense.values()) != set(self.lineup):
            raise ValueError("Lineup and defense must contain the same players")
        for position, pid in self.defense.items():
            p = self.player(pid)
            if p.category != "batter" or (position != "DH" and position not in [p.position, *p.secondary_positions]):
                raise ValueError(f"Ineligible defensive position: {pid} at {position}")
        if self.player(self.starter_id).category != "pitcher":
            raise ValueError("Starter must be a pitcher")


@dataclass(frozen=True)
class Park:
    park_id: str
    name: str
    left_m: float
    center_m: float
    right_m: float
    fence_m: float
    indoor: bool
    home_run_factor: float


PARKS = (
    Park("bay", "蒼波実験球場", 100, 122, 100, 3.0, False, 1.00),
    Park("dome", "星環ドーム", 97, 118, 97, 4.0, True, 1.08),
)


@dataclass(frozen=True)
class Weather:
    temperature_c: float = 20.0
    wind_m_s: float = 0.0
    wind_direction_deg: float = 0.0  # 0 = toward center field, 180 = toward home
    humidity: float = 0.5
    precipitation: str = "none"


@dataclass(frozen=True)
class Environment:
    park: Park = PARKS[0]
    weather: Weather = Weather()


@dataclass(frozen=True)
class Rules:
    version: str = "phase1-rules-1"
    max_innings: int = 12
    extra_runner: bool = False
    starter_pitch_limit: int = 90
    reliever_pitch_limit: int = 35
    max_pitches: int = 5000  # diagnostic guard; never silently declare a result

    def __post_init__(self) -> None:
        if not 9 <= self.max_innings <= 50:
            raise ValueError("max_innings must be between 9 and 50")
        if min(self.starter_pitch_limit, self.reliever_pitch_limit, self.max_pitches) <= 0:
            raise ValueError("Pitch limits must be positive")


@dataclass
class Runner:
    player_id: str
    responsible_pitcher: str
    earned: bool = True


@dataclass
class GameState:
    inning: int = 1
    half: str = "top"
    outs: int = 0
    balls: int = 0
    strikes: int = 0
    score: list[int] = field(default_factory=lambda: [0, 0])  # away, home
    bases: list[Runner | None] = field(default_factory=lambda: [None, None, None])
    order: list[int] = field(default_factory=lambda: [0, 0])
    pitches: int = 0
    finished: bool = False
    ending: str | None = None


@dataclass
class BattingStats:
    PA: int = 0
    AB: int = 0
    H: int = 0
    doubles: int = 0
    triples: int = 0
    HR: int = 0
    BB: int = 0
    SO: int = 0
    SF: int = 0
    R: int = 0
    RBI: int = 0
    GIDP: int = 0


@dataclass
class PitchingStats:
    pitches: int = 0
    outs: int = 0
    BF: int = 0
    H: int = 0
    HR: int = 0
    BB: int = 0
    SO: int = 0
    R: int = 0
    ER: int = 0


def recover(teams: list[Team], days: float = 1.0) -> None:
    if days < 0:
        raise ValueError("Rest days cannot be negative")
    for team in teams:
        for p in team.players:
            p.state.fatigue = max(0.0, p.state.fatigue - days * p.ability.recovery)
