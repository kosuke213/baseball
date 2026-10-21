"""Append-only event journal; replay uses recorded decisions, not a new model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .rules import (RULES_VERSION, Transition, UnsupportedRule, advance_half, apply_plan, canonical,
                    change_pitcher, count_event, fingerprint, frame_dict, frame_from_dict,
                    plan_dict, plan_from_dict, substitute)


def hash_record(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def perform(frame, operation, parameters):
    if operation == 'play':
        result = apply_plan(frame, plan_from_dict(parameters))
    elif operation == 'advance_half':
        result = advance_half(frame, **parameters)
    elif operation == 'substitute':
        result = substitute(frame, **parameters)
    elif operation == 'change_pitcher':
        result = change_pitcher(frame, **parameters)
    elif operation == 'count':
        result = count_event(frame, **parameters)
    else:
        raise UnsupportedRule('Unknown journal operation')
    return result.after if isinstance(result, Transition) else result


class Journal:
    def __init__(self, path, initial, model_version, seed=None):
        self.path = Path(path)
        initial.validate()
        header = {'format': 'identity-journal-1', 'rules_version': RULES_VERSION,
                  'model_version': model_version, 'seed': seed, 'initial': frame_dict(initial)}
        self.previous = hash_record(header)
        with self.path.open('x', encoding='utf-8', newline='\n') as file:
            file.write(canonical({'header': header, 'hash': self.previous}) + '\n')
        self.current = initial
        self.sequence = 0
        self.model_version = model_version

    def append(self, operation, parameters):
        after = perform(self.current, operation, parameters)
        record = {'sequence': self.sequence + 1, 'before': fingerprint(self.current), 'after': fingerprint(after),
                  'operation': operation, 'parameters': parameters, 'rules_version': RULES_VERSION,
                  'model_version': self.model_version, 'previous': self.previous}
        sha = hash_record(record)
        with self.path.open('a', encoding='utf-8', newline='\n') as file:
            file.write(canonical({'event': record, 'hash': sha}) + '\n')
        self.current, self.previous = after, sha
        self.sequence += 1
        return after

    def record_window(self, result):
        if result.model_version != self.model_version:
            raise ValueError('Sampled model version differs from the frozen journal')
        for transition in result.transitions:
            self.append('play', plan_dict(transition.plan))
            if self.current != transition.after:
                raise ValueError('Journal and sampled window disagree')
        return self.current


def replay(path):
    with Path(path).open(encoding='utf-8') as file:
        first = json.loads(next(file))
        header = first['header']
        if hash_record(header) != first['hash'] or header['rules_version'] != RULES_VERSION:
            raise UnsupportedRule('Journal header/version mismatch; use its matching rules implementation')
        frame = frame_from_dict(header['initial'])
        previous = first['hash']
        for sequence, line in enumerate(file, 1):
            row = json.loads(line); event = row['event']
            if (hash_record(event) != row['hash'] or event['previous'] != previous
                    or event['sequence'] != sequence or event['before'] != fingerprint(frame)
                    or event['rules_version'] != RULES_VERSION or event['model_version'] != header['model_version']):
                raise ValueError('Journal chain, state or version mismatch')
            frame = perform(frame, event['operation'], event['parameters'])
            if fingerprint(frame) != event['after']:
                raise ValueError('Replayed state differs from immutable event record')
            previous = row['hash']
    return frame
