"""Recover role-labelled participant dispositions from frozen Retrosheet IDs.

run_b/run1..3 and lob_id1..3 are ID fields, not binary flags. Outs are the
unique remaining participant set, checked against the observed out delta.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

from data_collection import adapters
from data_collection.fetch import write_json
from ..empirical.common import OUTCOMES, base_mask, sha_file
from ..empirical.extract import classify
from .rules import (Frame, RunnerToken, Move, Plan, UnsupportedRule, apply_plan,
                    canonical, conservative_plan, plan_dict)


def example_frame(pre_state, *, batter='B', runners=None):
    outs, bases = divmod(pre_state, 8)
    tokens = ['R1', 'R2', 'R3'] if runners is None else runners
    trailing = [v for v in tokens if v]
    lineup = [batter]
    index = 0
    while len(lineup) + len(trailing) < 9:
        value = f'A{index}'; index += 1
        if value not in lineup and value not in trailing:
            lineup.append(value)
    lineup.extend(trailing)
    home = tuple(f'H{i}' for i in range(9))
    return Frame((tuple(lineup), home), ('AP', 'HP'), outs=outs,
                 bases=tuple(RunnerToken(tokens[i], 'HP') if bases & (1 << i) else None for i in range(3))).validate()


def recover(row):
    outcome, kind = classify(row)
    if kind == 'non_play':
        return None
    pa = row['pa'] == '1'
    participants = {row[f'br{i}_pre']: str(i) for i in (1, 2, 3) if row[f'br{i}_pre']}
    if len(participants) != sum(bool(row[f'br{i}_pre']) for i in (1, 2, 3)):
        raise ValueError('Duplicate source runner IDs')
    if pa:
        if row['batter'] in participants:
            raise ValueError('Batter already on base in source')
        participants[row['batter']] = 'B'
    post = {row[f'br{i}_post']: str(i) for i in (1, 2, 3) if row[f'br{i}_post']}
    scorers = [row[k] for k in ('run_b', 'run1', 'run2', 'run3') if row[k]]
    stranded = [row[f'lob_id{i}'] for i in (1, 2, 3) if row[f'lob_id{i}']]
    if len(scorers) != int(row['runs']) or len(set(scorers)) != len(scorers):
        raise ValueError('Source scorer IDs disagree with runs')
    # At a third out the LOB fields name the survivors; their final bases are not inferred.
    if int(row['outs_post']) == 3:
        post = {pid: dest for pid, dest in post.items() if pid not in stranded}
    seen = [*post, *scorers, *stranded]
    if len(seen) != len(set(seen)) or not set(seen) <= set(participants):
        raise ValueError('Source post/scorer/LOB identities conflict')
    out_ids = set(participants) - set(seen)
    if len(out_ids) != int(row['outs_post']) - int(row['outs_pre']):
        raise ValueError('Unique missing participant set does not equal source out delta')
    moves = []
    for pid, role in sorted(participants.items(), key=lambda pair: pair[1]):
        dest = post[pid] if pid in post else 'H' if pid in scorers else 'LOB' if pid in stranded else 'OUT'
        moves.append({'role': role, 'origin': 0 if role == 'B' else int(role), 'destination': dest})
    return {'outcome': outcome if pa else kind, 'completed_pa': pa, 'moves': moves,
            'dropped_third_strike': row['k_safe'] == '1', 'source_scorers': scorers,
            'source_out_ids': sorted(out_ids), 'participants': participants}


def bind_action(action, mapping, reference):
    return Plan(action['outcome'], tuple(Move(mapping[m['role']], m['origin'], m['destination']) for m in action['moves']),
                action['completed_pa'], 'empirical', reference, action['dropped_third_strike'])


def project(template, pre_state):
    frame = example_frame(pre_state)
    mapping = {'B': frame.batter, **{str(i): r.player_id for i, r in enumerate(frame.bases, 1) if r}}
    runs = 0
    for action in template:
        transition = apply_plan(frame, bind_action(action, mapping, 'training-template'))
        frame = transition.after; runs += len(transition.scored)
    post = 24 if frame.outs == 3 else frame.outs * 8 + frame.base_mask
    return post, runs


def collect(path, source6, source5, cache):
    if path.exists():
        raise ValueError('Identity output already exists')
    audit = Counter(); reasons = Counter(); examples = []; raw_artifacts = []
    with closing(sqlite3.connect('file:' + str(source6) + '?mode=ro', uri=True)) as src6, closing(sqlite3.connect('file:' + str(source5) + '?mode=ro', uri=True)) as src5, closing(sqlite3.connect(path)) as dst, dst:
        src6.row_factory = sqlite3.Row
        dates = {r[0]: (r[1], r[2]) for r in src5.execute('SELECT game_id,min(event_date),max(event_date) FROM plays GROUP BY game_id')}
        dst.executescript('''
          CREATE TABLE patterns(sha256 TEXT PRIMARY KEY,template_json TEXT NOT NULL);
          CREATE TABLE windows(game_id TEXT,first_pn INTEGER,last_pn INTEGER,season INTEGER,
            first_date TEXT,last_date TEXT,pre_state INTEGER,post_state INTEGER,runs INTEGER,outcome TEXT,
            extra INTEGER,reconstructed INTEGER,supported INTEGER,reason TEXT,pattern_sha TEXT REFERENCES patterns,
            artifact_id TEXT,first_source_row INTEGER,last_source_row INTEGER,PRIMARY KEY(game_id,first_pn));
          CREATE INDEX identity_seasons ON windows(season,supported);
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
        ''')
        for year in (2023, 2024, 2025):
            artifact = f'retro_plays_{year}'
            meta = json.loads(src5.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?', (artifact,)).fetchone()[0])
            raw_artifacts.append(meta)
            blob = cache / 'blobs' / meta['sha256']
            if not blob.exists() or sha_file(blob) != meta['sha256']:
                raise ValueError('Identity source artifact missing/corrupt')
            raw = iter(adapters.zipped_csv(blob.read_bytes(), f'{year}plays.csv'))
            current = next(raw, None)
            for window in src6.execute('SELECT * FROM windows WHERE season=? ORDER BY first_source_row', (year,)):
                audit['windows'] += 1
                while current and current[0] < window['first_source_row']:
                    current = next(raw, None)
                rows = []
                while current and current[0] <= window['last_source_row']:
                    if current[1]['event'] != 'NP':
                        rows.append(current)
                    current = next(raw, None)
                if not rows or rows[0][0] != window['first_source_row'] or rows[-1][0] != window['last_source_row']:
                    raise ValueError('Identity source range alignment failed')
                if any('retrosheet:game:' + r['gid'] != window['game_id'] for _, r in rows):
                    raise ValueError('Identity game alignment failed')
                reconstructed, supported, reason, pattern_sha = 1, 0, None, None
                template = []
                first = rows[0][1]
                global_roles = {first['batter']: 'B', **{first[f'br{i}_pre']: str(i) for i in (1, 2, 3) if first[f'br{i}_pre']}}
                if not window['transition_observed']:
                    reason = 'censored_game_ending'
                    reconstructed = 0
                elif window['actor_changed']:
                    reason = 'actor_or_substitution_changed'
                    reconstructed = 0
                else:
                    try:
                        for number, row in rows:
                            action = recover(row)
                            audit['recovered_atomic_plays'] += 1
                            normalized = {k: action[k] for k in ('outcome', 'completed_pa', 'dropped_third_strike')}
                            normalized['moves'] = []
                            for m in action['moves']:
                                source_id = next(pid for pid, role in action['participants'].items() if role == m['role'])
                                if source_id not in global_roles:
                                    raise ValueError('Unrecorded participant substitution inside window')
                                normalized['moves'].append({**m, 'role': global_roles[source_id]})
                            template.append(normalized)
                        # Reconstruction succeeded independently of the bounded rule implementation.
                        audit['reconstructed_windows'] += 1
                        try:
                            post, runs = project(template, window['pre_state'])
                            if (post, runs) != (window['post_state'], window['runs']):
                                raise ValueError('Identity projection differs from observed state/runs')
                            supported = 1
                        except (ValueError, UnsupportedRule) as exc:
                            reason = 'rule_scope:' + str(exc)
                        pattern_sha = hashlib.sha256(canonical(template).encode()).hexdigest()
                        dst.execute('INSERT OR IGNORE INTO patterns VALUES(?,?)', (pattern_sha, canonical(template)))
                        if supported and len(examples) < 30 and (len(rows) > 1 or first['hr'] == '1' or first['gdp'] == '1' or first['single'] == '1'):
                            examples.append({'game_id': window['game_id'], 'first_pn': window['first_pn'],
                                             'source_rows': [r[0] for r in rows], 'initial_ids': global_roles,
                                             'actions': [{'source_row': n, 'scorers': recover(r)['source_scorers'],
                                                          'outs': recover(r)['source_out_ids']} for n, r in rows],
                                             'template': template, 'artifact_id': artifact, 'artifact_sha256': meta['sha256']})
                    except (ValueError, KeyError) as exc:
                        reconstructed = 0
                        reason = 'reconstruction:' + str(exc)
                audit['supported_windows'] += supported
                if reason:
                    reasons[reason] += 1
                first_date, last_date = dates[window['game_id']]
                dst.execute('INSERT INTO windows VALUES(' + ','.join('?' for _ in range(18)) + ')',
                            (window['game_id'], window['first_pn'], window['last_pn'], year, first_date, last_date,
                             window['pre_state'], window['post_state'], window['runs'], window['outcome'], window['extra_innings'],
                             reconstructed, supported, reason, pattern_sha, artifact, window['first_source_row'], window['last_source_row']))
        result = {**audit, 'reasons': dict(reasons), 'source_examples': examples, 'raw_artifacts': raw_artifacts,
                  'by_year': [dict(zip(['season', 'windows', 'reconstructed', 'supported'], row)) for row in dst.execute('SELECT season,count(*),sum(reconstructed),sum(supported) FROM windows GROUP BY season')],
                  'limits': ['run fields contain explicit scorer IDs; missing participants are outs only when out delta and explicit LOB IDs agree',
                             'LOB identifies a stranded player but does not establish a final base',
                             'scorer/out identity is recoverable more widely than supported rule timing',
                             'source fielding-position out codes are not misinterpreted as player IDs']}
        dst.execute('INSERT INTO metadata VALUES(?,?)', ('audit', canonical(result)))
        return result


def fit_templates(db, seasons):
    if not set(seasons) <= {2023, 2024}:
        raise ValueError('Identity template fit cannot use 2025 reference labels')
    groups = {}
    rows = db.execute('''SELECT w.pre_state,w.outcome,w.extra,w.pattern_sha,p.template_json,count(*)
      FROM windows w JOIN patterns p ON p.sha256=w.pattern_sha
      WHERE w.supported=1 AND w.season IN (''' + ','.join('?' for _ in seasons) + ''')
      GROUP BY 1,2,3,4 ORDER BY 1,2,3,4''', seasons)
    for pre, outcome, extra, sha, text, n in rows:
        key = f'{pre}:{outcome}:{extra}'
        group = groups.setdefault(key, {'n': 0, 'patterns': []})
        group['n'] += n
        group['patterns'].append({'sha256': sha, 'n': n, 'actions': json.loads(text)})
    sources = {}
    for sha, artifact, first, last, game, pn in db.execute('''SELECT pattern_sha,artifact_id,first_source_row,last_source_row,game_id,first_pn
         FROM windows WHERE supported=1 AND season IN (''' + ','.join('?' for _ in seasons) + ''') ORDER BY season,first_source_row''', seasons):
        sources.setdefault(sha, {'artifact_id': artifact, 'first_source_row': first, 'last_source_row': last,
                                 'game_id': game, 'first_pn': pn})
    return {'version': 'identity-templates-1', 'training_seasons': seasons, 'groups': groups, 'sources': sources,
            'fallback_prior_count': 10, 'fallback': 'conservative explicit assumptions; unavailable results abstain'}


def template_choices(model, pre, outcome, extra):
    """Use empirical backoff across regimes, plus a labelled conservative prior."""
    group = model['groups'].get(f'{pre}:{outcome}:{int(extra)}')
    if group is None:
        group = model['groups'].get(f'{pre}:{outcome}:{1 - int(extra)}')
    candidates = []
    if group:
        candidates.extend((p['actions'], p['n'], 'empirical', p['sha256']) for p in group['patterns'])
    try:
        frame = example_frame(pre)
        plan = conservative_plan(frame, outcome)
        mapping = {frame.batter: 'B', **{r.player_id: str(i) for i, r in enumerate(frame.bases, 1) if r}}
        action = {'outcome': outcome, 'completed_pa': True, 'dropped_third_strike': False,
                  'moves': [{'role': mapping[m.player_id], 'origin': m.origin, 'destination': m.destination} for m in plan.moves]}
        candidates.append(([action], model['fallback_prior_count'], 'assumption', 'conservative-fixed-advance-1'))
    except (ValueError, UnsupportedRule):
        pass
    return candidates
