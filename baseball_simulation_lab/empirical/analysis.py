"""Temporal validation, held-out scoring, calibration and probability exports."""
from __future__ import annotations

from collections import defaultdict
import csv
from itertools import groupby
import json
import math

import numpy as np

from data_collection.fetch import write_json
from . import fit
from .common import END, OUTCOMES, canonical, feature_keys


def csv_file(path, rows, fields=None):
    rows = iter(rows)
    first = next(rows, None)
    fields = fields or (list(first) if first is not None else ['status'])
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        if first is not None:
            writer.writerow(first)
        writer.writerows(rows)


def basic_metrics(ll, brier):
    return {'n': int(len(ll)), 'log_loss': float(np.mean(ll)) if len(ll) else None,
            'brier': float(np.mean(brier)) if len(ll) else None}


def analyze(db, output, config, progress=print):
    batch = fit.load_batch(db)
    inner = batch.subset(batch.season == 2023)
    valid = batch.subset(batch.season == 2024)
    train = batch.subset(batch.season < 2025)
    test = batch.subset(batch.season == 2025)
    if set(train.games) & set(test.games) or set(inner.games) & set(valid.games):
        raise ValueError('Temporal split has overlapping game IDs')
    inner_counts = fit.count_tables(inner)
    grid = []
    for alpha in config['context_alphas']:
        for weight in config['player_weights']:
            model = fit.fit_tables(inner_counts, context_alpha=alpha, player_weight=weight, training_seasons=[2023])
            pred = fit.predict(valid, model)
            _, y, p = fit.pa_prediction(valid, pred)
            ll, brier = fit.score(y, p)
            row = {'training': '2023', 'validation': '2024', 'context_alpha': alpha, 'player_weight': weight, **basic_metrics(ll, brier)}
            grid.append(row)
    selected = min(grid, key=lambda row: (row['log_loss'], row['player_weight'], row['context_alpha']))
    csv_file(output / 'validation_grid.csv', grid)
    progress('Selected on 2024 only: ' + canonical(selected))
    inner_model = fit.fit_tables(inner_counts, context_alpha=selected['context_alpha'], player_weight=selected['player_weight'], training_seasons=[2023])
    validation_pred = fit.predict(valid, inner_model)
    kernel_grid = []
    for alpha in config['kernel_alphas']:
        kernels = fit.fit_kernels(inner, alpha)
        scores = fit.transition_scores(valid, validation_pred, kernels)
        keep = valid.transition_valid.astype(bool)
        kernel_grid.append({'training': '2023', 'validation': '2024', 'kernel_alpha': alpha,
                            **basic_metrics(scores['joint'][0][keep], scores['joint'][1][keep])})
    selected_kernel = min(kernel_grid, key=lambda row: (row['log_loss'], row['kernel_alpha']))
    csv_file(output / 'transition_validation_grid.csv', kernel_grid)
    counts = fit.count_tables(train)
    model = fit.fit_tables(counts, context_alpha=selected['context_alpha'], player_weight=selected['player_weight'], training_seasons=[2023, 2024])
    model['input_contract'] = {
        'features': ['observed_window_pre_outs', 'observed_window_pre_bases', 'published_batter_hand',
                     'published_pitcher_hand', 'inning_band', 'batting_score_diff_band', 'half', 'pre_window_batter_id', 'pre_window_pitcher_id'],
        'excluded': ['terminal_count', 'pitch_sequence', 'post_state', 'runs', 'realized_outcome', 'game_final',
                     '2025_performance', 'future_player_biography', 'speed', 'spin', 'launch_angle'],
        'fallback': 'unseen context -> hands -> league; unseen player -> league; legal outcome mask applied last',
        'pa_probability': 'conditional on completed PA; excludes runner-only third-out windows',
        'source_hand_B': 'published switch-hitter category; actual batting stance is not inferred',
    }
    kernels = fit.fit_kernels(train, selected_kernel['kernel_alpha'])
    write_json(output / 'model.json', model)
    write_json(output / 'kernels.json', kernels)
    results, calibration_rows, paired = [], [], {}
    for name in ('uniform', 'league', 'hands', 'context', 'selected'):
        predictions = fit.predict(test, model, name)
        keep, y, p = fit.pa_prediction(test, predictions)
        ll, brier = fit.score(y, p)
        rows, ece = fit.calibration(y, p, name, 'test_2025')
        calibration_rows.extend(rows)
        for group, mask in [('all', np.ones(len(y), dtype=bool)), ('regulation', test.extra[keep] == 0), ('extra_innings', test.extra[keep] == 1)]:
            results.append({'task': 'completed_PA_14_classes', 'model': name, 'split': 'test_2025', 'group': group,
                            **basic_metrics(ll[mask], brier[mask]), **(ece if group == 'all' else {})})
        if name in ('league', 'selected'):
            paired[name] = (ll, brier)
        if name == 'selected':
            selected_pred = predictions
            step_scores = fit.score(test.target, predictions)
            results.append({'task': 'observed_window_15_classes', 'model': name, 'split': 'test_2025', 'group': 'all',
                            **basic_metrics(*step_scores)})
    transitions = fit.transition_scores(test, selected_pred, kernels)
    valid_transition = test.transition_valid.astype(bool)
    for task in ('joint', 'state', 'runs'):
        for prefix, name in [('', 'selected'), ('baseline_', 'state_empirical')]:
            for group, mask in [('all', valid_transition), ('regulation', valid_transition & (test.extra == 0)),
                                ('extra_innings', valid_transition & (test.extra == 1))]:
                results.append({'task': 'window_next_' + task, 'model': name, 'split': 'test_2025', 'group': group,
                                **basic_metrics(transitions[prefix + task][0][mask], transitions[prefix + task][1][mask])})
    csv_file(output / 'evaluation_metrics.csv', results,
             ['task', 'model', 'split', 'group', 'n', 'log_loss', 'brier', 'macro_class_ece', 'top_label_ece'])
    csv_file(output / 'calibration.csv', calibration_rows)
    test_pa_indices = np.flatnonzero(test.target < len(OUTCOMES) - 1)
    games = [test.games[i] for i in test_pa_indices]
    intervals = {}
    for index, metric in enumerate(('log_loss', 'brier')):
        intervals['pa_' + metric] = fit.bootstrap_difference(games, paired['selected'][index], paired['league'][index],
                                                             config['seed'], config['bootstrap_repetitions'])
        indices = np.flatnonzero(valid_transition)
        intervals['transition_joint_' + metric] = fit.bootstrap_difference(
            [test.games[i] for i in indices], transitions['joint'][index][indices], transitions['baseline_joint'][index][indices],
            config['seed'], config['bootstrap_repetitions'])
    evaluation = {'split': {'inner_train': [2023], 'validation': [2024], 'refit': [2023, 2024], 'test': [2025],
                            'rule': '2025 labels are never passed to fit or hyperparameter selection'},
                  'selected_pa_settings': selected, 'selected_transition_settings': selected_kernel,
                  'training_windows': len(train.target), 'training_completed_pa': int((train.target < 14).sum()),
                  'test_windows': len(test.target), 'test_completed_pa': int((test.target < 14).sum()),
                  'test_transition_windows': int(valid_transition.sum()), 'metrics': results, 'game_bootstrap': intervals,
                  'definitions': {'log_loss': 'natural logarithm, nats per observation; lower is better; no probability clipping',
                                  'brier': 'sum over all classes of (p-one_hot)^2, range 0..2; no division by class count',
                                  'ece': '10 fixed equal-width probability bins; macro class ECE and top-label ECE',
                                  'transition': 'Joint post-state/runs predicted BEFORE outcome, marginalizing all 15 outcomes',
                                  'censoring': 'All final windows before third out excluded from transition fitting/scoring; completed PA labels retained',
                                  'calibration_limit': 'ECE depends on binning and is descriptive; intervals resample games, not seasons'},
                  'coverage': {'unseen_test_batters_windows': sum(k not in model['tables']['batter'] for k in test.keys['batter']),
                               'unseen_test_pitchers_windows': sum(k not in model['tables']['pitcher'] for k in test.keys['pitcher']),
                               'unseen_test_context_windows': sum(k not in model['tables']['context'] for k in test.keys['context'])}}
    write_json(output / 'evaluation.json', evaluation)
    export_probabilities(output, model, kernels)
    examples(output, model, kernels)
    return evaluation


def export_probabilities(output, model, kernels):
    def rows():
        settings = model['settings']
        for name in ('league', 'hands', 'context', 'batter', 'pitcher'):
            groups = {'all': model['tables']['league']} if name == 'league' else model['tables'][name]
            for key, table in groups.items():
                alpha = 7.5 if name == 'league' else settings['context_alpha'] if name == 'context' else settings['hands_alpha'] if name == 'hands' else settings['player_alpha']
                for label, count, p in zip(OUTCOMES, table['counts'], table['p']):
                    yield {'component': name, 'key': key, 'n': table['n'], 'outcome': label, 'count': count,
                           'probability': p, 'data_weight': table['n'] / (table['n'] + alpha),
                           'conditional_posterior_sd': math.sqrt(p * (1 - p) / (table['n'] + alpha + 1))}
    csv_file(output / 'probability_components.csv', rows())
    def transition_rows():
        for key, table in kernels['conditional'].items():
            pre, outcome, extra = key.split(':')
            for (post, runs), count, p in zip(table['targets'], table['counts'], table['p']):
                yield {'pre_state': pre, 'outcome': outcome, 'extra_innings': extra, 'n': table['n'],
                       'pooled_n': table['pooled_n'], 'post_state': post, 'runs': runs, 'count': count, 'probability': p,
                       'prior_only_cell': int(count == 0)}
    csv_file(output / 'transition_probabilities.csv', transition_rows())


def examples(output, model, kernels):
    from .api import EmpiricalModel
    api = EmpiricalModel(model, kernels)
    rows = []
    for bh, ph, outs, bases, inning, diff in [('L', 'R', 0, 0, 1, 0), ('R', 'R', 0, 0, 1, 0),
                                             ('L', 'R', 1, 1, 5, 0), ('B', 'L', 2, 7, 9, -3),
                                             ('R', 'L', 0, 2, 10, 0)]:
        features = dict(outs=outs, bases=bases, batter_hand=bh, pitcher_hand=ph, inning=inning, batting_score_diff=diff, half=0)
        p = api.predict_pa(**features)
        keys = feature_keys(**features)
        context = model['tables']['context'].get(keys['context'])
        joint = api.predict_next_state_runs(**features)
        rows.append({'features': features, 'training_context_n': context['n'] if context else 0,
                     'pa_probabilities': p, 'expected_step_runs': sum(r['runs'] * r['probability'] for r in joint)})
    write_json(output / 'examples.json', rows)


def descriptive_exports(db, output):
    db.row_factory = __import__('sqlite3').Row
    frequencies = []
    for name, years in [('2023', [2023]), ('2024', [2024]), ('2025', [2025]), ('train_2023_2024', [2023, 2024])]:
        counts = dict(db.execute('SELECT outcome,count(*) FROM plays WHERE pa=1 AND season IN (' + ','.join('?' for _ in years) + ') GROUP BY outcome', years))
        total = sum(counts.values())
        for outcome in OUTCOMES[:-1]:
            frequencies.append({'split': name, 'outcome': outcome, 'count': counts.get(outcome, 0), 'completed_pa': total,
                                'frequency': counts.get(outcome, 0) / total})
    csv_file(output / 'outcome_frequencies.csv', frequencies)
    def transition_rows():
        for unit, query in [
            ('play', '''SELECT p.season,p.inning>=10 extra,p.pre_state,p.post_state,p.runs,count(*) n
               FROM plays p LEFT JOIN windows w ON w.game_id=p.game_id AND w.last_pn=p.pn
               WHERE coalesce(w.transition_observed,1)=1 GROUP BY 1,2,3,4,5'''),
            ('observed_pa_window', '''SELECT season,extra_innings extra,pre_state,post_state,runs,count(*) n
               FROM windows WHERE transition_observed=1 GROUP BY 1,2,3,4,5''')]:
            rows = list(db.execute(query))
            totals = defaultdict(int)
            for row in rows:
                totals[row['season'], row['extra'], row['pre_state']] += row['n']
            for row in rows:
                yield {'unit': unit, **dict(row), 'state_n': totals[row['season'], row['extra'], row['pre_state']],
                       'probability': row['n'] / totals[row['season'], row['extra'], row['pre_state']]}
    csv_file(output / 'transition_counts.csv', transition_rows())
    csv_file(output / 'censored_windows.csv', (dict(r) for r in db.execute('SELECT * FROM windows WHERE transition_observed=0 ORDER BY game_id,first_pn')))
    csv_file(output / 'excluded_nonplays.csv', (dict(r) for r in db.execute('SELECT * FROM exclusions ORDER BY game_id,pn')))
    def stats_rows():
        for role in ('batter', 'pitcher'):
            for row in db.execute(f'SELECT season,{role} player_id,outcome,count(*) n FROM plays WHERE pa=1 GROUP BY 1,2,3 ORDER BY 1,2,3'):
                yield {'role': role, **dict(row), 'actor_definition': 'terminal source-row actor; not retrospective official substitution credit'}
    csv_file(output / 'player_observed_stats.csv', stats_rows())
    moments = defaultdict(list)
    censored_halves = defaultdict(int)
    complete_halves = defaultdict(int)
    rows = db.execute('SELECT * FROM windows ORDER BY game_id,first_pn')
    for identity, group in groupby(rows, key=lambda r: (r['game_id'], r['inning'], r['half'])):
        half = list(group)
        split = 'test_2025' if half[0]['season'] == 2025 else 'train_2023_2024'
        population = split, half[0]['extra_innings']
        if half[-1]['post_state'] != END:
            censored_halves[population] += 1
            continue
        complete_halves[population] += 1
        future_runs = 0
        for row in reversed(half):
            future_runs += row['runs']
            split = 'test_2025' if row['season'] == 2025 else 'train_2023_2024'
            moments[split, row['extra_innings'], row['pre_state']].append(future_runs)
    rows = []
    for split in ('train_2023_2024', 'test_2025'):
        for extra in (0, 1):
            for pre in range(24):
                values = moments[split, extra, pre]
                rows.append({'split': split, 'extra_innings': extra, 'pre_state': pre, 'outs': pre // 8, 'bases': pre % 8,
                             'n_windows': len(values), 'mean_runs_until_third_out': float(np.mean(values)) if values else '',
                             'sd': float(np.std(values, ddof=1)) if len(values) > 1 else '',
                             'complete_halves_in_population': complete_halves[split, extra],
                             'excluded_censored_halves_in_population': censored_halves[split, extra]})
    csv_file(output / 'run_expectancy.csv', rows)
    return {'complete_halves': sum(complete_halves.values()), 'censored_halves': sum(censored_halves.values())}
