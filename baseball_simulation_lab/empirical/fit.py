"""Small multinomial shrinkage tables. Numpy is used offline, not by the API."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json

import numpy as np

from .common import OUTCOMES, canonical, feature_keys, legal_targets, outcome_mask


@dataclass
class Batch:
    season: np.ndarray
    target: np.ndarray
    pre: np.ndarray
    post: np.ndarray
    runs: np.ndarray
    extra: np.ndarray
    transition_valid: np.ndarray
    games: list
    keys: dict

    def subset(self, mask):
        indices = np.flatnonzero(mask)
        return Batch(*(a[mask] for a in (self.season, self.target, self.pre, self.post, self.runs, self.extra, self.transition_valid)),
                     [self.games[i] for i in indices], {k: [v[i] for i in indices] for k, v in self.keys.items()})


def load_batch(db):
    rows = db.execute('''SELECT season,outcome,pre_state,post_state,runs,extra_innings,transition_observed,
       game_id,inning,half,batter,pitcher,batter_hand,pitcher_hand,score_diff
       FROM windows WHERE completed_pa=1 OR post_state=24 ORDER BY game_id,first_pn''')
    columns = [[] for _ in range(7)]
    games = []
    keys = {k: [] for k in ('hands', 'context', 'batter', 'pitcher')}
    for row in rows:
        for i, value in enumerate((row[0], OUTCOMES.index(row[1]), *row[2:7])):
            columns[i].append(value)
        games.append(row[7])
        outs, bases = divmod(row[2], 8)
        features = feature_keys(outs=outs, bases=bases, inning=row[8], half=row[9], batter_id=row[10],
                                pitcher_id=row[11], batter_hand=row[12], pitcher_hand=row[13], batting_score_diff=row[14])
        for name in keys:
            keys[name].append(features[name])
    return Batch(*(np.array(c, dtype=np.int32) for c in columns), games, keys)


def count_tables(batch):
    if not set(batch.season.tolist()) <= {2023, 2024}:
        raise ValueError('Fit input contains evaluation seasons')
    result = {'league': np.bincount(batch.target, minlength=len(OUTCOMES))}
    for name, keys in batch.keys.items():
        counts = defaultdict(lambda: np.zeros(len(OUTCOMES), dtype=np.int64))
        for key, label in zip(keys, batch.target):
            counts[key][label] += 1
        result[name] = dict(sorted(counts.items()))
    return result


def fit_tables(counts, *, context_alpha, player_weight, training_seasons):
    settings = {'context_alpha': context_alpha, 'hands_alpha': 100, 'player_alpha': 500,
                'league_pseudocount_per_class': 0.5, 'player_weight': player_weight}
    league_counts = counts['league']
    league = (league_counts + 0.5) / (sum(league_counts) + len(OUTCOMES) * 0.5)
    tables = {'league': {'n': int(sum(league_counts)), 'counts': league_counts.tolist(), 'p': league.tolist()}}
    for name in ('hands', 'context', 'batter', 'pitcher'):
        tables[name] = {}
        alpha = context_alpha if name == 'context' else settings['hands_alpha'] if name == 'hands' else settings['player_alpha']
        for key, values in counts[name].items():
            if name == 'context':
                cells = json.loads(key)
                parent = np.asarray(tables['hands'][canonical(cells[2:4])]['p'])
            else:
                parent = league
            n = int(sum(values))
            p = (values + alpha * parent) / (n + alpha)
            tables[name][key] = {'n': n, 'counts': values.tolist(), 'p': p.tolist()}
    return {'schema_version': 1, 'unit': 'observed_PA_window_or_runner_third_out', 'outcomes': list(OUTCOMES),
            'training_seasons': training_seasons, 'settings': settings, 'tables': tables}


def predict(batch, model, variant='selected'):
    tables = model['tables']
    league = np.asarray(tables['league']['p'])
    if variant == 'uniform':
        result = np.full((len(batch.target), len(OUTCOMES)), 1 / len(OUTCOMES))
    elif variant == 'league':
        result = np.tile(league, (len(batch.target), 1))
    else:
        hands = np.array([tables['hands'].get(k, {}).get('p', league) for k in batch.keys['hands']])
        if variant == 'hands':
            result = hands
        else:
            context = np.array([tables['context'].get(k, {}).get('p', hands[i]) for i, k in enumerate(batch.keys['context'])])
            weight = model['settings']['player_weight'] if variant == 'selected' else 0.0
            if weight:
                batter = np.array([tables['batter'].get(k, {}).get('p', league) for k in batch.keys['batter']])
                pitcher = np.array([tables['pitcher'].get(k, {}).get('p', league) for k in batch.keys['pitcher']])
                result = (1 - weight) * context + weight * (batter + pitcher) / 2
            else:
                result = context
    masks = np.asarray([outcome_mask(pre) for pre in range(24)])[batch.pre]
    result *= masks
    result /= result.sum(axis=1, keepdims=True)
    if (result[np.arange(len(batch.target)), batch.target] <= 0).any():
        raise ValueError('Observed outcome excluded by pre-state support')
    return result


def score(y, p):
    truth = p[np.arange(len(y)), y]
    if not np.isfinite(p).all() or np.any(truth <= 0) or not np.allclose(p.sum(axis=1), 1, atol=1e-10):
        raise ValueError('Invalid scored probabilities; no silent probability clipping')
    ll = -np.log(truth)
    brier = (p * p).sum(axis=1) - 2 * truth + 1
    return ll, brier


def pa_prediction(batch, p):
    keep = batch.target < len(OUTCOMES) - 1
    result = p[keep, :-1].copy()
    result /= result.sum(axis=1, keepdims=True)
    return keep, batch.target[keep], result


def fit_kernels(batch, alpha):
    if not set(batch.season.tolist()) <= {2023, 2024}:
        raise ValueError('Transition fit input contains evaluation seasons')
    counts = defaultdict(lambda: defaultdict(int))
    marginal = defaultdict(lambda: defaultdict(int))
    for pre, outcome, post, runs, extra, valid in zip(batch.pre, batch.target, batch.post, batch.runs, batch.extra, batch.transition_valid):
        if not valid:
            continue
        pair = (int(post), int(runs))
        if pair not in legal_targets(int(pre), OUTCOMES[outcome]):
            raise ValueError('Unresolved transition-support exception')
        counts[int(pre), int(outcome), int(extra)][pair] += 1
        marginal[int(pre), int(extra)][pair] += 1
    result = {'schema_version': 1, 'alpha': alpha, 'uniform_legal_prior_total': 0.5,
              'support': 'coarse count conservation; empirical counts plus explicit prior, not full event-rule enforcement',
              'conditional': {}, 'state_baseline': {}}
    for pre in range(24):
        all_targets = sorted(set(pair for label in OUTCOMES for pair in legal_targets(pre, label)))
        for extra in (0, 1):
            mc = marginal[pre, extra]
            p = [(mc[pair] + 0.5 / len(all_targets)) / (sum(mc.values()) + 0.5) for pair in all_targets]
            result['state_baseline'][f'{pre}:{extra}'] = {'n': sum(mc.values()), 'targets': all_targets, 'p': p}
            for index, outcome in enumerate(OUTCOMES):
                targets = legal_targets(pre, outcome)
                if not targets:
                    continue
                total = {pair: counts[pre, index, 0][pair] + counts[pre, index, 1][pair] for pair in targets}
                pooled_n = sum(total.values())
                pooled = [(total[pair] + 0.5 / len(targets)) / (pooled_n + 0.5) for pair in targets]
                local = counts[pre, index, extra]
                n = sum(local.values())
                p = [(local[pair] + alpha * parent) / (n + alpha) for pair, parent in zip(targets, pooled)]
                result['conditional'][f'{pre}:{outcome}:{extra}'] = {
                    'n': n, 'pooled_n': pooled_n, 'targets': targets, 'counts': [local[t] for t in targets], 'p': p}
    return result


def transition_scores(batch, p_outcomes, kernels):
    """Predict without using the realized outcome: marginalize the 15 outcomes."""
    result = {name: [np.full(len(batch.target), np.nan), np.full(len(batch.target), np.nan)]
              for name in ('joint', 'state', 'runs', 'baseline_joint', 'baseline_state', 'baseline_runs')}
    selected_indices = np.flatnonzero(batch.transition_valid)
    for pre in range(24):
        for extra in (0, 1):
            indices = selected_indices[(batch.pre[selected_indices] == pre) & (batch.extra[selected_indices] == extra)]
            if not len(indices):
                continue
            matrix = np.zeros((len(OUTCOMES), 125))
            for col, outcome in enumerate(OUTCOMES):
                table = kernels['conditional'].get(f'{pre}:{outcome}:{extra}')
                if table:
                    for (post, runs), probability in zip(table['targets'], table['p']):
                        matrix[col, post * 5 + runs] = probability
            joint = p_outcomes[indices] @ matrix
            base = kernels['state_baseline'][f'{pre}:{extra}']
            base_vector = np.zeros(125)
            for (post, runs), probability in zip(base['targets'], base['p']):
                base_vector[post * 5 + runs] = probability
            for prefix, probabilities in [('', joint), ('baseline_', np.tile(base_vector, (len(indices), 1)))]:
                state_p = probabilities.reshape(-1, 25, 5).sum(axis=2)
                runs_p = probabilities.reshape(-1, 25, 5).sum(axis=1)
                for name, y, pred in [('joint', batch.post[indices] * 5 + batch.runs[indices], probabilities),
                                      ('state', batch.post[indices], state_p), ('runs', batch.runs[indices], runs_p)]:
                    ll, brier = score(y, pred)
                    result[prefix + name][0][indices] = ll
                    result[prefix + name][1][indices] = brier
    return result


def calibration(y, p, model, split, bins=10):
    rows = []
    eces = []
    for col, label in enumerate(OUTCOMES[:p.shape[1]]):
        assignments = np.minimum((p[:, col] * bins).astype(int), bins - 1)
        ece = 0.0
        for bucket in range(bins):
            keep = assignments == bucket
            n = int(keep.sum())
            if n:
                mean = float(p[keep, col].mean())
                observed = float((y[keep] == col).mean())
                ece += n * abs(mean - observed) / len(y)
                rows.append({'model': model, 'split': split, 'class': label, 'bin': bucket,
                             'n': n, 'mean_probability': mean, 'observed_frequency': observed})
        eces.append(ece)
    top = p.argmax(axis=1)
    confidence = p.max(axis=1)
    assignments = np.minimum((confidence * bins).astype(int), bins - 1)
    top_ece = 0.0
    for bucket in range(bins):
        keep = assignments == bucket
        if keep.any():
            top_ece += keep.sum() * abs(float(confidence[keep].mean()) - float((top[keep] == y[keep]).mean())) / len(y)
    return rows, {'macro_class_ece': float(np.mean(eces)), 'top_label_ece': float(top_ece)}


def bootstrap_difference(games, selected, baseline, seed=626, repetitions=1000):
    _, indices = np.unique(games, return_inverse=True)
    n_games = int(indices.max()) + 1
    sums = np.bincount(indices, weights=selected - baseline)
    sizes = np.bincount(indices)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(repetitions):
        sampled = rng.integers(0, n_games, n_games)
        means.append(float(sums[sampled].sum() / sizes[sampled].sum()))
    return {'difference_selected_minus_baseline': float(np.mean(selected - baseline)),
            'percentile_95_interval': np.quantile(means, [0.025, 0.975]).tolist(),
            'unit': 'resampled whole games, weighted by observations', 'games': n_games,
            'repetitions': repetitions, 'seed': seed}
