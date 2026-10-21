"""Deterministic baseball transitions. Random sampling is isolated in step()."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import numpy as np

from .domain import (BattingStats, Environment, GameState, PitchingStats, Rules,
                     Runner, Team, primitive)
from .model import (CONTACT_OUTCOMES, PITCH_OUTCOMES, PitchOutcomeModel,
                    RuleBasedModel, validate_probabilities)


class SimulationError(RuntimeError):
    pass


class Game:
    def __init__(self, away: Team, home: Team, seed: int = 42,
                 rules: Rules | None = None, environment: Environment | None = None,
                 model: PitchOutcomeModel | None = None, record_events: bool = True):
        away.validate()
        home.validate()
        if away.team_id == home.team_id or set(p.player_id for p in away.players) & set(p.player_id for p in home.players):
            raise ValueError("Two distinct teams with globally unique player IDs are required")
        self.teams = deepcopy([away, home])
        self.rules = rules or Rules()
        self.environment = environment or Environment()
        self.model = model or RuleBasedModel()
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.snapshot = primitive({
            "schema_version": 1, "teams": [asdict(t) for t in self.teams],
            "seed": seed, "rules": asdict(self.rules), "environment": asdict(self.environment),
            "model": self.model.metadata(), "numpy_version": np.__version__,
            "rng": "PCG64", "engine_version": "phase1-engine-1",
        })
        self._initial_id = hashlib.sha256(json.dumps(self.snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        self.state = GameState()
        self.lineups = [list(t.lineup) for t in self.teams]
        self.defenses = [dict(t.defense) for t in self.teams]
        self.pitchers = [t.starter_id for t in self.teams]
        self.used_pitchers = [{t.starter_id} for t in self.teams]
        self.used_batters = [set(t.lineup) for t in self.teams]
        self.initial_fatigue = {p.player_id: p.state.fatigue for t in self.teams for p in t.players}
        self.batting = {p.player_id: BattingStats() for t in self.teams for p in t.players}
        self.pitching = {p.player_id: PitchingStats() for t in self.teams for p in t.players if p.category == "pitcher"}
        self.line_score: list[list[int | None]] = [[0], [None]]
        self.substitutions: list[dict] = []
        self.events: list[dict] = []
        self.record_events = record_events
        self.sequence = 0

    @property
    def game_id(self) -> str:
        # Decisions made during a game are also reproducibility inputs.
        # Identity becomes official at completion; do not merge two strategies.
        if not self.substitutions:
            return self._initial_id
        decisions = json.dumps(self.substitutions, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256((self._initial_id + decisions).encode()).hexdigest()[:24]

    @property
    def batting_side(self) -> int:
        return 0 if self.state.half == "top" else 1

    @property
    def batter_id(self) -> str:
        side = self.batting_side
        return self.lineups[side][self.state.order[side]]

    @property
    def pitcher_id(self) -> str:
        return self.pitchers[1 - self.batting_side]

    def view(self) -> dict:
        return {**primitive(self.state),
                "batter_id": self.batter_id, "pitcher_id": self.pitcher_id,
                "pitcher_pitches": self.pitching[self.pitcher_id].pitches,
                "line_score": deepcopy(self.line_score),
                "defense": deepcopy(self.defenses[1-self.batting_side])}

    def _log(self, kind: str, before: dict, **fields) -> dict:
        self.sequence += 1
        event = {"sequence": self.sequence, "kind": kind, "before": before,
                 "after": self.view(), **fields}
        if self.record_events:
            self.events.append(event)
        return event

    def change_pitcher(self, player_id: str) -> None:
        if self.state.finished or self.state.balls or self.state.strikes:
            raise ValueError("Pitcher changes are allowed between plate appearances")
        side = 1 - self.batting_side
        p = self.teams[side].player(player_id)
        if p.category != "pitcher" or p.status != "active" or player_id in self.used_pitchers[side]:
            raise ValueError("Pitcher is unavailable or has already appeared")
        before = self.view()
        old = self.pitchers[side]
        self.pitchers[side] = player_id
        self.used_pitchers[side].add(player_id)
        change = {"kind": "pitcher_change", "side": side, "out": old, "in": player_id,
                  "inning": self.state.inning, "half": self.state.half,
                  "pitches_before": self.state.pitches}
        self.substitutions.append(change)
        self._log("substitution", before, substitution=change)

    def replace_batter(self, side: int, slot: int, player_id: str) -> None:
        if side not in (0, 1) or not 0 <= slot < 9:
            raise ValueError("Invalid lineup slot")
        if self.state.finished or self.state.balls or self.state.strikes:
            raise ValueError("Batter changes are allowed between plate appearances")
        p = self.teams[side].player(player_id)
        old = self.lineups[side][slot]
        position = next(pos for pos, pid in self.defenses[side].items() if pid == old)
        if p.category != "batter" or p.status != "active" or player_id in self.used_batters[side]:
            raise ValueError("Batter unavailable or already used")
        if position != "DH" and position not in [p.position, *p.secondary_positions]:
            raise ValueError("Replacement cannot cover the defensive position")
        before = self.view()
        self.lineups[side][slot] = player_id
        self.defenses[side][position] = player_id
        self.used_batters[side].add(player_id)
        # A substituted baserunner also leaves the game. The replacement keeps
        # the original pitcher's responsibility and earned/unearned status.
        for runner in self.state.bases:
            if runner is not None and runner.player_id == old:
                runner.player_id = player_id
        change = {"kind": "batter_change", "side": side, "slot": slot,
                  "position": position, "out": old, "in": player_id,
                  "inning": self.state.inning, "half": self.state.half,
                  "pitches_before": self.state.pitches}
        self.substitutions.append(change)
        self._log("substitution", before, substitution=change)

    def _automatic_pitcher_change(self) -> None:
        side = 1 - self.batting_side
        current = self.pitchers[side]
        limit = self.rules.starter_pitch_limit if current == self.teams[side].starter_id else self.rules.reliever_pitch_limit
        if not self.state.balls and not self.state.strikes and self.pitching[current].pitches >= limit:
            candidates = [p for p in self.teams[side].players if p.category == "pitcher" and p.status == "active" and p.player_id not in self.used_pitchers[side]]
            if candidates:
                # Prefer rested relief pitchers, then remaining starters.
                p = min(candidates, key=lambda p: (p.ability.stamina > 60, p.state.fatigue, p.player_id))
                self.change_pitcher(p.player_id)

    def step(self) -> dict:
        if self.state.finished:
            raise SimulationError("The game is finished")
        if self.state.pitches >= self.rules.max_pitches:
            raise SimulationError(f"Pitch safety limit reached: {self.game_id}, {self.view()}")
        self._automatic_pitcher_change()
        side = self.batting_side
        batter = self.teams[side].player(self.batter_id)
        pitcher = self.teams[1-side].player(self.pitcher_id)
        probabilities = self.model.predict_probabilities(batter, pitcher, self.state, self.environment)
        validate_probabilities(probabilities, PITCH_OUTCOMES)
        outcome = str(self.rng.choice(list(probabilities), p=list(probabilities.values())))
        contact = None
        if outcome == "in_play":
            defenders = self.defenses[1-side]
            defense = float(np.mean([self.teams[1-side].player(pid).ability.fielding for pos, pid in defenders.items() if pos != "DH"]))
            contact_probs = self.model.contact_probabilities(batter, pitcher, self.state, self.environment, defense)
            validate_probabilities(contact_probs, CONTACT_OUTCOMES)
            contact = str(self.rng.choice(list(contact_probs), p=list(contact_probs.values())))
        return self.apply_pitch(outcome, contact)

    def apply_pitch(self, outcome: str, contact: str | None = None) -> dict:
        """Apply an explicit legal outcome, enabling deterministic rule tests."""
        s = self.state
        if s.finished:
            raise SimulationError("Cannot pitch after game end")
        self.assert_invariants()
        if outcome not in PITCH_OUTCOMES or (outcome == "in_play" and contact not in CONTACT_OUTCOMES):
            raise ValueError("Unknown pitch or contact outcome")
        if outcome != "in_play" and contact is not None:
            raise ValueError("Contact is only valid for an in-play pitch")
        if contact == "double_play" and (s.outs >= 2 or s.bases[0] is None):
            raise SimulationError("Double play requires first base occupied and fewer than two outs")
        if contact == "sac_fly" and (s.outs >= 2 or s.bases[2] is None):
            raise SimulationError("Sac fly requires third base occupied and fewer than two outs")
        before = self.view()
        side = self.batting_side
        bid, pid = self.batter_id, self.pitcher_id
        bs, ps = self.batting[bid], self.pitching[pid]
        ps.pitches += 1
        s.pitches += 1
        pitcher = self.teams[1-side].player(pid)
        pitcher.state.fatigue = min(2.5, self.initial_fatigue[pid] + ps.pitches / pitcher.ability.stamina * 0.35 * pitcher.ability.fatigue_sensitivity)
        result = outcome
        completed = False
        if outcome == "ball":
            s.balls += 1
            if s.balls == 4:
                result, completed = "walk", True
                bs.BB += 1
                ps.BB += 1
                self._walk(bid, pid)
        elif outcome in ("called_strike", "swinging_strike"):
            s.strikes += 1
            if s.strikes == 3:
                result, completed = "strikeout", True
                bs.AB += 1
                bs.SO += 1
                ps.SO += 1
                self._outs(1, pid)
        elif outcome == "foul":
            s.strikes = min(2, s.strikes + 1)
        else:
            result, completed = str(contact), True
            if contact in ("single", "double", "triple", "home_run"):
                # Non-HR walkoffs credit only bases needed for the winning run.
                if self._walkoff_possible() and contact != "home_run":
                    needed = s.score[0] - s.score[1] + 1
                    distances = sorted(3-i for i, r in enumerate(s.bases) if r is not None)
                    if len(distances) >= needed:
                        bases = min({"single": 1, "double": 2, "triple": 3}[str(contact)], distances[needed-1])
                        result = {1: "single", 2: "double", 3: "triple"}[bases]
                bs.AB += 1
                bs.H += 1
                ps.H += 1
                if result == "double": bs.doubles += 1
                if result == "triple": bs.triples += 1
                if result == "home_run":
                    bs.HR += 1
                    ps.HR += 1
                self._hit({"single": 1, "double": 2, "triple": 3, "home_run": 4}[result], bid, pid)
            elif contact == "sac_fly":
                bs.SF += 1
                self._outs(1, pid)
                runner = s.bases[2]
                s.bases[2] = None
                self._score(runner, bid)
            elif contact == "double_play":
                bs.AB += 1
                bs.GIDP += 1
                s.bases[0] = None
                self._outs(2, pid)
            else:
                bs.AB += 1
                self._outs(1, pid)
        if completed:
            bs.PA += 1
            ps.BF += 1
            s.order[side] = (s.order[side] + 1) % 9
            s.balls = s.strikes = 0
            if self._walkoff_possible() and s.score[1] > s.score[0]:
                self._finish("walkoff")
            elif s.outs == 3:
                self._end_half()
        self.assert_invariants()
        return self._log("pitch", before, batter_id=bid, pitcher_id=pid,
                         pitch=outcome, contact=contact, result=result,
                         plate_appearance_complete=completed)

    def _outs(self, count: int, pitcher_id: str) -> None:
        self.state.outs += count
        self.pitching[pitcher_id].outs += count

    def _walkoff_possible(self) -> bool:
        return self.state.inning >= 9 and self.state.half == "bottom"

    def _score(self, runner: Runner | None, batter_id: str) -> None:
        if runner is None:
            raise SimulationError("Cannot score a missing runner")
        s = self.state
        s.score[self.batting_side] += 1
        self.line_score[self.batting_side][s.inning-1] += 1
        self.batting[runner.player_id].R += 1
        self.batting[batter_id].RBI += 1
        charged = self.pitching[runner.responsible_pitcher]
        charged.R += 1
        charged.ER += int(runner.earned)

    def _walk(self, batter_id: str, pitcher_id: str) -> None:
        bases = self.state.bases
        if bases[0] is not None:
            if bases[1] is not None:
                if bases[2] is not None:
                    self._score(bases[2], batter_id)
                bases[2] = bases[1]
            bases[1] = bases[0]
        bases[0] = Runner(batter_id, pitcher_id)

    def _hit(self, distance: int, batter_id: str, pitcher_id: str) -> None:
        old = self.state.bases
        self.state.bases = [None, None, None]
        for index in (2, 1, 0):
            runner = old[index]
            if runner is None:
                continue
            if index + distance >= 3:
                self._score(runner, batter_id)
            else:
                self.state.bases[index + distance] = runner
        runner = Runner(batter_id, pitcher_id)
        if distance == 4:
            self._score(runner, batter_id)
        else:
            self.state.bases[distance-1] = runner

    def _end_half(self) -> None:
        s = self.state
        if s.inning >= 9:
            if s.half == "top" and s.score[1] > s.score[0]:
                self._finish("home_leads_after_top")
                return
            if s.half == "bottom":
                if s.score[0] != s.score[1]:
                    self._finish("regulation" if s.inning == 9 else "extra_innings")
                    return
                if s.inning >= self.rules.max_innings:
                    self._finish("draw_limit")
                    return
        s.outs = s.balls = s.strikes = 0
        s.bases = [None, None, None]
        if s.half == "top":
            s.half = "bottom"
            self.line_score[1][s.inning-1] = 0
        else:
            s.inning += 1
            s.half = "top"
            self.line_score[0].append(0)
            self.line_score[1].append(None)
        if self.rules.extra_runner and s.inning > 9:
            side = self.batting_side
            runner = self.lineups[side][(s.order[side]-1) % 9]
            s.bases[1] = Runner(runner, self.pitcher_id, earned=False)

    def _finish(self, ending: str) -> None:
        self.state.finished = True
        self.state.ending = ending
        for team in self.teams:
            for p in team.players:
                bs = self.batting[p.player_id]
                ps = self.pitching.get(p.player_id)
                p.state.experience += bs.PA + (ps.BF if ps else 0)
                if bs.PA:
                    p.state.fatigue = min(2.5, p.state.fatigue + 0.08*p.ability.fatigue_sensitivity)

    def assert_invariants(self) -> None:
        s = self.state
        if s.half not in ("top", "bottom") or not 1 <= s.inning <= self.rules.max_innings:
            raise SimulationError("Invalid inning/half")
        if not 0 <= s.outs <= (3 if s.finished else 2) or not 0 <= s.balls <= 3 or not 0 <= s.strikes <= 2:
            raise SimulationError("Invalid outs or pitch count")
        runners = [r.player_id for r in s.bases if r]
        if len(set(runners)) != len(runners):
            raise SimulationError("A runner occupies more than one base")
        if not s.finished and self.batter_id in runners:
            raise SimulationError("The batter is already on base")
        for r in (r for r in s.bases if r):
            if r.player_id not in self.batting or r.responsible_pitcher not in self.pitching:
                raise SimulationError("Unknown runner or responsible pitcher")
        for side in (0, 1):
            if s.score[side] < 0 or sum(v or 0 for v in self.line_score[side]) != s.score[side]:
                raise SimulationError("Scoreboard mismatch")
            if len(set(self.lineups[side])) != 9 or set(self.lineups[side]) != set(self.defenses[side].values()):
                raise SimulationError("Lineup/defense mismatch")

    def run(self) -> "Game":
        while not self.state.finished:
            self.step()
        return self

    def result(self) -> dict:
        if not self.state.finished:
            raise SimulationError("No official result before game end")
        return primitive({"game_id": self.game_id, "snapshot": self.snapshot,
                          "final": self.view(), "events": self.events,
                          "batting": {pid: asdict(s) for pid, s in self.batting.items() if s.PA or s.R},
                          "pitching": {pid: asdict(s) for pid, s in self.pitching.items() if s.pitches},
                          "lineups": self.lineups, "defenses": self.defenses,
                          "substitutions": self.substitutions,
                          "postgame_teams": [asdict(t) for t in self.teams]})
