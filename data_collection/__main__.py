"""Run the bounded stage-2 collection and build an isolated SQLite snapshot."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile

from . import adapters as a
from .fetch import Collector, CollectionError, digest, safe_url, write_json

ROOT = Path(__file__).resolve().parents[1]
KEYS = {"games": ["game_id"], "plays": ["gid", "pn"], "people": ["key_uuid"],
        "japan_board": ["rank", "name_jp"], "weather": ["station_id", "timestamp_utc"]}


def validate_plan(plan):
    ids = [s["id"] for s in plan["artifacts"]]
    if len(ids) != len(set(ids)):
        raise CollectionError("Duplicate artifact IDs")
    if not 1 <= plan["sample_game_limit"] <= 100 or not 1 <= plan["budget_bytes"] <= 100_000_000:
        raise CollectionError("Pilot sample/byte budget exceeds scope")
    for s in plan["artifacts"]:
        safe_url(s["url"])
        if s["purpose"] not in ("data", "evidence") or not 1 <= s["max_bytes"] <= 20_000_000:
            raise CollectionError("Invalid artifact purpose/size budget")
        rights = plan["rights"][s["rights"]]
        if not rights["evidence_artifacts"] or not rights["attribution"]:
            raise CollectionError("Rights evidence/attribution is missing")
        for key in rights["evidence_artifacts"]:
            if key not in ids or next(x for x in plan["artifacts"] if x["id"] == key)["purpose"] != "evidence":
                raise CollectionError("Invalid rights evidence reference")


def database(path, artifacts, datasets, joins):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".sqlite3")
    os.close(fd)
    try:
        with closing(sqlite3.connect(tmp)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE artifacts (
                    artifact_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL
                );
                CREATE TABLE records (
                    dataset TEXT NOT NULL, row_number INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                    member TEXT NOT NULL, source_row INTEGER NOT NULL,
                    business_key_json TEXT NOT NULL, data_json TEXT NOT NULL,
                    PRIMARY KEY(dataset, row_number)
                );
                CREATE TABLE identity_matches (
                    retrosheet_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    key_uuid TEXT, key_mlbam TEXT, match_count INTEGER NOT NULL
                );
                CREATE INDEX record_artifact ON records(artifact_id, member, source_row);
            """)
            for m in artifacts:
                db.execute("INSERT INTO artifacts VALUES(?,?,?)", (m["id"], m["sha256"], json.dumps(m, ensure_ascii=False)))
            for name, rows in datasets.items():
                for n, row in enumerate(rows, 1):
                    values = row["values"]
                    key = [values[k] for k in KEYS[name]]
                    db.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", (
                        name, n, row["artifact_id"], row["member"], row["source_row"],
                        json.dumps(key), json.dumps(values, ensure_ascii=False)))
                # Names are internal constants, never supplied by upstream data.
                db.execute(f"CREATE VIEW {name} AS SELECT * FROM records WHERE dataset='{name}'")
            for match in joins["rows"]:
                db.execute("INSERT INTO identity_matches VALUES(?,?,?,?,?)", (
                    match["retrosheet_id"], match["status"], match["key_uuid"], match["key_mlbam"], match["match_count"]))
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise CollectionError("SQLite integrity/foreign-key check failed")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def export_csv(path, rows):
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def build_report(plan, metas, datasets, scans, selected):
    profiles = {name: a.profile(rows, KEYS[name]) for name, rows in datasets.items()}
    game_check = a.validate_games(datasets["games"])
    play_check = a.validate_plays(datasets["games"], datasets["plays"], selected)
    joins = a.identity_join(datasets["plays"], datasets["people"])
    issues = []
    for name, p in profiles.items():
        if not p["rows"] or p["duplicate_keys"] or p["empty_key_rows"]:
            issues.append({"dataset": name, "issue": "Empty dataset, missing key, or duplicate business key"})
    if game_check["line_score_failures"] or play_check["failures"]:
        issues.append({"issue": "Game or play consistency checks failed"})
    # Unmatched IDs are reported, never filled by name guessing.
    if joins["status_counts"].get("ambiguous", 0):
        issues.append({"issue": "Ambiguous identity mapping"})
    return {
        "schema_version": 1, "stage": 2, "status": "pass" if not issues else "review_required",
        "snapshot_retrieved_at": max(m["retrieved_at"] for m in metas),
        "artifact_count": len(metas), "data_artifact_count": sum(m["purpose"] == "data" for m in metas),
        "source_ids_collected": sorted({sid for m in metas if m["purpose"] == "data"
                                         for sid in plan["rights"][m["rights"]]["source_ids"]}),
        "raw_bytes": sum(m["bytes"] for m in metas), "scanned_input_rows": scans,
        "observed_coverage": {
            "game_log_first_date": min(r["values"]["field_001"] for r in datasets["games"]),
            "game_log_last_date": max(r["values"]["field_001"] for r in datasets["games"]),
            "play_pbp_counts": dict(Counter(r["values"]["pbp"] for r in datasets["plays"])),
            "empty_pitch_sequence_events": dict(Counter(r["values"]["event"] for r in datasets["plays"]
                                                        if not r["values"]["pitches"])),
            "people_with_npb_id": sum(bool(r["values"]["key_npb"]) for r in datasets["people"]),
            "weather_hours_jst": [r["values"]["hour_jst"] for r in datasets["weather"]],
        },
        "datasets": profiles, "game_log_checks": game_check, "play_checks": play_check,
        "identity_join": joins, "issues": issues, "deferred": plan["deferred"],
        "selection": {"game_limit": plan["sample_game_limit"], "games": selected,
                      "npb_identity_examples": plan["npb_identity_limit"],
                      "rule": "First 4/last 4 chronologically; up to 8 each of extra-inning/doubleheader/resumed games, then chronological fill. Deterministic nonrandom engineering sample, not a representative population."},
        "limits": ["No model training or simulator calibration in stage 2.",
                   "All source columns remain strings or original nested values. No silent imputation; units and measurement definitions remain in hashed source documentation.",
                   "JPL board is secondary metadata/scouting; no external player IDs or per-row verification/source columns. No automatic merge or capability estimates.",
                   "JMA hourly station data is independent of sampled MLB games. No stadium/weather join or microclimate inference.",
                   "ID reference is fully scanned at one commit, but normalized people include only sampled batter/pitcher matches and 100 NPB-ID examples; other roles are not joined.",
                   "Retrosheet Game Logs and parsed plays have shared provenance. Matching totals is internal consistency, not independent corroboration."]}


def run(args):
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    plan_sha = digest(args.plan.read_bytes())
    lock_path = args.plan.with_name("lock.json")
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    if not lock and not args.record_lock:
        raise CollectionError("Missing acquisition lock. First reviewed acquisition requires --record-lock")
    if lock and lock["plan_sha256"] != plan_sha:
        raise CollectionError("Plan changed: create a new versioned pilot plan/lock instead of updating this snapshot")
    collector = Collector(args.output / "raw", plan["rights"], offline=args.offline, budget=plan["budget_bytes"])
    payloads, metas, errors = {}, [], []
    # Obtain policy evidence before accepting any data governed by it.
    ordered = sorted(plan["artifacts"], key=lambda s: s["purpose"] == "data")
    for original in ordered:
        s = dict(original)
        if lock:
            pin = lock["artifacts"][s["id"]]
            if pin["url"] != s["url"]:
                raise CollectionError("Artifact URL differs from acquisition lock")
            s["expected_sha256"] = pin["sha256"]
        try:
            if s["purpose"] == "data" and any(k not in payloads for k in plan["rights"][s["rights"]]["evidence_artifacts"]):
                raise CollectionError("Rights evidence unavailable; dependent data skipped")
            data, meta = collector.fetch(s)
            if lock and len(data) != pin["bytes"]:
                raise CollectionError("Payload length differs from acquisition lock")
            payloads[s["id"]] = data
            metas.append(meta)
            print(f"{s['id']}: {len(data):,} bytes", flush=True)
        except CollectionError as exc:
            errors.append({"artifact_id": s["id"], "url": s["url"], "error": str(exc)})
    args.report_dir.mkdir(parents=True, exist_ok=True)
    attempt = {"plan_sha256": plan_sha, "artifacts": metas, "errors": errors,
               "run_at": datetime.now(timezone.utc).isoformat(),
               "network_requests": collector.network_requests, "cache_hits": collector.cache_hits}
    write_json(args.output / "last_attempt.json", attempt)
    if errors:
        # Successful cached artifacts survive. Do not replace a valid DB with partial data.
        write_json(args.report_dir / "last_failure.json", attempt)
        raise CollectionError(f"{len(errors)} artifact(s) unavailable; see last_failure.json. Existing database preserved")
    if not lock:
        lock = {"schema_version": 1, "plan_sha256": plan_sha,
                "artifacts": {m["id"]: {k: m[k] for k in ("url", "sha256", "bytes")} for m in metas}}
        # Seal even if a later parser fails; retries must use these original bytes.
        write_json(lock_path, lock)
    games = a.gamelogs(payloads["retro_gl_2024"])
    selected = a.choose_games(games, plan["sample_game_limit"])
    plays, play_scan = a.plays(payloads["retro_plays_2024"], selected)
    ids = {r["values"][k] for r in plays for k in ("batter", "pitcher")}
    people, people_scan = a.people({k: v for k, v in payloads.items() if k.startswith("register_") and k != "register_readme"},
                                  ids, plan["npb_identity_limit"])
    datasets = {"games": games, "plays": plays, "people": people,
                "japan_board": a.japan_board(payloads["jpl_draft_2026"]),
                "weather": a.weather(payloads["jma_tokyo_20240329"])}
    scans = {"game_logs": len(games), "plays": play_scan, "register": people_scan,
             "japan_board": len(datasets["japan_board"]), "weather": len(datasets["weather"])}
    report = build_report(plan, metas, datasets, scans, selected)
    report.update(plan_sha256=plan_sha, lock_sha256=digest(lock_path.read_bytes()))
    database(args.output / "pilot.sqlite3", metas, datasets, report["identity_join"])
    manifest = {"plan_sha256": plan_sha, "lock_sha256": report["lock_sha256"], "artifacts": metas}
    write_json(args.report_dir / "manifest.json", manifest)
    write_json(args.report_dir / "quality.json", report)
    write_json(args.output / "quality.json", report)
    for name, rows in datasets.items():
        args.output.joinpath("normalized").mkdir(exist_ok=True)
        with (args.output / "normalized" / (name + ".jsonl")).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    export_csv(args.report_dir / "sample_games.csv", report["play_checks"]["games"])
    export_csv(args.report_dir / "identity_matches.csv", report["identity_join"]["rows"])
    export_csv(args.report_dir / "weather_sample.csv", [r["values"] for r in datasets["weather"]])
    write_json(args.report_dir / "previews.json", {name: rows[:3] for name, rows in datasets.items()})
    # A small downloadable derivative, with provenance and mandatory attribution.
    # Large source archives remain outside Git in the verified raw cache.
    bundle_files = {
        "pilot.sqlite3": args.output / "pilot.sqlite3",
        **{name: args.report_dir / name for name in ("manifest.json", "quality.json", "sample_games.csv",
                                                    "identity_matches.csv", "weather_sample.csv", "previews.json")},
    }
    for name in ("README.md", "ATTRIBUTIONS.md"):
        if not (args.report_dir / name).exists():
            raise CollectionError(f"Bundle documentation missing: {name}")
        bundle_files[name] = args.report_dir / name
    fd, tmp_bundle = tempfile.mkstemp(dir=args.report_dir, suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in sorted(bundle_files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        os.replace(tmp_bundle, args.report_dir / "sample_bundle.zip")
    finally:
        Path(tmp_bundle).unlink(missing_ok=True)
    bundle_bytes = (args.report_dir / "sample_bundle.zip").read_bytes()
    write_json(args.report_dir / "bundle.json", {"file": "sample_bundle.zip", "bytes": len(bundle_bytes),
                                                "sha256": digest(bundle_bytes), "database_sha256": digest((args.output / "pilot.sqlite3").read_bytes())})
    print(json.dumps({"status": report["status"], "rows": {k: len(v) for k, v in datasets.items()},
                      "network_requests": collector.network_requests, "cache_hits": collector.cache_hits,
                      "database": str(args.output / "pilot.sqlite3")}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "data_sources/pilot/plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/research/pilot")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data_sources/pilot")
    parser.add_argument("--offline", action="store_true", help="Verify cached bytes and rebuild without network access")
    parser.add_argument("--record-lock", action="store_true", help="Seal the first acquisition; never overwrites an existing lock")
    args = parser.parse_args()
    try:
        return run(args)
    except (CollectionError, KeyError, ValueError, UnicodeError, csv.Error, zipfile.BadZipFile, OSError) as exc:
        # Never print transport exception chains or environment configuration.
        print(f"Pilot failed: {type(exc).__name__}: {exc}" if isinstance(exc, CollectionError)
              else f"Pilot failed: {type(exc).__name__}; inspect input schema/cache", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
