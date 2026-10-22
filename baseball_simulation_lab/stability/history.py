"""Versioned extension of Journal; old Stage 7 logs retain their old interpreter."""
from __future__ import annotations

from pathlib import Path
import json

from ..calibrated.replay import Journal, hash_record, perform as legacy_perform
from ..calibrated.rules import canonical, fingerprint, frame_dict, frame_from_dict
from .rules import GameRules, RULES_VERSION, apply_play, next_half, play_from_dict


def perform(frame, operation, parameters):
    if operation == 'play_v2':
        applied = apply_play(frame, play_from_dict(parameters))
        return applied.transition.after, applied
    if operation == 'advance_half_v2':
        return next_half(frame, GameRules(**parameters)), None
    if operation in ('substitute', 'change_pitcher'):
        return legacy_perform(frame, operation, parameters), None
    if operation in ('draw', 'stop', 'finish'):
        if operation == 'finish' and not frame.finished:
            raise ValueError('Finished record requires a finished game state')
        return frame, None
    raise ValueError('Unknown fullgame journal operation')


class GameJournal(Journal):
    """Journal hash-chain protocol plus new versioned operations and memory mode.

    Legacy replay remains untouched. Shared hashes, Frame codec, legacy control
    interpreter and Journal's no-overwrite discipline are retained.
    """
    def __init__(self, initial, request, model_version, path=None):
        self.path = Path(path) if path else None
        self.current = initial.validate(); self.model_version = model_version; self.sequence = 0
        header = {'format': 'stability-journal-1', 'rules_version': RULES_VERSION,
                  'storage_schema_version': 'stability-history-1', 'model_version': model_version, 'seed': request['seed'], 'request': request,
                  'initial': frame_dict(initial)}
        self.previous = hash_record(header)
        self.rows = [{'header': header, 'hash': self.previous}]
        if self.path:
            with self.path.open('x', encoding='utf-8', newline='\n') as f:
                f.write(canonical(self.rows[0]) + '\n')

    def append(self, operation, parameters):
        after, applied = perform(self.current, operation, parameters)
        record = {'sequence': self.sequence + 1, 'before': fingerprint(self.current), 'after': fingerprint(after),
                  'operation': operation, 'parameters': parameters, 'rules_version': RULES_VERSION,
                  'model_version': self.model_version, 'previous': self.previous}
        sha = hash_record(record); row = {'event': record, 'hash': sha}
        if self.path:
            with self.path.open('a', encoding='utf-8', newline='\n') as f: f.write(canonical(row) + '\n')
        self.rows.append(row)
        self.current, self.previous = after, sha; self.sequence += 1
        return after, applied

    def record_window(self, result):
        raise TypeError('Fullgame history requires scoring-labelled play_v2 events, not a Stage 7 WindowResult')


def replay_rows(rows, *, observer=None):
    first = rows[0]; header = first['header']
    if (header['format'] != 'stability-journal-1' or header['rules_version'] != RULES_VERSION
            or hash_record(header) != first['hash']):
        raise ValueError('Unknown/corrupt fullgame journal header')
    frame = frame_from_dict(header['initial']); previous = first['hash']
    for sequence, row in enumerate(rows[1:], 1):
        e = row['event']
        if (hash_record(e) != row['hash'] or e['previous'] != previous or e['sequence'] != sequence
                or e['before'] != fingerprint(frame) or e['rules_version'] != RULES_VERSION
                or e['model_version'] != header['model_version']):
            raise ValueError('Journal hash, state, sequence or version mismatch')
        before = frame; frame, applied = perform(frame, e['operation'], e['parameters'])
        if e['after'] != fingerprint(frame): raise ValueError('Replayed state fingerprint differs')
        if observer: observer(before, frame, e['operation'], e['parameters'], applied)
        previous = row['hash']
    return frame


def replay(path):
    return replay_rows([json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()])
