"""Read the pinned warehouse and immutable Retrosheet originals, without writes."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from itertools import groupby
import json
from pathlib import Path
import sqlite3

from data_collection import adapters
from .common import END, OUTCOMES, RAW_OUTCOMES, base_mask, canonical, legal_targets, sha_file

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE plays (
 game_id TEXT NOT NULL, pn INTEGER NOT NULL, season INTEGER NOT NULL,
 inning INTEGER NOT NULL, half INTEGER NOT NULL, pre_state INTEGER NOT NULL,
 post_state INTEGER NOT NULL, runs INTEGER NOT NULL, pa INTEGER NOT NULL,
 outcome TEXT, event_kind TEXT NOT NULL, event_raw TEXT NOT NULL,
 batter TEXT NOT NULL,pitcher TEXT NOT NULL,batter_hand TEXT,pitcher_hand TEXT,
 score_diff INTEGER NOT NULL, intentional_walk INTEGER NOT NULL,k_safe INTEGER NOT NULL,
 artifact_id TEXT NOT NULL,source_row INTEGER NOT NULL,
 PRIMARY KEY(game_id,pn)
);
CREATE TABLE windows (
 game_id TEXT NOT NULL, first_pn INTEGER NOT NULL,last_pn INTEGER NOT NULL,season INTEGER NOT NULL,
 inning INTEGER NOT NULL,half INTEGER NOT NULL,pre_state INTEGER NOT NULL,
 post_state INTEGER NOT NULL,runs INTEGER NOT NULL,outcome TEXT NOT NULL,
 completed_pa INTEGER NOT NULL,batter TEXT NOT NULL,pitcher TEXT NOT NULL,
 batter_hand TEXT,pitcher_hand TEXT,score_diff INTEGER NOT NULL,play_rows INTEGER NOT NULL,
 actor_changed INTEGER NOT NULL,extra_innings INTEGER NOT NULL,game_final INTEGER NOT NULL,
 transition_observed INTEGER NOT NULL,censor_reason TEXT,
 artifact_id TEXT NOT NULL,first_source_row INTEGER NOT NULL,last_source_row INTEGER NOT NULL,
 PRIMARY KEY(game_id,first_pn),FOREIGN KEY(game_id,first_pn) REFERENCES plays(game_id,pn)
);
CREATE INDEX window_seasons ON windows(season);
CREATE TABLE exclusions(game_id TEXT,pn INTEGER,season INTEGER,reason TEXT,artifact_id TEXT,source_row INTEGER);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
'''


def flag(row, key):
    if row[key] not in ('0', '1'):
        raise ValueError('Non-binary Retrosheet indicator: ' + key)
    return int(row[key])


def classify(row):
    pa = flag(row, 'pa')
    active = [name for name in RAW_OUTCOMES if flag(row, name)]
    if len(active) != pa:
        raise ValueError('PA indicators are not exhaustive and exclusive')
    if pa:
        return OUTCOMES[RAW_OUTCOMES.index(active[0])], 'completed_pa'
    event = row['event']
    if event == 'NP':
        return None, 'non_play'
    for prefix, kind in [('POCS', 'pickoff_caught_stealing'), ('PO', 'pickoff'), ('CS', 'caught_stealing'),
                         ('SB', 'stolen_base'), ('WP', 'wild_pitch'), ('PB', 'passed_ball'),
                         ('BK', 'balk'), ('DI', 'defensive_indifference'), ('OA', 'other_advance'),
                         ('FLE', 'foul_error')]:
        if event.startswith(prefix):
            return None, kind
    return None, 'other_non_pa_play'


def extract(path, source, cache, expected_sha):
    if sha_file(source) != expected_sha:
        raise ValueError('Stage 5 database checksum differs from pinned input')
    if Path(path).exists():
        raise ValueError('Derived database already exists; use a new staging directory')
    audit = {'input_database_sha256': expected_sha, 'raw_artifacts': [], 'raw_nonselected_rows': 0,
             'non_play_rows': 0, 'outcome_counts': {}, 'input_tables': {}, 'missingness': {}, 'identities': {}}
    with closing(sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(path)) as dst, dst:
        src.row_factory = sqlite3.Row
        src.execute('PRAGMA query_only=ON')
        dst.executescript(SCHEMA)
        audit['input_tables'] = {r['name']: r['sql'] for r in src.execute("SELECT name,sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")}
        audit['integrity_check'] = src.execute('PRAGMA quick_check').fetchone()[0]
        audit['identities'] = dict(src.execute("SELECT status,count(*) FROM player_matches WHERE retrosheet_id IN (SELECT batter_retro_id FROM plays UNION SELECT pitcher_retro_id FROM plays) GROUP BY status"))
        audit['missingness'] = dict(src.execute('''SELECT count(*) rows,sum(balls IS NULL) balls_null,
          sum(strikes IS NULL) strikes_null,sum(pitch_count IS NULL) pitch_count_null,
          sum(pitches_raw='') pitches_empty,sum(batter_hand IS NULL OR batter_hand='') batter_hand_missing,
          sum(pitcher_hand IS NULL OR pitcher_hand='') pitcher_hand_missing FROM analysis_plays''').fetchone())
        audit['hands'] = [dict(r) for r in src.execute('SELECT batter_hand,pitcher_hand,count(*) n FROM analysis_plays WHERE plate_appearance=1 GROUP BY 1,2')]
        audit['source_game_checks'] = dict(src.execute('SELECT status,count(*) FROM game_checks GROUP BY status'))
        audit['outside_scope_games'] = src.execute('SELECT count(*) FROM games WHERE season NOT BETWEEN 2023 AND 2025').fetchone()[0]
        for year in (2023, 2024, 2025):
            artifact = f'retro_plays_{year}'
            meta = json.loads(src.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?', (artifact,)).fetchone()[0])
            blob = cache / 'blobs' / meta['sha256']
            if not blob.exists() or sha_file(blob) != meta['sha256']:
                raise ValueError('Pinned original missing/corrupt: ' + artifact)
            audit['raw_artifacts'].append(meta)
            selected = iter(src.execute('''SELECT p.* FROM plays p JOIN games g USING(game_id)
                JOIN game_checks q USING(game_id) WHERE p.artifact_id=? AND g.season=?
                AND q.status='pass' AND p.pbp_type='full' ORDER BY p.source_row''', (artifact, year)))
            expected = next(selected, None)
            imported = 0
            for number, raw in adapters.zipped_csv(blob.read_bytes(), f'{year}plays.csv'):
                if expected is None or number < expected['source_row']:
                    audit['raw_nonselected_rows'] += 1
                    continue
                if number != expected['source_row'] or raw['gid'] != expected['game_id'].removeprefix('retrosheet:game:') or int(raw['pn']) != expected['play_number']:
                    raise ValueError('Original-to-warehouse source-row alignment failed')
                outcome, kind = classify(raw)
                for field, column in [('pa', 'plate_appearance'), ('k', 'strikeout'), ('hr', 'home_run'), ('runs', 'runs'),
                                      ('outs_pre', 'outs_pre'), ('outs_post', 'outs_post')]:
                    if int(raw[field]) != expected[column]:
                        raise ValueError('Original-to-warehouse value disagreement')
                if kind == 'non_play':
                    if flag(raw, 'pa') or int(raw['runs']) or raw['outs_pre'] != raw['outs_post']:
                        raise ValueError('NP unexpectedly changes outs/runs')
                    dst.execute('INSERT INTO exclusions VALUES(?,?,?,?,?,?)',
                                (expected['game_id'], int(raw['pn']), year, 'NP_non_play', artifact, number))
                    audit['non_play_rows'] += 1
                else:
                    outs = int(raw['outs_pre'])
                    if not 0 <= outs < 3:
                        raise ValueError('Real play starts after third out')
                    pre = outs * 8 + base_mask([raw[f'br{i}_pre'] for i in (1, 2, 3)])
                    post_outs = int(raw['outs_post'])
                    post = END if post_outs == 3 else post_outs * 8 + base_mask([raw[f'br{i}_post'] for i in (1, 2, 3)])
                    diff = int(raw['score_v']) - int(raw['score_h'])
                    if raw['vis_home'] == '1':
                        diff = -diff
                    dst.execute('INSERT INTO plays VALUES(' + ','.join('?' for _ in range(21)) + ')',
                                (expected['game_id'], int(raw['pn']), year, int(raw['inning']), int(raw['top_bot']), pre,
                                 post, int(raw['runs']), flag(raw, 'pa'), outcome, kind, raw['event'], raw['batter'],
                                 raw['pitcher'], raw['bathand'], raw['pithand'], diff, flag(raw, 'iw'), flag(raw, 'k_safe'), artifact, number))
                imported += 1
                expected = next(selected, None)
            if expected is not None or imported == 0:
                raise ValueError('Original partition incomplete or empty')
        audit['outcome_counts'] = dict(dst.execute('SELECT outcome,count(*) FROM plays WHERE pa=1 GROUP BY outcome'))
        audit['event_kinds'] = dict(dst.execute('SELECT event_kind,count(*) FROM plays GROUP BY event_kind'))
        dst.row_factory = sqlite3.Row
        audit['special_counts'] = dict(dst.execute('SELECT sum(intentional_walk) intentional_walks,sum(k_safe) strikeout_reached_safely FROM plays').fetchone())
        window_audit = make_windows(dst)
        audit.update(window_audit)
        audit['derived_counts'] = {table: dst.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('plays', 'windows', 'exclusions')}
        audit['by_year'] = [dict(r) for r in dst.execute('SELECT season,count(*) windows,sum(completed_pa) completed_pa,sum(play_rows) real_play_rows FROM windows GROUP BY season')]
        if dst.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Derived foreign-key validation failed')
        dst.execute('INSERT INTO metadata VALUES(?,?)', ('audit', canonical(audit)))
    if sha_file(source) != expected_sha:
        raise ValueError('Read-only source database unexpectedly changed')
    return audit


def make_windows(db):
    audit = Counter()
    support_exceptions = []
    for game, rows in groupby(db.execute('SELECT * FROM plays ORDER BY game_id,pn'), key=lambda r: r['game_id']):
        game_rows = list(rows)
        pending = []
        for index, row in enumerate(game_rows):
            if pending and (row['inning'], row['half']) != (pending[0]['inning'], pending[0]['half']):
                raise ValueError('Unclosed observed PA window across half-innings')
            if pending and row['pre_state'] != pending[-1]['post_state']:
                raise ValueError('Base/out discontinuity inside an observed PA window')
            if pending and row['score_diff'] != pending[0]['score_diff'] + sum(r['runs'] for r in pending):
                raise ValueError('Score discontinuity inside an observed PA window')
            pending.append(row)
            final = index == len(game_rows) - 1
            if not row['pa'] and row['post_state'] != END and not final:
                continue
            first = pending[0]
            outcome = row['outcome'] if row['pa'] else 'runner_only_end'
            runs = sum(r['runs'] for r in pending)
            changed = any(r['batter'] != first['batter'] or r['pitcher'] != first['pitcher'] for r in pending)
            audit['actor_changed_windows'] += changed
            audit['runner_only_end_windows'] += int(not row['pa'])
            audit['windows_with_intermediate_runner_events'] += len(pending) > 1
            audit['extra_inning_windows'] += first['inning'] >= 10
            if index == len(pending) - 1 or game_rows[index - len(pending)]['half'] != first['half'] or game_rows[index - len(pending)]['inning'] != first['inning']:
                audit['extra_half_starts_runner_on_second'] += int(first['inning'] >= 10 and first['pre_state'] == 2)
            censored = final and row['post_state'] != END
            reason = None
            if censored:
                reason = 'walkoff' if first['inning'] >= 9 and first['half'] == 1 and first['score_diff'] + runs > 0 else 'called_or_shortened_game'
                audit['censored_' + reason] += 1
            if not censored and (row['post_state'], runs) not in legal_targets(first['pre_state'], outcome):
                support_exceptions.append({'game_id': game, 'first_pn': first['pn'], 'last_pn': row['pn'],
                                           'state': first['pre_state'], 'post': row['post_state'], 'runs': runs, 'outcome': outcome})
            db.execute('INSERT INTO windows VALUES(' + ','.join('?' for _ in range(25)) + ')',
                       (game, first['pn'], row['pn'], first['season'], first['inning'], first['half'], first['pre_state'],
                        row['post_state'], runs, outcome, row['pa'], first['batter'], first['pitcher'],
                        first['batter_hand'], first['pitcher_hand'], first['score_diff'], len(pending), int(changed),
                        int(first['inning'] >= 10), int(final), int(not censored), reason,
                        first['artifact_id'], first['source_row'], row['source_row']))
            pending = []
        if pending:
            raise ValueError('Unclosed game window')
    audit['support_exception_count'] = len(support_exceptions)
    return {**audit, 'support_exceptions': support_exceptions}
