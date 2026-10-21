"""Summary metrics use observed counts, with no fabricated reference data."""

from collections import Counter
import numpy as np
import pandas as pd

from .engine import Game


def game_row(game: Game) -> dict:
    b = list(game.batting.values())
    pa, ab = sum(s.PA for s in b), sum(s.AB for s in b)
    hits, walks = sum(s.H for s in b), sum(s.BB for s in b)
    sf = sum(s.SF for s in b)
    tb = sum(s.H+s.doubles+2*s.triples+3*s.HR for s in b)
    pitchers = [p for p in game.pitching.values() if p.pitches]
    row = {"game_id": game.game_id, "seed": game.seed, "away": game.teams[0].team_id,
           "home": game.teams[1].team_id, "away_score": game.state.score[0], "home_score": game.state.score[1],
           "innings": game.state.inning, "ending": game.state.ending, "pitches": game.state.pitches,
           "pitcher_appearances": len(pitchers), "PA": pa, "AB": ab, "H": hits, "BB": walks,
           "SO": sum(s.SO for s in b), "HR": sum(s.HR for s in b), "SF": sf, "TB": tb}
    for inning, runs in enumerate(zip(*game.line_score), 1):
        row[f"inning_{inning}_runs"] = sum(r or 0 for r in runs)
        row[f"inning_{inning}_team_halves"] = sum(r is not None for r in runs)
    return row


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("At least one completed game is required")
    df = pd.DataFrame(rows)
    totals = df.sum(numeric_only=True)
    ratio = lambda numerator, denominator: float(numerator/denominator) if denominator else None
    scores = df.away_score + df.home_score
    draws = int((df.home_score == df.away_score).sum())
    innings = {}
    for column in df:
        if column.startswith("inning_") and column.endswith("_runs"):
            inning = column.split("_")[1]
            innings[inning] = ratio(df[column].sum(), df[f"inning_{inning}_team_halves"].sum())
    return {"games": len(rows), "mean_runs_per_team_game": float(scores.mean()/2),
            "batting_average": ratio(totals.H, totals.AB),
            "on_base_percentage": ratio(totals.H+totals.BB, totals.AB+totals.BB+totals.SF),
            "slugging_percentage": ratio(totals.TB, totals.AB),
            "strikeout_rate": ratio(totals.SO, totals.PA), "walk_rate": ratio(totals.BB, totals.PA),
            "home_run_rate": ratio(totals.HR, totals.PA),
            "mean_pitches_per_game": float(df.pitches.mean()),
            "mean_pitches_per_pitcher_appearance": ratio(totals.pitches, totals.pitcher_appearances),
            "home_win_rate_all_games": float((df.home_score > df.away_score).mean()),
            "home_win_rate_decisive_games": ratio(int((df.home_score > df.away_score).sum()), len(rows)-draws),
            "draws": draws, "extra_innings_rate": float((df.innings > 9).mean()),
            "mean_runs_per_played_team_half_by_inning": innings,
            "total_score_histogram": {str(k): v for k, v in sorted(Counter(int(s) for s in scores).items())},
            "total_score_quantiles": {str(q): float(np.quantile(scores, q)) for q in (0, .25, .5, .75, .95, 1)},
            "estimated_duration_minutes": None,
            "reference_data": None, "calibrated": False}
