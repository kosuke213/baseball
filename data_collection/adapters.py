"""Readers for the pilot's explicit formats; retain every original column."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import io
import json
import re
import zipfile

from .fetch import CollectionError


def csv_rows(stream, *, header=None):
    reader = csv.reader(stream, strict=True)
    fields = header if header is not None else next(reader, [])
    if not fields or len(fields) != len(set(fields)) or any(not x for x in fields):
        raise CollectionError("CSV has empty or duplicate column names")
    for number, values in enumerate(reader, 1 if header is not None else 2):
        if len(values) != len(fields):
            raise CollectionError(f"CSV field count changed at row {number}")
        yield number, dict(zip(fields, values))


def zipped_csv(data, expected_member, *, header=None):
    # Never extract paths supplied by an archive. Cap decompressed member size too.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist().count(expected_member) != 1:
            raise CollectionError("Expected exactly one named ZIP member")
        member = archive.getinfo(expected_member)
        if member.file_size > 160_000_000 or member.flag_bits & 1:
            raise CollectionError("ZIP member is too large or encrypted")
        with archive.open(member) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                yield from csv_rows(stream, header=header)


def record(artifact, member, number, values):
    return {"artifact_id": artifact, "member": member, "source_row": number, "values": values}


def gamelogs(data):
    # Ordinals are the official glfields.txt schema; no original field is dropped.
    names = [f"field_{i:03}" for i in range(1, 162)]
    rows = []
    for number, values in zipped_csv(data, "gl2024.txt", header=names):
        day = values["field_001"]
        datetime.strptime(day, "%Y%m%d")
        values["game_id"] = values["field_007"] + day + values["field_002"]
        rows.append(record("retro_gl_2024", "gl2024.txt", number, values))
    if not rows:
        raise CollectionError("No game log records")
    return rows


def choose_games(rows, limit):
    ordered = sorted(rows, key=lambda r: r["values"]["game_id"])
    bydate = sorted(ordered, key=lambda r: (r["values"]["field_001"], r["values"]["game_id"]))
    candidates = {
        "opening": bydate[:4], "closing": bydate[-4:],
        "extra_innings": [r for r in ordered if int(r["values"]["field_012"]) > 54][:8],
        "doubleheader": [r for r in ordered if r["values"]["field_002"] != "0"][:8],
        "resumed": [r for r in ordered if r["values"]["field_014"]][:8],
        "fill": bydate,
    }
    selected = {}
    for label, group in candidates.items():
        for row in group:
            gid = row["values"]["game_id"]
            if label == "fill" and gid in selected:
                continue
            if gid in selected:
                selected[gid].append(label)
            elif len(selected) < limit:
                selected[gid] = [label]
            if len(selected) == limit and label == "fill":
                break
    return selected


def plays(data, selected):
    rows, scanned = [], 0
    for number, values in zipped_csv(data, "2024plays.csv"):
        scanned += 1
        if values["gid"] in selected:
            rows.append(record("retro_plays_2024", "2024plays.csv", number, values))
    if not rows:
        raise CollectionError("No plays matched the selected game IDs")
    return rows, scanned


def people(payloads, player_ids, npb_limit):
    matched, npb, scanned = [], [], 0
    for artifact_id in sorted(payloads):
        shard = artifact_id.removeprefix("register_")
        for number, values in csv_rows(io.StringIO(payloads[artifact_id].decode("utf-8-sig"), newline="")):
            scanned += 1
            row = record(artifact_id, f"data/people-{shard}.csv", number, values)
            if values["key_retro"] in player_ids:
                matched.append(row)
            elif values["key_npb"] and len(npb) < npb_limit:
                npb.append(row)
    return matched + npb, scanned


def japan_board(data):
    rows = [record("jpl_draft_2026", "boards/2026-npb-draft-board.csv", n, v)
            for n, v in csv_rows(io.StringIO(data.decode("utf-8-sig"), newline=""))]
    if not rows:
        raise CollectionError("Empty Japan Prospect Lab board")
    return rows


WEATHER_COLUMNS = [
    "hour_jst", "station_pressure_hpa", "sea_level_pressure_hpa", "precipitation_mm",
    "temperature_c", "dewpoint_c", "vapor_pressure_hpa", "humidity_pct",
    "wind_speed_m_s", "wind_direction", "sunshine_h", "solar_radiation_mj_m2",
    "snowfall_cm", "snow_depth_cm", "weather", "cloud_cover", "visibility_km",
]


class WeatherTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = self.cell = False
        self.rows, self.current, self.text, self.attrs = [], [], [], {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("id") == "tablefix1":
            self.active = True
        if not self.active:
            return
        if tag == "tr":
            self.current = []
        elif tag == "td":
            self.cell, self.text, self.attrs = True, [], attrs
        elif self.cell and tag == "img":
            self.text.append(attrs.get("alt", ""))

    def handle_data(self, data):
        if self.active and self.cell:
            self.text.append(data)

    def handle_endtag(self, tag):
        if self.active and tag == "td" and self.cell:
            self.current.append({"text": "".join(self.text).strip(), "attributes": self.attrs})
            self.cell = False
        elif self.active and tag == "tr" and self.current:
            self.rows.append(self.current)
        elif tag == "table":
            self.active = False


def weather(data):
    text = data.decode("utf-8")
    if "2024年3月29日" not in text or "東京（東京都)" not in text:
        raise CollectionError("Weather response does not match station/date")
    parser = WeatherTable()
    parser.feed(text)
    rows = []
    midnight = datetime(2024, 3, 29, tzinfo=timezone(timedelta(hours=9)))
    for number, cells in enumerate(parser.rows, 1):
        if len(cells) != len(WEATHER_COLUMNS):
            raise CollectionError("JMA hourly table schema changed")
        values = dict(zip(WEATHER_COLUMNS, (c["text"] for c in cells)))
        hour = int(values["hour_jst"])
        if hour not in range(1, 25):
            raise CollectionError("Invalid JMA hourly timestamp")
        ts = midnight + timedelta(hours=hour)
        values.update(station_id="47662", local_date="2024-03-29",
                      timestamp_jst=ts.isoformat(), timestamp_utc=ts.astimezone(timezone.utc).isoformat(),
                      cell_attributes={k: c["attributes"] for k, c in zip(WEATHER_COLUMNS, cells)})
        rows.append(record("jma_tokyo_20240329", "HTML#tablefix1", number, values))
    if len(rows) != 24:
        raise CollectionError("Expected 24 JMA hourly observations")
    return rows


def profile(rows, key_fields):
    values = [r["values"] for r in rows]
    columns = sorted({k for v in values for k in v})
    keys = [tuple(str(v.get(k, "")) for k in key_fields) for v in values]
    return {
        "rows": len(rows), "columns": len(columns), "business_key": key_fields,
        "duplicate_keys": len(keys) - len(set(keys)),
        "empty_key_rows": sum(any(not v.get(k, "") for k in key_fields) for v in values),
        "duplicate_full_rows": len(values) - len({json.dumps(v, sort_keys=True) for v in values}),
        "column_profiles": {
            k: {"empty_cells": sum(v.get(k, "") == "" for v in values),
                "absent_cells": sum(k not in v for v in values),
                "marker_counts": dict(Counter(v.get(k) for v in values if isinstance(v.get(k), str)
                                              and v.get(k) in ("--", "///", "×", "??"))),
                "json_types": sorted({type(v[k]).__name__ for v in values if k in v})}
            for k in columns
        },
        "missingness_rule": "Only an empty string is an empty cell. Source markers remain literal values; absent columns are reported separately. No missing-to-zero conversion.",
    }


def linescore(text):
    if not text:
        raise ValueError("Missing line score")
    tokens = re.findall(r"\(\d+\)|\d|[xX]", text)
    if "".join(tokens) != text:
        raise ValueError("Unrecognized line score")
    return sum(int(t.strip("()")) for t in tokens if t.lower() != "x")


def validate_games(games):
    failures = []
    for row in games:
        g = row["values"]
        for side, line, score in [("visiting", "field_020", "field_010"), ("home", "field_021", "field_011")]:
            try:
                ok = linescore(g[line]) == int(g[score])
            except ValueError:
                ok = False
            if not ok:
                failures.append({"game_id": g["game_id"], "side": side, "line_score": g[line], "score": g[score]})
    return {"games_checked": len(games), "line_score_failures": failures}


def validate_plays(games, plays_rows, selected):
    log = {r["values"]["game_id"]: r["values"] for r in games}
    groups = defaultdict(list)
    for row in plays_rows:
        groups[row["values"]["gid"]].append(row["values"])
    failures, game_checks = [], []
    counters = Counter()

    def check(ok, name, gid, pn):
        counters[name + "_checked"] += 1
        if not ok:
            counters[name + "_failed"] += 1
            failures.append({"check": name, "game_id": gid, "pn": pn})

    for gid in selected:
        seq = sorted(groups[gid], key=lambda p: int(p["pn"]))
        check(bool(seq), "game_present", gid, None)
        if not seq:
            continue
        g = log[gid]
        check([int(p["pn"]) for p in seq] == list(range(1, len(seq) + 1)), "play_sequence", gid, None)
        for index, p in enumerate(seq):
            pre, post = int(p["outs_pre"]), int(p["outs_post"])
            check(0 <= pre <= 2 and pre <= post <= 3, "outs_range", gid, p["pn"])
            side = int(p["vis_home"])
            check(side in (0, 1) and p["batteam"] == g["field_004" if side == 0 else "field_007"],
                  "batting_team", gid, p["pn"])
            check(int(p["inning"]) >= 1, "inning_range", gid, p["pn"])
            if index + 1 < len(seq):
                nxt = seq[index + 1]
                check(int(nxt["score_v"]) == int(p["score_v"]) + (int(p["runs"]) if side == 0 else 0)
                      and int(nxt["score_h"]) == int(p["score_h"]) + (int(p["runs"]) if side == 1 else 0),
                      "score_transition", gid, p["pn"])
                same_half = (p["inning"], p["top_bot"]) == (nxt["inning"], nxt["top_bot"])
                if same_half:
                    check(post == int(nxt["outs_pre"]), "outs_transition", gid, p["pn"])
                    # Pinch runners change identity without changing base occupancy.
                    check(all(bool(p[f"br{b}_post"]) == bool(nxt[f"br{b}_pre"]) for b in (1, 2, 3)),
                          "base_occupancy_transition", gid, p["pn"])
                else:
                    check(post == 3 and int(nxt["outs_pre"]) == 0, "half_inning_outs", gid, p["pn"])
                    expected = (int(p["inning"]) + int(p["top_bot"]), 1 - int(p["top_bot"]))
                    check((int(nxt["inning"]), int(nxt["top_bot"])) == expected,
                          "half_inning_sequence", gid, p["pn"])
        score_v = sum(int(p["runs"]) for p in seq if p["vis_home"] == "0")
        score_h = sum(int(p["runs"]) for p in seq if p["vis_home"] == "1")
        outs = sum(int(p["outs_post"]) - int(p["outs_pre"]) for p in seq)
        check((score_v, score_h) == (int(g["field_010"]), int(g["field_011"])), "final_score", gid, None)
        check(outs == int(g["field_012"]), "total_outs", gid, None)
        first = seq[0]
        check((first["score_v"], first["score_h"], first["outs_pre"]) == ("0", "0", "0"),
              "initial_state", gid, first["pn"])
        game_checks.append({"game_id": gid, "sample_reason": selected[gid], "plays": len(seq),
                            "score_v": score_v, "score_h": score_h, "outs": outs,
                            "innings": max(int(p["inning"]) for p in seq),
                            "pbp": sorted({p["pbp"] for p in seq}),
                            "event_dates": sorted({p["date"] for p in seq})})
    return {"games_checked": len(selected), "counters": dict(counters), "failures": failures,
            "games": game_checks,
            "limits": "Checks compare official parsed CSV to official Game Logs. Not independent scorecard verification, full event grammar replay, or pitch-tracking validation. Runner substitutions compare occupancy, not identity; automatic runners across innings are not validated."}


def identity_join(plays_rows, people_rows):
    ids = sorted({r["values"][k] for r in plays_rows for k in ("batter", "pitcher") if r["values"][k]})
    mapping = defaultdict(list)
    for row in people_rows:
        p = row["values"]
        if p["key_retro"]:
            mapping[p["key_retro"]].append(p)
    result = []
    for key in ids:
        candidates = mapping[key]
        result.append({"retrosheet_id": key, "match_count": len(candidates),
                       "status": "matched" if len(candidates) == 1 else "unmatched" if not candidates else "ambiguous",
                       "key_uuid": candidates[0]["key_uuid"] if len(candidates) == 1 else None,
                       "key_mlbam": candidates[0]["key_mlbam"] if len(candidates) == 1 else None})
    return {"distinct_game_player_ids": len(ids), "status_counts": dict(Counter(r["status"] for r in result)),
            "rows": result, "join_rule": "Exact key_retro only; key_uuid is the stable primary ID. No name matching. Japanese board has no external player IDs, so it is not automatically joined."}
