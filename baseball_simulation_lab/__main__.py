"""Windows/Linux CLI: python -m baseball_simulation_lab --help."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd

from .domain import Environment, PARKS, Rules, Weather, recover
from .engine import Game
from .generation import GenerationSettings, generate_world
from .model import ModelSettings, RuleBasedModel
from .reporting import game_row, summarize
from .storage import Store, replay


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="架空野球リーグのローカル実験（未較正モデル）")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="再現可能な初期データを生成。既存記録は保持")
    init.add_argument("--db", default="data/lab.sqlite3")
    init.add_argument("--world-seed", type=int, default=2026)
    init.add_argument("--world-config", type=Path)
    reset = sub.add_parser("reset", help="指定DBを削除して初期化（--yes が必須）")
    reset.add_argument("--db", default="data/lab.sqlite3")
    reset.add_argument("--world-seed", type=int, default=2026)
    reset.add_argument("--yes", action="store_true")
    reset.add_argument("--world-config", type=Path)
    sim = sub.add_parser("simulate", help="一括実行し JSON/CSV レポートを出力")
    sim.add_argument("--games", type=int, default=1)
    sim.add_argument("--seed", type=int, default=42)
    sim.add_argument("--world-seed", type=int, default=2026)
    sim.add_argument("--world-config", type=Path)
    sim.add_argument("--db", default="data/lab.sqlite3")
    sim.add_argument("--output", default="reports/latest")
    sim.add_argument("--summary-only", action="store_true", help="速度検証用。DB・一球ログを保存しない")
    sim.add_argument("--carry-fatigue", action="store_true", help="連戦状態を継承し各試合後1日休養。既定は独立試行")
    sim.add_argument("--park", choices=[p.park_id for p in PARKS], default="bay")
    sim.add_argument("--temperature", type=float, default=20)
    sim.add_argument("--wind", type=float, default=0)
    sim.add_argument("--wind-direction", type=float, default=0)
    sim.add_argument("--max-innings", type=int, default=12)
    sim.add_argument("--extra-runner", action="store_true")
    sim.add_argument("--hr-scale", type=float, default=1)
    sim.add_argument("--rules", type=Path, help="Rules のJSON設定ファイル。個別フラグより優先")
    rep = sub.add_parser("replay", help="保存した入力・シード・交代履歴で再実行し全記録一致を検証")
    rep.add_argument("--db", default="data/lab.sqlite3")
    rep.add_argument("--game-id", required=True)
    return p


def main(argv=None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.command == "replay":
        with Store(args.db) as store:
            game = replay(store.load(args.game_id))
        print(f"Replay verified: {game.game_id}, {game.state.pitches} pitches, score={game.state.score}")
        return 0
    settings = GenerationSettings(**json.loads(args.world_config.read_text(encoding="utf-8"))) if args.world_config else GenerationSettings()
    if args.command in ("init", "reset"):
        if args.command == "reset":
            if not args.yes:
                p.error("reset は指定DBを削除します。--yes が必要です")
            path = Path(args.db)
            path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(path)+suffix).unlink(missing_ok=True)
        with Store(args.db) as store:
            created = store.initialize(generate_world(args.world_seed, settings))
        print(f"{'Initialized' if created else 'Already initialized'}: {args.db} (2 teams, 56 fictional players)")
        return 0
    if args.games < 1:
        p.error("--games must be positive")
    if not -30 <= args.temperature <= 50 or not 0 <= args.wind <= 30:
        p.error("Temperature must be -30..50 C and wind 0..30 m/s")
    rules = Rules(**json.loads(args.rules.read_text(encoding="utf-8"))) if args.rules else Rules(max_innings=args.max_innings, extra_runner=args.extra_runner)
    model = RuleBasedModel(ModelSettings(home_run_scale=args.hr_scale))
    environment = Environment(next(p for p in PARKS if p.park_id == args.park), Weather(args.temperature, args.wind, args.wind_direction))
    teams = generate_world(args.world_seed, settings)
    store = None if args.summary_only else Store(args.db)
    started = time.perf_counter()
    rows = []
    saved = 0
    try:
        if store:
            store.initialize(generate_world(args.world_seed, settings))
        for index in range(args.games):
            # Alternate home/away so team quality doesn't masquerade as home advantage.
            away, home = teams if index % 2 == 0 else list(reversed(teams))
            game = Game(away, home, seed=args.seed+index, rules=rules, environment=environment,
                        model=model, record_events=not args.summary_only).run()
            if store:
                saved += int(store.save(game))
            rows.append(game_row(game))
            if args.carry_fatigue:
                teams = sorted(game.teams, key=lambda t: t.team_id)
                recover(teams)
            if (index+1) % 100 == 0:
                print(f"Completed {index+1}/{args.games}", flush=True)
    finally:
        if store:
            store.close()
    summary = summarize(rows)
    summary.update({"elapsed_seconds": time.perf_counter()-started, "world_seed": args.world_seed,
                    "first_game_seed": args.seed, "newly_saved_games": saved,
                    "summary_only": args.summary_only, "carry_fatigue": args.carry_fatigue,
                    "model": model.metadata(), "rules": asdict(rules),
                    "environment": asdict(environment), "generation_settings": asdict(settings),
                    "numpy_version": np.__version__, "engine_version": "phase1-engine-1"})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "games.csv", index=False, encoding="utf-8-sig")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    print(f"Reports: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
