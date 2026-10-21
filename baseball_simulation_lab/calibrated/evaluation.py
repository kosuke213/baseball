"""Common-target comparisons. Unsupported identity mass is explicit, not clipped."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from itertools import groupby
import json
import random

import numpy as np

from data_collection.fetch import write_json
from ..empirical import fit
from ..empirical.analysis import csv_file
from ..empirical.common import OUTCOMES
from .api import CalibratedModel
from .calibration import adjust, date_splits
from .identity import example_frame, fit_templates, project, template_choices
from .rules import UnsupportedRule


def calibrated_step(batch, base, parameters):
    p = fit.predict(batch, base)
    keep, _, completed = fit.pa_prediction(batch, p)
    _, _, league = fit.pa_prediction(batch, fit.predict(batch, base, 'league'))
    p[keep, :-1] = adjust(completed, league, parameters) * (1 - p[keep, -1, None])
    # Runner-only windows need the same PA distribution too (not their true class).
    other = ~keep
    if other.any():
        pp = p[other, :-1].copy(); pp /= pp.sum(axis=1, keepdims=True)
        q = fit.predict(batch.subset(other), base, 'league')[:, :-1]; q /= q.sum(axis=1, keepdims=True)
        p[other, :-1] = adjust(pp, q, parameters) * (1 - p[other, -1, None])
    return p


def projection_matrix(templates, pre, extra):
    matrix = np.zeros((15, 126))  # final cell is explicit unsupported/abstain mass
    for col, outcome in enumerate(OUTCOMES):
        choices = template_choices(templates, pre, outcome, extra)
        total = sum(c[1] for c in choices)
        if not total:
            matrix[col, 125] = 1
        for actions, weight, _, _ in choices:
            post, runs = project(actions, pre)
            matrix[col, post * 5 + runs] += weight / total
    return matrix


def identity_rule_mask(probabilities, pre_states):
    p = probabilities.copy()
    aborted = p[:, -1].copy()
    p[pre_states % 8 == 0, OUTCOMES.index('fielders_choice')] = 0
    p[:, :-1] *= ((1 - aborted) / p[:, :-1].sum(axis=1))[:, None]
    return p


def summarize(ll, brier):
    finite = np.isfinite(ll)
    return {'n': len(ll), 'log_loss': float(ll.mean()) if finite.all() else None,
            'infinite_log_loss': not bool(finite.all()), 'zero_probability_targets': int((~finite).sum()),
            'positive_target_coverage': float(finite.mean()), 'brier': float(brier.mean()),
            'supported_stratum_log_loss': float(ll[finite].mean()) if finite.any() else None}


def compare_transitions(batch, dates, identity_db, final_model, calibration, output, config):
    rows, intervals, support_rows = [], {}, []
    inner = batch.subset(batch.season == 2023)
    _, h2mask = date_splits(batch, dates)
    periods = [('selection_2024_H2_exploratory', batch.subset(h2mask), [2023]),
               ('known_reference_2025', batch.subset(batch.season == 2025), [2023, 2024])]
    final_templates = None
    for period, b, seasons in periods:
        trained = inner if seasons == [2023] else batch.subset(batch.season < 2025)
        base = fit.fit_tables(fit.count_tables(trained), context_alpha=25, player_weight=0.5, training_seasons=seasons)
        kernels = fit.fit_kernels(trained, 100)
        templates = fit_templates(identity_db, seasons)
        if len(seasons) == 2:
            final_templates = templates
            write_json(output / 'identity_model.json', templates)
            write_json(output / 'kernels.json', kernels)
        predicted = calibrated_step(b, base, calibration['parameters'])
        id_predicted = identity_rule_mask(predicted, b.pre)
        aggregate = fit.transition_scores(b, predicted, kernels)
        valid = b.transition_valid.astype(bool)
        indices = np.flatnonzero(valid)
        ll = np.full(len(b.target), np.nan); brier = np.full(len(b.target), np.nan)
        abstention = np.zeros(len(b.target))
        for pre in range(24):
            for extra in (0, 1):
                group = indices[(b.pre[indices] == pre) & (b.extra[indices] == extra)]
                matrix = projection_matrix(templates, pre, extra)
                if len(seasons) == 2:
                    for col, outcome in enumerate(OUTCOMES):
                        table = kernels['conditional'].get(f'{pre}:{outcome}:{extra}')
                        if table:
                            for (post, runs), probability, count in zip(table['targets'], table['p'], table['counts']):
                                support_rows.append({'pre_state': pre, 'outcome': outcome, 'extra': extra,
                                    'post_state': post, 'runs': runs, 'stage6_probability': probability,
                                    'observed_count': count, 'id_route_in_supported_contract': int(matrix[col, post * 5 + runs] > 0)})
                if not len(group):
                    continue
                joint = id_predicted[group] @ matrix
                truth = joint[np.arange(len(group)), b.post[group] * 5 + b.runs[group]]
                positive = truth > 0
                local_ll = np.full(len(group), np.inf); local_ll[positive] = -np.log(truth[positive])
                ll[group] = local_ll
                brier[group] = (joint * joint).sum(axis=1) - 2 * truth + 1
                abstention[group] = joint[:, 125]
        for name, values in [('state_only', aggregate['baseline_joint']), ('result_conditional', aggregate['joint']),
                             ('identity_rules', (ll, brier))]:
            rows.append({'period': period, 'model': name, **summarize(values[0][valid], values[1][valid]),
                         'mean_abstention_mass': float(abstention[valid].mean()) if name == 'identity_rules' else 0})
        games = [b.games[i] for i in indices]
        intervals[period + ':identity_brier_vs_state'] = fit.bootstrap_difference(games, brier[valid], aggregate['baseline_joint'][1][valid],
                                                                                 config['seed'], config['bootstrap_repetitions'])
        # Fair diagnostic comparison on the SAME positive-support stratum for all models.
        common = valid & np.isfinite(ll)
        for name, values in [('state_only', aggregate['baseline_joint']), ('result_conditional', aggregate['joint']), ('identity_rules', (ll, brier))]:
            rows.append({'period': period + ':positive_support_diagnostic', 'model': name,
                         **summarize(values[0][common], values[1][common]), 'mean_abstention_mass': None})
    csv_file(output / 'transition_comparison.csv', rows)
    csv_file(output / 'coarse_support_audit.csv', support_rows)
    record = {'target': 'observed-window post-state/runs, 125 physical cells + explicit abstention cell',
              'identity_transition_mode': 'empirical templates plus declared conservative prior (allow_assumptions=True); API default is empirical-only',
              'additional_identity_rule_mask': 'FC result impossible with no preceding runner; separate from calibration-only comparisons',
              'interpretation': 'same coarse target; individual trajectories are a different target and have no directly comparable accuracy score',
              'zero_policy': 'zero probability means infinite log loss, serialized as null plus infinite_log_loss=true; never clipped',
              'diagnostic_limit': 'positive-support subset depends on realized target, so it is NOT an all-population performance claim',
              'witness_limit': 'no supported ID route is a bounded-contract limitation, not proof that the real play is universally illegal',
              'metrics': rows, 'game_bootstrap': intervals}
    write_json(output / 'transition_evaluation.json', record)
    return final_templates, record


def simulations(base_model, kernels, templates, calibration, source_db, output, config, progress=print):
    api = CalibratedModel(base_model, kernels, templates, calibration, 'stage7-simulation-frozen')
    starts = {i: example_frame(i) for i in range(24)}
    state_draws = {i: ([(p, r) for p, r in kernels['state_baseline'][f'{i}:0']['targets']], kernels['state_baseline'][f'{i}:0']['p']) for i in range(24)}
    old = api.base
    summaries, distributions, movement_rows = [], [], []
    for mode in ('state_only', 'result_conditional', 'identity_rules'):
        rng = random.Random(config['seed'])
        outcomes = Counter(); movements = Counter(); failures = Counter()
        runs_values, steps_values = [], []
        assumed = empirical = 0
        for trial in range(config['simulation_halves']):
            frame = starts[0]
            pre = 0; runs_total = 0; steps = 0
            trial_outcomes = Counter(); trial_movements = Counter()
            try:
                while pre != 24:
                    steps += 1
                    if steps > 500:
                        raise UnsupportedRule('Half-inning step guard; no fabricated result')
                    if mode == 'state_only':
                        choices, weights = state_draws[pre]
                        pre, runs = rng.choices(choices, weights=weights, k=1)[0]
                        runs_total += runs
                    elif mode == 'result_conditional':
                        step = old.sample_step(rng, outs=pre // 8, bases=pre % 8, inning=1, half=0)
                        pre = 24 if step.half_ended else step.outs_after * 8 + step.bases_after
                        runs_total += step.runs
                        trial_outcomes[step.outcome] += int(step.completed_pa)
                    else:
                        result = api.sample(frame, rng, allow_assumptions=True)
                        for transition in result.transitions:
                            assumed += transition.plan.source == 'assumption'
                            empirical += transition.plan.source == 'empirical'
                            for move in transition.plan.moves:
                                if move.origin:
                                    trial_movements[f'{move.origin}->{move.destination}'] += 1
                            if transition.completed_pa:
                                trial_outcomes[transition.plan.outcome] += 1
                        frame = result.after
                        runs_total = frame.score[0]
                        pre = 24 if frame.outs == 3 else frame.outs * 8 + frame.base_mask
                runs_values.append(runs_total); steps_values.append(steps)
                outcomes.update(trial_outcomes); movements.update(trial_movements)
            except (UnsupportedRule, ValueError) as exc:
                failures[str(exc)] += 1
            if (trial + 1) % 2500 == 0:
                progress(f'Simulation {mode}: {trial + 1}/{config["simulation_halves"]}')
        completed = len(runs_values); pa = sum(outcomes.values())
        mean = float(np.mean(runs_values)) if completed else None
        summaries.append({'model': mode, 'attempted_halves': config['simulation_halves'], 'completed_halves': completed,
                          'failed_halves': sum(failures.values()), 'mean_runs_completed_only': mean,
                          'sd_runs': float(np.std(runs_values, ddof=1)) if completed > 1 else None,
                          'mean_steps_completed_only': float(np.mean(steps_values)) if completed else None,
                          'outs_per_completed_half': 3, 'completed_pa': pa if mode != 'state_only' else None,
                          'hit_rate': sum(outcomes[k] for k in ('single', 'double', 'triple', 'home_run')) / pa if pa else None,
                          'walk_rate': outcomes['walk'] / pa if pa else None, 'home_run_rate': outcomes['home_run'] / pa if pa else None,
                          'assumed_actions_attempted': assumed, 'empirical_actions_attempted': empirical,
                          'failures': dict(failures)})
        for value, n in sorted(Counter(runs_values).items()):
            distributions.append({'population': mode, 'runs': value, 'n': n, 'completed_halves': completed})
        for route, n in sorted(movements.items()):
            movement_rows.append({'population': mode, 'movement': route, 'n': n})
    # Observed complete regular halves; reporting labels and dates are not fit inputs.
    for year in (2024, 2025):
        observed_runs, observed_steps = [], []
        event_counts = Counter()
        for _, rows in groupby(source_db.execute('SELECT game_id,inning,half,post_state,runs,outcome,completed_pa FROM windows WHERE season=? AND inning<10 ORDER BY game_id,first_pn', (year,)), key=lambda row: row[:3]):
            half = list(rows)
            if half[-1][3] != 24:
                continue
            observed_runs.append(sum(r[4] for r in half)); observed_steps.append(len(half))
            event_counts.update(r[5] for r in half if r[6])
        pa = sum(event_counts.values())
        summaries.append({'model': f'observed_complete_regular_{year}', 'attempted_halves': len(observed_runs),
            'completed_halves': len(observed_runs), 'failed_halves': 0, 'mean_runs_completed_only': float(np.mean(observed_runs)),
            'sd_runs': float(np.std(observed_runs, ddof=1)), 'mean_steps_completed_only': float(np.mean(observed_steps)),
            'outs_per_completed_half': 3, 'completed_pa': pa,
            'hit_rate': sum(event_counts[k] for k in ('single', 'double', 'triple', 'home_run')) / pa,
            'walk_rate': event_counts['walk'] / pa, 'home_run_rate': event_counts['home_run'] / pa,
            'assumed_actions_attempted': None, 'empirical_actions_attempted': None, 'failures': {}})
        for value, n in sorted(Counter(observed_runs).items()):
            distributions.append({'population': f'observed_complete_regular_{year}', 'runs': value, 'n': n, 'completed_halves': len(observed_runs)})
    # Exact score-only Markov expectation; no anonymous runner-to-player assignment.
    q = np.zeros((24, 24)); reward = np.zeros(24)
    for pre in range(24):
        table = kernels['state_baseline'][f'{pre}:0']
        for (post, runs), probability in zip(table['targets'], table['p']):
            reward[pre] += probability * runs
            if post != 24:
                q[pre, post] += probability
    expected = np.linalg.solve(np.eye(24) - q, reward)
    csv_file(output / 'state_baseline_run_expectancy.csv', [{'pre_state': i, 'runs_until_third_out': float(value)} for i, value in enumerate(expected)])
    write_json(output / 'simulation.json', {'seed': config['seed'], 'summaries': summaries,
        'limits': ['fictional roster has no real-player IDs or hand information; common league fallback is used',
                   'all trials start regulation half 1 with bases empty, no walkoff; NOT a complete baseball game',
                   'failures are not resampled; completed-only summaries may have selection bias',
                   'score-only state model has no identifiable hits/walks/HR, shown as null',
                   'observed halves contain actual player/hand/tactical mixtures and are not the same population'],
        'state_baseline_expected_runs_from_empty': float(expected[0])})
    csv_file(output / 'simulation_distribution.csv', distributions)
    csv_file(output / 'simulation_movements.csv', movement_rows, ['population', 'movement', 'n'])
    csv_file(output / 'simulation_summary.csv', [{**r, 'failures': json.dumps(r['failures'], sort_keys=True)} for r in summaries])
    return summaries
