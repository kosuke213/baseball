"""Disjoint 2024 calibration fit/selection. 2025 is a known reference only."""
from __future__ import annotations

import json
import numpy as np

from data_collection.fetch import write_json
from ..empirical import fit
from ..empirical.analysis import basic_metrics, csv_file
from ..empirical.common import OUTCOMES


def adjust(p, q, parameters):
    values = np.power(p, 1 / parameters['temperature'])
    values /= values.sum(axis=1, keepdims=True)
    values = (1 - parameters['league_weight']) * values + parameters['league_weight'] * q
    return values / values.sum(axis=1, keepdims=True)


def detailed_scores(y, p, name, split):
    ll, brier = fit.score(y, p)
    rows, ece = fit.calibration(y, p, name, split)
    rare = np.isin(y, [2, 4, 5, 9, 10, 11, 13])
    return {**basic_metrics(ll, brier), **ece,
            'rare_true_class_n': int(rare.sum()),
            'rare_true_class_log_loss': float(ll[rare].mean()) if rare.any() else None}, rows, (ll, brier)


def date_splits(batch, dates):
    first = np.array([dates[g][0] for g in batch.games])
    last = np.array([dates[g][1] for g in batch.games])
    return ((batch.season == 2024) & (last < '2024-07-01'),
            (batch.season == 2024) & (first >= '2024-07-01'))


def run_calibration(batch, dates, output, config):
    inner = batch.subset(batch.season == 2023)
    h1mask, h2mask = date_splits(batch, dates)
    h1, h2 = batch.subset(h1mask), batch.subset(h2mask)
    if not len(h1.target) or not len(h2.target) or set(h1.games) & set(h2.games):
        raise ValueError('Calibration fit and selection games must be nonempty and disjoint')
    base = fit.fit_tables(fit.count_tables(inner), context_alpha=25, player_weight=0.5, training_seasons=[2023])
    data = {}
    for name, b in [('fit_2024_H1', h1), ('selection_2024_H2', h2)]:
        keep, y, p = fit.pa_prediction(b, fit.predict(b, base))
        _, _, q = fit.pa_prediction(b, fit.predict(b, base, 'league'))
        data[name] = (b, keep, y, p, q)
    # Parameters are learned on H1 only. H2 chooses among the four fitted methods.
    grids = {
        'identity': [(1.0, 0.0)],
        'temperature': [(t, 0.0) for t in config['temperatures']],
        'league_blend': [(1.0, w) for w in config['league_weights']],
        'temperature_blend': [(t, w) for t in config['temperatures'] for w in config['league_weights']],
    }
    fit_grid, methods = [], {}
    _, _, y, p, q = data['fit_2024_H1']
    for name, candidates in grids.items():
        rows = []
        for temperature, weight in candidates:
            parameters = {'temperature': temperature, 'league_weight': weight}
            ll, brier = fit.score(y, adjust(p, q, parameters))
            rows.append({'method': name, **parameters, **basic_metrics(ll, brier)})
        winner = min(rows, key=lambda r: (r['log_loss'], abs(r['temperature'] - 1) + r['league_weight']))
        fit_grid.extend(rows)
        methods[name] = {'temperature': winner['temperature'], 'league_weight': winner['league_weight']}
    csv_file(output / 'calibration_fit_grid.csv', fit_grid)
    metrics, calibration_rows, cached = [], [], {}
    for split, (_, keep, y, p, q) in data.items():
        for name, parameters in methods.items():
            predicted = adjust(p, q, parameters)
            scores, rows, vectors = detailed_scores(y, predicted, name, split)
            metrics.append({'period': split, 'method': name, **parameters, **scores})
            calibration_rows.extend(rows); cached[split, name] = vectors
    selection = {r['method']: r for r in metrics if r['period'] == 'selection_2024_H2'}
    original = selection['identity']
    eligible = [r for r in selection.values() if r['log_loss'] <= original['log_loss']
                and r['brier'] <= original['brier'] + 1e-8
                and r['top_label_ece'] <= original['top_label_ece'] + config['ece_guard_tolerance']]
    winner = min(eligible, key=lambda r: (r['log_loss'], 0 if r['method'] == 'identity' else 1))
    selected = winner['method']
    train = batch.subset(batch.season < 2025)
    final_model = fit.fit_tables(fit.count_tables(train), context_alpha=25, player_weight=0.5, training_seasons=[2023, 2024])
    reference = batch.subset(batch.season == 2025)
    reference_keep, reference_y, reference_p = fit.pa_prediction(reference, fit.predict(reference, final_model))
    _, _, reference_q = fit.pa_prediction(reference, fit.predict(reference, final_model, 'league'))
    for name, params in [('identity', methods['identity']), ('selected', methods[selected])]:
        scores, rows, vectors = detailed_scores(reference_y, adjust(reference_p, reference_q, params), name, 'known_reference_2025')
        metrics.append({'period': 'known_reference_2025', 'method': name, **params, **scores})
        calibration_rows.extend(rows); cached['known_reference_2025', name] = vectors
    # Report the separate rule fix, without selecting/retuning calibration on it.
    for split, b, keep, y, p, q in [('selection_2024_H2', *data['selection_2024_H2']),
                                   ('known_reference_2025', reference, reference_keep, reference_y, reference_p, reference_q)]:
        rule_p = adjust(p, q, methods[selected])
        rule_p[b.pre[keep] % 8 == 0, OUTCOMES.index('fielders_choice')] = 0
        rule_p /= rule_p.sum(axis=1, keepdims=True)
        scores, rows, vectors = detailed_scores(y, rule_p, 'selected_plus_FC_rule', split)
        metrics.append({'period': split, 'method': 'selected_plus_FC_rule', **methods[selected], **scores})
        calibration_rows.extend(rows)
    intervals = {}
    absolute_intervals = {}
    for split, chosen, b, keep in [('selection_2024_H2', selected, h2, data['selection_2024_H2'][1]),
                                  ('known_reference_2025', 'selected', reference, reference_keep)]:
        games = [g for g, k in zip(b.games, keep) if k]
        for index, metric in enumerate(('log_loss', 'brier')):
            intervals[split + ':' + metric] = fit.bootstrap_difference(games, cached[split, chosen][index],
                cached[split, 'identity'][index], config['seed'], config['bootstrap_repetitions'])
            absolute = fit.bootstrap_difference(games, cached[split, chosen][index], np.zeros(len(games)),
                                                 config['seed'], config['bootstrap_repetitions'])
            absolute['estimate'] = absolute.pop('difference_selected_minus_baseline')
            absolute_intervals[split + ':' + metric] = absolute
    record = {'version': 'calibration-1', 'fit_period': '2024-H1', 'selection_period': '2024-H2',
              'selected_method': selected, 'parameters': methods[selected], 'methods': methods,
              'fit_games': len(set(h1.games)), 'selection_games': len(set(h2.games)),
              'fit_pa': int(data['fit_2024_H1'][1].sum()), 'selection_pa': int(data['selection_2024_H2'][1].sum()),
              'spanning_cutoff_windows_excluded': int(((batch.season == 2024) & ~h1mask & ~h2mask).sum()),
              'independent_final_test_available': False,
              'evaluation_status': '2024 re-split is exploratory (stage6 already used 2024); 2025 is known reference, never a new untouched test',
              'refit_transfer_limit': 'H1 calibrator fitted to 2023-only OOS predictions is frozen and transferred to 2023-2024 base; no 2025 retuning',
              'selection_rule': 'H2 log loss with Brier and top-ECE non-degradation guards; identity remains if no admissible improvement',
              'rare_classes': [OUTCOMES[i] for i in (2, 4, 5, 9, 10, 11, 13)],
              'metrics': metrics, 'game_bootstrap': intervals, 'absolute_score_intervals': absolute_intervals}
    # Fitted parameters are a separate artifact: reference labels cannot alter it.
    fitted_fields = ('version', 'fit_period', 'selection_period', 'selected_method', 'parameters', 'methods',
                     'fit_games', 'selection_games', 'fit_pa', 'selection_pa', 'spanning_cutoff_windows_excluded',
                     'independent_final_test_available', 'evaluation_status', 'refit_transfer_limit', 'selection_rule')
    write_json(output / 'calibration.json', {k: record[k] for k in fitted_fields})
    write_json(output / 'calibration_evaluation.json', record)
    write_json(output / 'base_model.json', final_model)
    csv_file(output / 'calibration_metrics.csv', metrics)
    csv_file(output / 'class_calibration.csv', calibration_rows)
    # Finer bins for rare probabilities, without fitting or modifying predictions.
    detail = []
    class_scores = []
    for split, y, raw_p, q in [('selection_2024_H2', data['selection_2024_H2'][2], data['selection_2024_H2'][3], data['selection_2024_H2'][4]),
                              ('known_reference_2025', reference_y, reference_p, reference_q)]:
        for method, params in [('identity', methods['identity']), ('selected', methods[selected]), ('selected_plus_FC_rule', methods[selected])]:
            pp = adjust(raw_p, q, params)
            if method == 'selected_plus_FC_rule':
                population = h2 if split == 'selection_2024_H2' else reference
                completed = population.target < 14
                pp[population.pre[completed] % 8 == 0, OUTCOMES.index('fielders_choice')] = 0
                pp /= pp.sum(axis=1, keepdims=True)
            for col, label in enumerate(OUTCOMES[:-1]):
                observed = y == col
                binary_ll = np.zeros(len(y))
                binary_ll[observed] = -np.log(pp[observed, col])
                binary_ll[~observed] = -np.log1p(-pp[~observed, col])
                class_scores.append({'period': split, 'method': method, 'outcome': label, 'n': len(y),
                                     'true_count': int(observed.sum()), 'mean_predicted': float(pp[:, col].mean()),
                                     'observed_frequency': float(observed.mean()),
                                     'binary_log_loss': float(binary_ll.mean()),
                                     'binary_brier': float(np.mean((pp[:, col] - observed) ** 2)),
                                     'positive_class_log_loss': float(-np.log(pp[observed, col]).mean()) if observed.any() else None})
                edges = np.unique(np.quantile(pp[:, col], np.linspace(0, 1, 11)))
                assigned = np.searchsorted(edges[1:-1], pp[:, col], side='right')
                for bucket in np.unique(assigned):
                    mask = assigned == bucket
                    detail.append({'period': split, 'method': method, 'outcome': label, 'quantile_bin': int(bucket),
                                   'n': int(mask.sum()), 'predicted': float(pp[mask, col].mean()),
                                   'observed': float((y[mask] == col).mean()),
                                   'true_count': int((y[mask] == col).sum())})
    csv_file(output / 'rare_quantile_calibration.csv', detail)
    csv_file(output / 'class_scores.csv', class_scores)
    return final_model, record
