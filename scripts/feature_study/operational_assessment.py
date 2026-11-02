"""Descriptive capacity/decile charts; does not select model or operating thresholds."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve, average_precision_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
from models.HomeCreditTraining import HomeCreditTraining

OUT = ROOT / 'reports/modeling/operational_assessment_20261026'
OUT.mkdir(exist_ok=True)
active = json.loads((ROOT / 'artifacts/inference_metadata.json').read_text(encoding='utf-8'))
source = ROOT / active['evaluation']['folder'] / active['evaluation']['predictions']
validation = pd.read_parquet(source)
datasets = [('active_validation', validation, active['main_threshold'])]
study = ROOT / 'reports/modeling/feature_study_20261026'
if (study / 'test_execution.json').exists():
    decision = json.loads((study / 'final_decision_before_test.json').read_text(encoding='utf-8'))
    datasets.append(('frozen_finalist_historical_test', pd.read_parquet(study / 'historical_test_predictions.parquet'), decision['threshold']))

capacity_rows, decile_rows, metrics_rows = [], [], []
fig, axes = plt.subplots(len(datasets), 3, figsize=(16, 4.5 * len(datasets)), squeeze=False)
for panel, (name, data, threshold) in enumerate(datasets):
    assert data['SK_ID_CURR'].is_unique and data['TARGET'].isin([0, 1]).all()
    assert np.isfinite(data['score']).all() and data['score'].between(0, 1).all()
    rank = data.sort_values(['score', 'SK_ID_CURR'], ascending=[False, True], kind='stable').reset_index(drop=True)
    n, positives = len(rank), int(rank['TARGET'].sum())
    rate = positives / n
    metrics = HomeCreditTraining.policyMetrics(data['TARGET'], data['score'], threshold, name, 'fixed_frozen_threshold')
    metrics.update({'false_discovery_rate': metrics['fp'] / (metrics['tp'] + metrics['fp']),
        'false_positive_rate': metrics['fp'] / (metrics['fp'] + metrics['tn']),
        'false_negative_rate': metrics['fn'] / (metrics['tp'] + metrics['fn']),
        'below_threshold_positive_rate': metrics['fn'] / (metrics['tn'] + metrics['fn']),
        'above_threshold_lift': metrics['precision'] / rate, 'prevalence': rate})
    metrics_rows.append(metrics)
    for fraction in [.01, .05, .10, .20]:
        row = HomeCreditTraining.capacityMetrics(data['SK_ID_CURR'], data['TARGET'], data['score'], name, fraction)
        capacity_rows.append({'dataset': name, 'fraction': fraction, 'review_n': row['review_n'],
            'captured_positive_n': row['captured_positive_n'],
            'false_alerts_n': row['review_n'] - row['captured_positive_n'],
            'missed_positive_n': positives - row['captured_positive_n'],
            'precision': row['precision'], 'recall': row['recall'], 'lift': row['lift'],
            'random_expected_positive_n': row['review_n'] * rate})
    edges = [int(np.ceil(fraction * n / 10)) for fraction in range(11)]
    for decile in range(10):
        group = rank.iloc[edges[decile]:edges[decile + 1]]
        captured = int(group['TARGET'].sum())
        cumulative = int(rank.iloc[:edges[decile + 1]]['TARGET'].sum())
        decile_rows.append({'dataset': name, 'decile': decile + 1, 'n': len(group),
            'positive_n': captured, 'positive_rate': captured / len(group),
            'lift': captured / len(group) / rate,
            'cumulative_review_n': edges[decile + 1], 'cumulative_captured_n': cumulative,
            'cumulative_recall': cumulative / positives,
            'min_score': float(group['score'].min()), 'max_score': float(group['score'].max()),
            'mean_score': float(group['score'].mean())})
    assert sum(row['n'] for row in decile_rows if row['dataset'] == name) == n
    assert sum(row['positive_n'] for row in decile_rows if row['dataset'] == name) == positives
    precision, recall, _ = precision_recall_curve(data['TARGET'], data['score'])
    axes[panel, 0].plot(recall, precision, color='#52677f', label=f'AP={average_precision_score(data.TARGET, data.score):.3f}')
    axes[panel, 0].axhline(rate, color='#999', linestyle='--', label=f'Prevalence={rate:.1%}')
    axes[panel, 0].scatter([metrics['recall']], [metrics['precision']], color='#b63f55', zorder=3)
    axes[panel, 0].set(xlabel='Recall', ylabel='Precision', title=f'{name}: Precision-Recall', xlim=(0, 1), ylim=(0, 1))
    axes[panel, 0].legend(fontsize=8)
    cumulative = np.cumsum(rank['TARGET'].to_numpy()) / positives
    fraction = np.arange(1, n + 1) / n
    axes[panel, 1].plot(fraction, cumulative, color='#52677f', label='Frozen scores')
    axes[panel, 1].plot([0, 1], [0, 1], color='#999', linestyle='--', label='Random order')
    axes[panel, 1].set(xlabel='Fraction reviewed', ylabel='Fraction of TARGET=1 captured', title='Cumulative gains', xlim=(0, 1), ylim=(0, 1))
    axes[panel, 1].legend(fontsize=8)
    rows = [row for row in decile_rows if row['dataset'] == name]
    axes[panel, 2].bar([row['decile'] for row in rows], [row['positive_rate'] for row in rows], color='#52677f')
    axes[panel, 2].axhline(rate, color='#999', linestyle='--')
    axes[panel, 2].set(xlabel='Decile (1 = highest score)', ylabel='Observed TARGET=1 share', title='Observed deciles, no automatic lending actions', xticks=range(1, 11))

fig.tight_layout()
fig.savefig(OUT / 'pr_gains_deciles.png', dpi=160)
plt.close(fig)
pd.DataFrame(capacity_rows).to_csv(OUT / 'capacity.csv', index=False)
pd.DataFrame(decile_rows).to_csv(OUT / 'deciles.csv', index=False)
pd.DataFrame(metrics_rows).to_csv(OUT / 'fixed_threshold_metrics.csv', index=False)
(OUT / 'verification.json').write_text(json.dumps({'status': 'passed', 'decile_counts_reconcile': True,
    'tie_break': 'score descending, SK_ID_CURR ascending', 'model_or_threshold_changed': False,
    'datasets': [item[0] for item in datasets], 'validation_is_not_independent_of_threshold_selection': True,
    'historical_test_is_not_a_new_independent_holdout': True}, indent=2), encoding='utf-8')
print(pd.DataFrame(capacity_rows).to_string(index=False))
print(pd.DataFrame(metrics_rows)[['dataset', 'false_discovery_rate', 'false_positive_rate', 'below_threshold_positive_rate']].to_string(index=False))
