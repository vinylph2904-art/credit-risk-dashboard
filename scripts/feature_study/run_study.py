"""Source ablation, fold-local selection and frozen historical-test evaluation."""
# %% 18.1 Fixed design: write before reading any new evaluation labels.
from pathlib import Path
import gc
import hashlib
import json
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from connectors.Connector import Connector
from models.HomeCreditModelData import HomeCreditModelData
from models.HomeCreditTraining import HomeCreditTraining
from models.CreditRiskModel import CreditRiskModel

REPORTS = ROOT / 'reports/modeling/feature_study_20261026'
WORK = ROOT / 'tmp/feature_study_20261026'
REPORTS.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)
started = time.perf_counter()
active_bytes = (ROOT / 'artifacts/inference_metadata.json').read_bytes()
active = json.loads(active_bytes)
design = json.loads((ROOT / 'reports/modeling/boosting_comparison/experiment_plan.json').read_text(encoding='utf-8'))
schemas = json.loads((ROOT / 'configs/preprocessing_schema.json').read_text(encoding='utf-8'))['schemas']
case = design['cases']['B_CAT_02']
plan = design['plan']
all_columns = schemas['B']['feature_order']
flags = [column for column in all_columns if column.startswith('HAS_USABLE_')]
source_specs = {
    'bureau': ('BUR_', 'HAS_USABLE_BUREAU'),
    'bureau_balance': ('BB_', 'HAS_USABLE_BUREAU_BALANCE'),
    'previous': ('PREV_', 'HAS_USABLE_PREVIOUS'),
    'pos': ('POS_', 'HAS_USABLE_POS'),
    'card': ('CC_', 'HAS_USABLE_CARD'),
    'installments': ('INS_', 'HAS_USABLE_INSTALLMENTS'),
}
source_columns = {name: [column for column in all_columns if column.startswith(prefix) or column == flag]
                  for name, (prefix, flag) in source_specs.items()}
history_columns = [column for column in all_columns if column not in schemas['A']['feature_order'] and column not in flags]
assert len(all_columns) == 199 and len(history_columns) == 66 and len(flags) == 6
assert set(sum(source_columns.values(), [])) == set(history_columns + flags)
variants = {'full_B': all_columns}
for name, columns in source_columns.items():
    variants['without_' + name] = [column for column in all_columns if column not in columns]
variants['without_flags'] = [column for column in all_columns if column not in flags]
variants['without_history_keep_flags'] = [column for column in all_columns if column not in history_columns]
variants['application_A'] = schemas['A']['feature_order']

protocol = {
    'version': 'source-ablation-fold-selection-v1', 'declared_date': '2026-10-26',
    'scope': 'post-historical-test extension, not a prospectively untouched evaluation',
    'model': case, 'training_plan': plan, 'variants': variants,
    'source_groups': source_columns, 'selection_k': 150,
    'selection_method': 'PredictionValuesChange from full model fitted only on outer-fit rows; select top150, refit subset on same outer-fit rows; probe never used for selection',
    'folds': 'same three frozen train folds; no early stopping; no hyperparameter search',
    'calibration': 'retain raw CatBoost to isolate feature-policy effects; no new calibration tuning',
    'cv_gate': {'minimum_mean_ap_gain': .001, 'minimum_nonnegative_folds': 2,
                'maximum_single_fold_ap_loss': .003, 'maximum_mean_brier_increase': .0005},
    'cv_tie_break': 'mean AP descending, feature count ascending, Brier ascending, variant ID',
    'validation_gate': 'candidate cost5:1 strictly below active; AP>=active-.001; Brier<=active+.0005; alert_rate<=active+.02',
    'threshold': 'validation only: min5FN+FP, ties recall desc then threshold desc',
    'demo_adequacy': 'validation AP>positive prevalence; ROC>.5; cost5:1 below always-negative and below frozen LR; these are study benchmarks, not a bank acceptance rule',
    'maximum_new_cv_fits': 30, 'maximum_new_final_fits': 1,
    'active_model_version': active['model_version'],
    'active_metadata_sha256': hashlib.sha256(active_bytes).hexdigest(),
    'deployment': 'offline candidate study only; active application artifact/metadata not replaced',
    'test_policy': 'read test features/labels only after saved final decision; score frozen finalist once; no model/threshold revision from test results',
}
protocol_path = REPORTS / 'protocol.json'
if protocol_path.exists():
    saved_protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    if saved_protocol['active_metadata_sha256'] != protocol['active_metadata_sha256']:
        migration = json.loads((REPORTS / 'path_migration_20261027.json').read_text(encoding='utf-8'))
        assert saved_protocol['active_metadata_sha256'] == migration['metadata_before_sha256']
        assert protocol['active_metadata_sha256'] == migration['metadata_after_sha256']
        assert hashlib.sha256((ROOT / active['model_path']).read_bytes()).hexdigest() == migration['model_sha256']
        # Chỉ chấp nhận đúng migration đã đối soát; giữ identity của cache lịch sử.
        protocol['active_metadata_sha256'] = saved_protocol['active_metadata_sha256']
    assert saved_protocol == protocol
else:
    protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def progress(stage, **details):
    value = {'stage': stage, 'elapsed_seconds': round(time.perf_counter() - started, 2), **details}
    write_json(WORK / 'progress.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)

progress('read_train', maximum_new_cv_fits=30)

# %% 18.2 Train data and identity; no validation or test labels here.
connector = Connector()
connector.connect()
try:
    reader = HomeCreditModelData(connector, pq.ParquetFile(ROOT / 'data/features/b/train.parquet').schema_arrow)
    X_raw = reader.readFeatures('train')
    y = reader.readLabels('train')
    split = reader.readSplitIndex().set_index('SK_ID_CURR')
finally:
    connector.disConnect()
folds = split.loc[X_raw.index, 'cv_fold'].astype('int8')
assert X_raw.index.equals(y.index) and len(X_raw) == 184506
assert not {'TARGET', 'SK_ID_CURR', 'split', 'cv_fold'} & set(all_columns)
base_key = HomeCreditTraining.makeCacheKey(X_raw, y, folds, plan, schemas, 'boosting-v1', rf_jobs=4)
assert base_key == design['cache_id']
study_key = HomeCreditTraining.makeCacheKey(X_raw, y, folds, protocol, schemas, protocol['version'], rf_jobs=4)
cache = ROOT / 'tmp/phase4_checkpoints/feature-study-v1' / study_key
training = HomeCreditTraining(plan, schemas, cache, study_key)
original = HomeCreditTraining(plan, schemas, ROOT / 'tmp/phase4_checkpoints/boosting-v1' / base_key, base_key)
X = training.prepareBoostingData(X_raw, schemas['B'], 'CAT')
del X_raw
reader.train = None
gc.collect()

def checkpoint_case(name, columns):
    return {'variant': name, 'columns': columns, 'base_case': case}

def fit_fold(name, columns, fold, selector=False):
    fit = folds != fold
    probe = folds == fold
    ids = X.index[probe]
    folder = cache / name.lower()
    folder.mkdir(exist_ok=True)
    path = folder / f'fold_{fold}.npz'
    cache_case = checkpoint_case(name, columns)
    cached = training.loadCheckpoint(path, ids, y.loc[ids], cache_case)
    model_path = folder / f'fold_{fold}.joblib'
    if cached is not None and (not selector or model_path.exists()):
        return cached
    progress('fit', variant=name, fold=fold, features=len(columns), cache_id=study_key)
    model = training.createBoostingModel(case, columns)
    tick = time.perf_counter()
    model.fit(X.loc[fit, columns], y.loc[fit])
    fit_s = time.perf_counter() - tick
    tick = time.perf_counter()
    score = model.predict_proba(X.loc[probe, columns])[:, 1]
    predict_s = time.perf_counter() - tick
    record = {'variant': name, 'fold': fold, 'features_n': len(columns),
              'fit_n': int(fit.sum()), 'probe_n': int(probe.sum()),
              'ap': average_precision_score(y.loc[probe], score),
              'roc_auc': roc_auc_score(y.loc[probe], score),
              'brier': brier_score_loss(y.loc[probe], score),
              'fit_s': fit_s, 'predict_s': predict_s, 'reused_historical_fit': False}
    if selector:
        importance = pd.DataFrame({'feature': columns,
            'importance': model.get_feature_importance(type='PredictionValuesChange')})
        importance = importance.sort_values(['importance', 'feature'], ascending=[False, True], kind='stable')
        importance.to_csv(folder / f'importance_fold_{fold}.csv', index=False)
        joblib.dump(model, model_path)
        old_score, _ = original.loadCheckpoint(original.cache_dir / 'b_cat_02' / f'fold_{fold}.npz', ids, y.loc[ids], case)
        np.testing.assert_allclose(score, old_score, atol=1e-12, rtol=0)
        record['matches_original_full_oof'] = True
    training.saveCheckpoint(path, ids, y.loc[ids], score, record, cache_case)
    progress('fold_complete', **record)
    del model
    gc.collect()
    return score, record

# %% 18.3 Paired source ablation and fit-only feature selection.
records = []
selected_by_fold = {}
for fold in [0, 1, 2]:
    _, record = fit_fold('full_B', all_columns, fold, selector=True)
    records.append(record)
    ranks = pd.read_csv(cache / 'full_b' / f'importance_fold_{fold}.csv')
    selected = set(ranks['feature'].head(protocol['selection_k']))
    selected_columns = [column for column in all_columns if column in selected]
    selected_by_fold[str(fold)] = selected_columns
    _, record = fit_fold('selected_top150', selected_columns, fold)
    records.append(record)
    for name, columns in variants.items():
        if name == 'full_B':
            continue
        if name == 'application_A':
            ids = X.index[folds == fold]
            old_case = design['cases']['A_CAT_02']
            _, old_record = original.loadCheckpoint(original.cache_dir / 'a_cat_02' / f'fold_{fold}.npz', ids, y.loc[ids], old_case)
            record = {'variant': name, 'fold': fold, 'features_n': len(columns),
                **{key: old_record[key] for key in ['fit_n', 'probe_n', 'ap', 'roc_auc', 'brier', 'fit_s', 'predict_s']},
                'reused_historical_fit': True}
        else:
            _, record = fit_fold(name, columns, fold)
        records.append(record)
    pd.DataFrame(records).to_csv(REPORTS / 'cv_folds.csv', index=False)
    write_json(REPORTS / 'selected_features_by_fold.json', selected_by_fold)

cv = pd.DataFrame(records)
baseline = cv.loc[cv['variant'] == 'full_B'].set_index('fold')
cv['ap_delta'] = [row.ap - baseline.loc[row.fold, 'ap'] for row in cv.itertuples()]
summary = cv.groupby('variant', sort=False).agg(features_n=('features_n', 'first'),
    mean_ap=('ap', 'mean'), std_ap=('ap', 'std'), mean_roc_auc=('roc_auc', 'mean'),
    mean_brier=('brier', 'mean'), mean_fit_s=('fit_s', 'mean'), mean_predict_s=('predict_s', 'mean'),
    mean_ap_delta=('ap_delta', 'mean'), minimum_fold_delta=('ap_delta', 'min'),
    nonnegative_folds=('ap_delta', lambda value: int((value >= 0).sum()))).reset_index()
full = summary.loc[summary['variant'] == 'full_B'].iloc[0]
gate = protocol['cv_gate']
summary['cv_eligible'] = ((summary['mean_ap_delta'] >= gate['minimum_mean_ap_gain']) &
    (summary['nonnegative_folds'] >= gate['minimum_nonnegative_folds']) &
    (summary['minimum_fold_delta'] >= -gate['maximum_single_fold_ap_loss']) &
    (summary['mean_brier'] <= full['mean_brier'] + gate['maximum_mean_brier_increase']))
eligible = summary.loc[summary['cv_eligible']].sort_values(
    ['mean_ap', 'features_n', 'mean_brier', 'variant'], ascending=[False, True, True, True])
candidate_name = eligible.iloc[0]['variant'] if len(eligible) else 'full_B'
summary.to_csv(REPORTS / 'cv_summary.csv', index=False)
write_json(REPORTS / 'cv_decision.json', {'candidate': candidate_name, 'cv_gate': gate,
    'test_labels_read': False, 'cache_id': study_key, 'validation_labels_read_during_selection': False})
progress('cv_complete', candidate=candidate_name)
print(summary.to_string(index=False), flush=True)

# %% 18.4 Freeze a candidate, then apply the predeclared validation gate.
active_model = CreditRiskModel(ROOT).loadModel()
if candidate_name == 'selected_top150':
    rank = pd.DataFrame({'feature': all_columns,
        'importance': active_model.model.get_feature_importance(type='PredictionValuesChange')})
    rank = rank.sort_values(['importance', 'feature'], ascending=[False, True], kind='stable')
    chosen_set = set(rank['feature'].head(protocol['selection_k']))
    candidate_columns = [column for column in all_columns if column in chosen_set]
else:
    candidate_columns = variants[candidate_name]
candidate_path = cache / 'final_candidate.joblib'
if candidate_name == 'full_B':
    candidate_model = active_model.model
elif candidate_path.exists():
    candidate_model = joblib.load(candidate_path)
    assert list(candidate_model.feature_names_) == candidate_columns
else:
    progress('fit_final_candidate', variant=candidate_name, features=len(candidate_columns))
    candidate_model = training.createBoostingModel(case, candidate_columns)
    candidate_model.fit(X.loc[:, candidate_columns], y)
    joblib.dump(candidate_model, candidate_path)
write_json(REPORTS / 'candidate_features.json', candidate_columns)
train_ids = X.index.copy()
train_prevalence = float(y.mean())
del X
gc.collect()
connector.connect()
try:
    validation = reader.readFeatures('validation')
    validation_y = reader.readLabels('validation')
finally:
    connector.disConnect()
assert validation.index.equals(validation_y.index) and not validation.index.isin(train_ids).any()
prepared = active_model.prepareInput(validation)
base_scores = active_model.predict(prepared)['score'].to_numpy()
candidate_scores = candidate_model.predict_proba(prepared.loc[:, candidate_columns])[:, 1]
_, sensitivity = training.thresholdEvaluation(validation_y, candidate_scores)
candidate_threshold = float(sensitivity.loc[sensitivity['fn_cost'] == 5, 'threshold'].iloc[0])
base_metrics = training.policyMetrics(validation_y, base_scores, active['main_threshold'], 'validation', 'active_full_B')
candidate_metrics = training.policyMetrics(validation_y, candidate_scores, candidate_threshold, 'validation', candidate_name)
validation_gate = bool(candidate_name != 'full_B' and
    candidate_metrics['cost_5_to_1'] < base_metrics['cost_5_to_1'] and
    candidate_metrics['ap'] >= base_metrics['ap'] - .001 and
    candidate_metrics['brier'] <= base_metrics['brier'] + .0005 and
    candidate_metrics['alert_rate'] <= base_metrics['alert_rate'] + .02)
final_name = candidate_name if validation_gate else 'full_B'
final_columns = candidate_columns if validation_gate else all_columns
final_model = candidate_model if validation_gate else active_model.model
final_threshold = candidate_threshold if validation_gate else active['main_threshold']
pd.DataFrame([base_metrics, candidate_metrics]).to_csv(REPORTS / 'validation_comparison.csv', index=False)
pd.DataFrame({'SK_ID_CURR': validation.index, 'TARGET': validation_y.to_numpy(),
    'active_score': base_scores, 'candidate_score': candidate_scores}).to_parquet(REPORTS / 'validation_predictions.parquet', index=False)
final_validation = candidate_metrics if validation_gate else base_metrics
negative_cost = 5 * float(validation_y.mean())
lr_validation = pd.read_csv(ROOT / 'reports/modeling/catboost_finalization/validation_comparison.csv')
lr_cost = float(lr_validation.loc[lr_validation['policy'] == 'LR_frozen', 'cost_5_to_1'].iloc[0])
adequacy = {'scope': 'relative demo benchmark; not proof of bank readiness',
    'ap_above_prevalence': bool(final_validation['ap'] > validation_y.mean()),
    'roc_above_random': bool(final_validation['roc_auc'] > .5),
    'cost_below_always_negative': bool(final_validation['cost_5_to_1'] < negative_cost),
    'cost_below_frozen_LR': bool(final_validation['cost_5_to_1'] < lr_cost),
    'always_negative_cost': negative_cost, 'frozen_LR_cost': lr_cost,
    'remaining_FN_share': 1 - final_validation['recall'],
    'next_preprocessing_if_failed': 'inspect source coverage, missing/sentinel rules, timing and feature groups on train; declare a new study before additional fits; never retune on historical test'}
adequacy['passes_declared_demo_benchmarks'] = all(adequacy[key] for key in [
    'ap_above_prevalence', 'roc_above_random', 'cost_below_always_negative', 'cost_below_frozen_LR'])
write_json(REPORTS / 'adequacy.json', adequacy)
freeze = {'final_variant': final_name, 'cv_candidate': candidate_name, 'validation_gate_passed': validation_gate,
    'feature_order': final_columns, 'threshold': final_threshold, 'calibration': 'raw',
    'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'test_labels_read_before_freeze': False,
    'active_artifact_changed': False, 'cache_id': study_key,
    'final_model_path': active['model_path'] if final_name == 'full_B' else str(candidate_path.relative_to(ROOT)).replace('\\', '/')}
freeze_path = REPORTS / 'final_decision_before_test.json'
if freeze_path.exists():
    old_freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    assert {k: v for k, v in old_freeze.items() if k != 'frozen_at_utc'} == {k: v for k, v in freeze.items() if k != 'frozen_at_utc'}
else:
    write_json(freeze_path, freeze)
freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
progress('final_frozen_before_test', final_variant=final_name, threshold=final_threshold)
del validation, prepared, candidate_scores, base_scores, candidate_model
gc.collect()

# %% 18.5 Historical internal test: descriptive evaluation after the freeze.
test_path = REPORTS / 'historical_test_predictions.parquet'
if test_path.exists():
    test_predictions = pd.read_parquet(test_path)
    recorded_sha = json.loads((REPORTS / 'test_execution.json').read_text())['decision_sha256']
    if recorded_sha != freeze_sha:
        migration = json.loads((REPORTS / 'path_migration_20261027.json').read_text(encoding='utf-8'))
        assert recorded_sha == migration['decision_before_sha256']
        assert freeze_sha == migration['decision_after_sha256']
else:
    connector.connect()
    try:
        test_data = reader.readFeatures('test')
        test_target = reader.readLabels('test')
    finally:
        connector.disConnect()
    assert test_data.index.equals(test_target.index)
    assert not test_data.index.isin(train_ids).any() and not test_data.index.isin(validation_y.index).any()
    test_prepared = active_model.prepareInput(test_data).loc[:, final_columns]
    test_scores = final_model.predict_proba(test_prepared)[:, 1]
    test_predictions = pd.DataFrame({'SK_ID_CURR': test_data.index,
        'TARGET': test_target.to_numpy(), 'score': test_scores})
    test_predictions.to_parquet(test_path, index=False)
    write_json(REPORTS / 'test_execution.json', {'decision_sha256': freeze_sha,
        'status': 'scored_frozen_finalist', 'n': len(test_predictions),
        'model_selection_after_test': False, 'threshold_selection_after_test': False,
        'scope': 'historical internal test; previously observed for LR, not a new independent holdout'})
    del test_data, test_target, test_prepared
test_metrics = training.policyMetrics(test_predictions['TARGET'], test_predictions['score'],
    final_threshold, 'historical_internal_test', final_name)
pd.DataFrame([test_metrics]).to_csv(REPORTS / 'historical_test_metrics.csv', index=False)
capacity = []
for fraction in [.05, .10, .20]:
    row = training.capacityMetrics(test_predictions['SK_ID_CURR'], test_predictions['TARGET'],
        test_predictions['score'], 'historical_internal_test', fraction)
    capacity.append({'fraction': fraction, **row})
pd.DataFrame(capacity).to_csv(REPORTS / 'historical_test_capacity.csv', index=False)
assert (ROOT / 'artifacts/inference_metadata.json').read_bytes() == active_bytes
progress('complete', final_variant=final_name, test_metrics=test_metrics,
    demo_benchmark_passed=adequacy['passes_declared_demo_benchmarks'], active_model_changed=False)

# %% 18.6 Read the paired effects and historical-test trade-offs.
plot = summary.loc[~summary['variant'].isin(['full_B', 'application_A'])].sort_values('mean_ap_delta')
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
axes[0].barh(plot['variant'], plot['mean_ap_delta'], color=['#b63f55' if value < 0 else '#4b718e' for value in plot['mean_ap_delta']])
axes[0].axvline(0, color='#888', linewidth=.8)
axes[0].set_xlabel('Mean paired CV AP change versus full B')
axes[0].set_title('Fixed CatBoost; same train folds')
axes[1].bar(['TN', 'FP', 'FN', 'TP'], [test_metrics[key] for key in ['tn', 'fp', 'fn', 'tp']], color=['#aebbc9', '#dca4ae', '#b63f55', '#4b718e'])
axes[1].set_title('Frozen finalist: historical internal test')
axes[1].set_ylabel('Applications')
fig.tight_layout()
fig.savefig(REPORTS / 'feature_study_summary.png', dpi=160)
plt.close(fig)
print('CV summary saved:', REPORTS / 'cv_summary.csv')
print('Historical test:', test_metrics)
