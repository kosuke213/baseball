"""Recover scoring-labelled routes from existing immutable CSVs, without fetching."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import hashlib
import json
import re
from pathlib import Path
import sqlite3

from data_collection import adapters
from data_collection.fetch import write_json
from ..calibrated.identity import recover, example_frame
from ..calibrated.rules import canonical
from .model import bind
from .rules import apply_play
from .paths import new_output

ROOT = Path(__file__).resolve().parents[2]


def input_paths(root=ROOT):
    c = json.loads((root / 'data_sources/stage7/config.json').read_text())
    return (root / 'data/research/stage5/snapshots' / c['input_stage5_snapshot'] / 'warehouse.sqlite3',
            root / 'data/research/stage6/snapshots' / c['input_stage6_snapshot'] / 'observations.sqlite3',
            root / 'data/research/pilot/raw', c)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024): h.update(block)
    return h.hexdigest()


def recover_with_evidence(row):
    """Repair an omitted LOB only when an explicit sole force out proves survivors.

    Retrosheet's fielding positions are never treated as player IDs. No final
    base or chronological order is fabricated for the surviving runners.
    """
    try:
        return recover(row)
    except ValueError as original:
        if not str(original).startswith('Unique missing participant set'):
            raise
        primary = row['event'].split('.')[0]
        match = re.fullmatch(r'[1-9]+\(([123])\)/FO(?:/[^.]*)?', primary)
        if (not match or row['pa'] != '1' or row['outs_pre'] != '2' or row['outs_post'] != '3'
                or row['runs'] != '0' or 'X' in row['event'].split('.', 1)[-1]):
            raise original
        retired = row['br' + match[1] + '_pre']
        participants = {row['batter'], *(row[f'br{i}_pre'] for i in (1, 2, 3) if row[f'br{i}_pre'])}
        survivors = participants - {retired}
        lob = {row[f'lob_id{i}'] for i in (1, 2, 3) if row[f'lob_id{i}']}
        if (not retired or not lob <= survivors or len(survivors) > 3
                or any(row[f'br{i}_post'] for i in (1, 2, 3))):
            raise original
        corrected = dict(row)
        for i, pid in enumerate(sorted(survivors) + [''] * (3 - len(survivors)), 1):
            corrected[f'lob_id{i}'] = pid
        result = recover(corrected)
        result['recovery_note'] = 'explicit_sole_force_third_out_identifies_omitted_LOB'
        return result


def enrich(row, action, global_roles):
    local = action['participants']
    moves = []
    for m in action['moves']:
        pid = next(pid for pid, role in local.items() if role == m['role'])
        if pid not in global_roles:
            raise ValueError('participant_substitution_inside_window')
        moves.append({**m, 'role': global_roles[pid]})
    hits = sum(int(row[k]) * i for k, i in [('single', 1), ('double', 2), ('triple', 3), ('hr', 4)])
    rbi_roles = []
    for suffix, pid in [('b', row['batter']), ('1', row['br1_pre']), ('2', row['br2_pre']), ('3', row['br3_pre'])]:
        if row['rbi' + ('_' if suffix == 'b' else '') + suffix] == '1':
            if not pid or pid not in global_roles:
                raise ValueError('unresolved_rbi_identity')
            rbi_roles.append(global_roles[pid])
    if len(rbi_roles) != int(row['rbi']):
        raise ValueError('rbi_total_disagrees_with_scorer_flags')
    out_roles = [m['role'] for m in moves if m['destination'] == 'OUT']
    bdest = next((m['destination'] for m in moves if m['role'] == 'B'), None)
    first_role = global_roles.get(row['br1_pre'])
    replaces_first = action['completed_pa'] and action['outcome'] in ('fielders_choice', 'reached_on_error') and first_role in out_roles and bdest in ('1', '2', '3')
    responsibility_complete = not (action['completed_pa'] and action['outcome'] in ('fielders_choice', 'reached_on_error') and out_roles and bdest in ('1', '2', '3') and not replaces_first)
    result = {'outcome': action['outcome'], 'completed_pa': action['completed_pa'],
        'dropped_third_strike': action['dropped_third_strike'], 'moves': moves,
        'credit': {'at_bat': row['ab'] == '1', 'hit_bases': hits, 'rbi_roles': rbi_roles,
                   'sacrifice_bunt': row['sh'] == '1', 'sacrifice_fly': row['sf'] == '1',
                   'ground_double_play': row['gdp'] == '1'},
        'batter_reached': hits or int(bdest in ('1', '2', '3', 'H')),
        'third_out': 'source_counted' if int(row['outs_post']) == 3 and int(row['runs']) else 'unspecified',
        'transfer_role': first_role if replaces_first else None, 'responsibility_complete': responsibility_complete,
        'event_text': row['event']}
    if action.get('recovery_note'): result['recovery_note'] = action['recovery_note']
    return result


def build(output, *, progress=print, seasons=(2023, 2024, 2025), source5=None, source6=None, cache=None, config=None):
    output = new_output(output)
    if output.exists():
        raise FileExistsError('Source build refuses to replace a published artifact directory')
    output.mkdir(parents=True)
    s5, s6, raw, defaults = input_paths()
    config = defaults if config is None else config
    source5, source6, cache = source5 or s5, source6 or s6, cache or raw
    if sha(source5) != config['stage5_database_sha256'] or sha(source6) != config['stage6_observations_sha256']:
        raise ValueError('Pinned source database mismatch')
    counts = Counter(); reasons = Counter(); groups = {}; sources = {}; raw_meta = []; examples = []
    with closing(sqlite3.connect('file:' + str(source5) + '?mode=ro', uri=True)) as db5, closing(sqlite3.connect('file:' + str(source6) + '?mode=ro', uri=True)) as db6:
        db6.row_factory = sqlite3.Row
        for year in seasons:
            progress(f'Source and scoring audit: {year}')
            meta = json.loads(db5.execute('SELECT metadata_json FROM artifacts WHERE artifact_id=?', (f'retro_plays_{year}',)).fetchone()[0])
            raw_meta.append(meta)
            blob = cache / 'blobs' / meta['sha256']
            if sha(blob) != meta['sha256']:
                raise ValueError('Immutable raw source checksum mismatch')
            raw_iter = iter(adapters.zipped_csv(blob.read_bytes(), f'{year}plays.csv'))
            current = next(raw_iter, None)
            for w in db6.execute('SELECT * FROM windows WHERE season=? ORDER BY first_source_row', (year,)):
                counts[f'{year}:windows'] += 1
                while current and current[0] < w['first_source_row']: current = next(raw_iter, None)
                rows = []
                while current and current[0] <= w['last_source_row']:
                    if current[1]['event'] != 'NP': rows.append(current)
                    current = next(raw_iter, None)
                try:
                    if not rows or rows[0][0] != w['first_source_row'] or rows[-1][0] != w['last_source_row'] or any('retrosheet:game:' + r['gid'] != w['game_id'] for _, r in rows):
                        raise RuntimeError('Source range alignment failed')
                    if w['actor_changed']:
                        raise ValueError('actor_changed_requires_lineup_parser')
                    if not w['transition_observed']:
                        raise ValueError('censored_end_requires_game_context_not_regular_template')
                    first = rows[0][1]
                    roles = {first['batter']: 'B', **{first[f'br{i}_pre']: str(i) for i in (1, 2, 3) if first[f'br{i}_pre']}}
                    actions = [enrich(r, recover_with_evidence(r), roles) for _, r in rows]
                    frame = example_frame(w['pre_state'])
                    mapping = {'B': frame.batter, **{str(i): r.player_id for i, r in enumerate(frame.bases, 1) if r}}
                    for a in actions:
                        frame = apply_play(frame, bind(a, mapping, 'empirical', 'source-validation')).transition.after
                    post = 24 if frame.outs == 3 else frame.outs * 8 + frame.base_mask
                    if (post, frame.score[0]) != (w['post_state'], w['runs']):
                        raise ValueError('projected_state_runs_disagree')
                    counts[f'{year}:supported'] += 1
                    counts[f'{year}:force_LOB_repairs'] += sum(bool(a.get('recovery_note')) for a in actions)
                    if year in (2023, 2024):
                        key = f'{w["pre_state"]}:{w["outcome"]}:{w["extra_innings"]}'
                        fingerprint = hashlib.sha256(canonical(actions).encode()).hexdigest()
                        group = groups.setdefault(key, {})
                        record = group.setdefault(fingerprint, {'sha256': fingerprint, 'n': 0, 'actions': actions})
                        record['n'] += 1
                        sources.setdefault(fingerprint, {'artifact_id': f'retro_plays_{year}', 'sha256': meta['sha256'], 'game_id': w['game_id'], 'first_source_row': w['first_source_row'], 'last_source_row': w['last_source_row']})
                        if len(examples) < 15 and any(a['third_out'] == 'source_counted' or any(m['role'] == 'B' and m['destination'] == 'OUT' for m in a['moves']) and a['credit']['hit_bases'] for a in actions):
                            examples.append({'source': sources[fingerprint], 'actions': actions})
                except (ValueError, KeyError) as exc:
                    reason = str(exc)
                    reasons[f'{year}:{reason}'] += 1
    model = {'version': 'scoring-routes-1', 'training_seasons': [2023, 2024],
             'stage7_model_version': json.loads((ROOT / 'data_sources/stage7/manifest.json').read_text())['snapshot_id'],
             'groups': {k: sorted(v.values(), key=lambda r: r['sha256']) for k, v in sorted(groups.items())},
             'sources': sources, 'prior_count': 10,
             'limits': ['censored game endings are excluded from ordinary-half templates',
                        'source_counted uses source adjudication, not recovered out/run timestamps',
                        'only 2023-2024 windows contribute to routes; 2025 is known reference']}
    write_json(output / 'routes.json', model)
    write_json(output / 'source_audit.json', {'counts': dict(counts), 'reasons': dict(reasons),
               'raw_artifacts': raw_meta, 'source_examples': examples,
               'route_groups': len(groups), 'route_patterns': len(sources),
               'input_sha256': {'stage5': config['stage5_database_sha256'], 'stage6': config['stage6_observations_sha256']},
               'new_play_data_requests': 0})
    return model
