"""Các bước huấn luyện và đánh giá dùng lại trong notebook 06–08."""
import gc
import hashlib
from pathlib import Path
import json
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer, MissingIndicator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, roc_auc_score, brier_score_loss,
                             accuracy_score, precision_score, recall_score, f1_score,
                             confusion_matrix)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler, FunctionTransformer
from sklearn.tree import DecisionTreeClassifier


class HomeCreditTraining:
    def __init__(self, plan, schemas, cache_dir, cache_key, rf_jobs=4):
        self.plan = plan
        self.schemas = schemas
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_key = cache_key
        self.rf_jobs = rf_jobs

    def numericPipeline(self, scale, indicators=True, use_log=False):
        steps = [('imputer', SimpleImputer(strategy='median', add_indicator=indicators,
                                           keep_empty_features=True))]
        if use_log:
            steps.append(('log', FunctionTransformer(np.log1p, feature_names_out='one-to-one')))
        steps.append(('float32', FunctionTransformer(np.asarray,
            kw_args={'dtype': np.float32}, feature_names_out='one-to-one')))
        if scale:
            steps.append(('scaler', StandardScaler()))
        return Pipeline(steps)

    def createPreprocessor(self, schema, model_name, variant):
        scale = model_name == 'LR'
        amounts = [column for column in self.plan['log_columns'] if column in schema['numeric']]
        others = [column for column in schema['numeric'] if column not in amounts]
        missing_steps = [
            ('missing', MissingIndicator(features='missing-only', sparse=False, error_on_new=False)),
            ('float32', FunctionTransformer(np.asarray, kw_args={'dtype': np.float32},
                                            feature_names_out='one-to-one'))
        ]
        if scale:
            missing_steps.append(('scaler', StandardScaler()))
        return ColumnTransformer([
            ('amounts', self.numericPipeline(scale, indicators=False,
                                             use_log=variant == 'log_amounts'), amounts),
            ('amount_missing', Pipeline(missing_steps), amounts),
            ('numeric', self.numericPipeline(scale), others),
            ('categorical', OneHotEncoder(handle_unknown='ignore', sparse_output=True,
                                          dtype=np.float32), schema['categorical'])
        ], sparse_threshold=1.0, n_jobs=1)

    def createPipeline(self, case, schema=None):
        name = case['model']
        config = case['config'].copy()
        variant = config.pop('preprocessing', 'standard')
        seed = self.plan['seed']
        settings = self.plan.get(name, {})
        if name == 'Dummy':
            model = DummyClassifier(**config)
        elif name == 'LR':
            model = LogisticRegression(**config, solver=settings['solver'],
                l1_ratio=settings['l1_ratio'], max_iter=settings['max_iter'],
                tol=settings['tol'], random_state=seed)
        elif name == 'DT':
            model = DecisionTreeClassifier(**config,
                min_samples_leaf=settings['min_samples_leaf'],
                criterion=settings['criterion'], random_state=seed)
        elif name == 'RF':
            model = RandomForestClassifier(**config,
                n_estimators=settings['n_estimators'],
                min_samples_leaf=settings['min_samples_leaf'],
                max_features=settings['max_features'], n_jobs=self.rf_jobs,
                criterion=settings['criterion'], random_state=seed)
        else:
            raise ValueError('Mô hình không có trong kế hoạch: ' + name)
        schema = self.schemas[case['set']] if schema is None else schema
        preprocess = self.createPreprocessor(schema, name, variant)
        return Pipeline([('preprocess', preprocess), ('model', model)])

    def createCalibratedModel(self, case):
        if case['model'] == 'CAT':
            base_model = self.createBoostingModel(case)
        else:
            base_model = self.createPipeline(case)
        inner_cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=self.plan['seed'])
        calibrated = CalibratedClassifierCV(
            estimator=base_model, method='sigmoid', cv=inner_cv, ensemble=False, n_jobs=1)
        return calibrated

    def runCrossValidation(self, case_id, case, X, y, folds,
                           feature_columns_by_fold=None, fold_numbers=(0, 1, 2)):
        if not X.index.equals(y.index) or not X.index.equals(folds.index):
            raise ValueError('Feature, label and fold IDs must have the same order.')
        if set(folds.unique()) != {0, 1, 2}:
            raise ValueError('Use the three existing training folds.')
        if not fold_numbers or any(fold not in [0, 1, 2] for fold in fold_numbers):
            raise ValueError('Only folds 0, 1 and 2 may be run.')
        if len(set(fold_numbers)) != len(fold_numbers):
            raise ValueError('A fold may only be run once per call.')
        source_schema = self.schemas[case['set']]
        folder = self.cache_dir / case_id.lower()
        folder.mkdir(exist_ok=True)
        records = []
        for fold in fold_numbers:
            is_fit = folds != fold
            is_probe = folds == fold
            probe_ids = X.index[is_probe]
            probe_y = y.loc[is_probe]
            columns = (source_schema['feature_order'] if feature_columns_by_fold is None
                       else feature_columns_by_fold[str(fold)])
            if len(columns) != len(set(columns)) or not set(columns).issubset(source_schema['feature_order']):
                raise ValueError('Fold feature list must contain unique columns from the source schema.')
            schema = {
                'feature_order': list(columns),
                'numeric': [column for column in source_schema['numeric'] if column in columns],
                'categorical': [column for column in source_schema['categorical'] if column in columns]
            }
            fold_case = case
            if feature_columns_by_fold is not None:
                feature_hash = hashlib.sha256(json.dumps(list(columns)).encode('utf-8')).hexdigest()
                fold_case = {**case, 'selection_fold': fold, 'selected_features_hash': feature_hash}
            fit_X = X.loc[is_fit, columns]
            probe_X = X.loc[is_probe, columns]
            path = folder / f'fold_{fold}.npz'
            checkpoint = self.loadCheckpoint(path, probe_ids, probe_y, fold_case)

            if checkpoint is None:
                estimator = self.createPipeline(case, schema=schema)
                started = time.perf_counter()
                with warnings.catch_warnings(record=True) as events:
                    warnings.simplefilter('always', ConvergenceWarning)
                    estimator.fit(fit_X, y.loc[is_fit])
                fit_s = time.perf_counter() - started
                score = estimator.predict_proba(probe_X)[:, 1]
                score_fit = estimator.predict_proba(fit_X)[:, 1]
                converged = True
                for event in events:
                    if issubclass(event.category, ConvergenceWarning):
                        converged = False
                iterations = getattr(estimator.named_steps['model'], 'n_iter_', [0])
                jobs = 1
                if case['model'] == 'RF':
                    jobs = self.rf_jobs
                record = {
                    'case_id': case_id, 'set': case['set'], 'model': case['model'],
                    'fold': fold, 'config': json.dumps(case['config'], sort_keys=True),
                    'fit_n': int(is_fit.sum()), 'probe_n': int(is_probe.sum()),
                    'features_n': len(columns),
                    'ap': average_precision_score(probe_y, score),
                    'roc_auc': roc_auc_score(probe_y, score),
                    'train_ap': average_precision_score(y.loc[is_fit], score_fit),
                    'brier': brier_score_loss(probe_y, score), 'fit_s': fit_s,
                    'n_jobs_actual': jobs, 'converged': converged,
                    'n_iter': int(np.max(iterations))}
                self.saveCheckpoint(path, probe_ids, probe_y, score, record, fold_case)
                del estimator, score_fit
                gc.collect()
            else:
                score, record = checkpoint
                print(case_id, 'fold', fold, ': dùng checkpoint; fit_s bên dưới là thời gian fit đã lưu')

            records.append(record)
            print(case_id, 'fold', fold, 'AP=', round(record['ap'], 5),
                  'fit_s=', round(record['fit_s'], 1), 'converged=', record['converged'])
        return records

    @staticmethod
    def prepareBoostingData(frame, schema, model_name, category_types=None):
        """Giữ NaN và số 0; chỉ học danh sách category từ phần fit của fold."""
        data = frame.loc[:, schema['feature_order']].copy()
        for column in schema['numeric']:
            data[column] = data[column].astype('float32')
        for column in schema['categorical']:
            values = data[column].astype(object)
            values = values.fillna('__MISSING__')
            data[column] = values.astype(str)
            if model_name == 'XGB':
                if category_types is None:
                    data[column] = data[column].astype('category')
                else:
                    # Category chưa có trong fit được xem là thiếu khi predict.
                    data[column] = data[column].astype(category_types[column])
        return data

    def createBoostingModel(self, case, feature_columns=None):
        """Chỉ import thư viện bổ sung khi thực sự chạy họ mô hình đó."""
        name = case['model']
        settings = self.plan[name].copy()
        settings.update(case['config'])
        if name == 'XGB':
            from xgboost import XGBClassifier
            return XGBClassifier(**settings, random_state=self.plan['seed'],
                                 n_jobs=self.plan['threads'])
        if name == 'CAT':
            from catboost import CatBoostClassifier
            schema = self.schemas[case['set']]
            columns = schema['feature_order'] if feature_columns is None else list(feature_columns)
            if not columns or len(set(columns)) != len(columns) or not set(columns).issubset(schema['feature_order']):
                raise ValueError('Feature subset must be nonempty, unique and belong to the schema.')
            # Tuple giữ tham số bất biến khi sklearn clone model cho calibration.
            return CatBoostClassifier(**settings, random_seed=self.plan['seed'],
                                      thread_count=self.plan['threads'],
                                      cat_features=tuple(column for column in schema['categorical'] if column in columns))
        raise ValueError('Họ boosting không hợp lệ: ' + name)

    def runBoostingCrossValidation(self, case_id, case, X, y, folds, fold_numbers=(0, 1, 2),
                                   feature_columns_by_fold=None):
        """CV bổ sung trên train; số vòng cố định, không dùng probe để early stop."""
        if case['model'] not in ['XGB', 'CAT']:
            raise ValueError('Chỉ dùng phương thức này cho XGB hoặc CAT.')
        if not X.index.equals(y.index) or not X.index.equals(folds.index):
            raise ValueError('Feature, label và fold phải có cùng ID và thứ tự.')
        if set(folds.unique()) != {0, 1, 2}:
            raise ValueError('Dùng đúng ba fold train đã có.')
        if not fold_numbers or any(fold not in [0, 1, 2] for fold in fold_numbers):
            raise ValueError('Chỉ chạy fold 0, 1 hoặc 2.')
        if len(set(fold_numbers)) != len(fold_numbers):
            raise ValueError('Không lặp lại cùng một fold trong một lần gọi.')
        source_schema = self.schemas[case['set']]
        folder = self.cache_dir / case_id.lower()
        folder.mkdir(exist_ok=True)
        records = []
        for fold in fold_numbers:
            is_fit = folds != fold
            is_probe = folds == fold
            probe_ids = X.index[is_probe]
            probe_y = y.loc[is_probe]
            columns = (source_schema['feature_order'] if feature_columns_by_fold is None
                       else feature_columns_by_fold[str(fold)])
            if len(columns) != len(set(columns)) or not set(columns).issubset(source_schema['feature_order']):
                raise ValueError('Fold feature list must contain unique columns from the source schema.')
            schema = {
                'feature_order': list(columns),
                'numeric': [column for column in source_schema['numeric'] if column in columns],
                'categorical': [column for column in source_schema['categorical'] if column in columns]
            }
            fold_case = case
            if feature_columns_by_fold is not None:
                feature_hash = hashlib.sha256(json.dumps(list(columns)).encode('utf-8')).hexdigest()
                fold_case = {**case, 'selection_fold': fold, 'selected_features_hash': feature_hash}
            path = folder / f'fold_{fold}.npz'
            checkpoint = self.loadCheckpoint(path, probe_ids, probe_y, fold_case)
            if checkpoint is not None:
                score, record = checkpoint
                print(case_id, 'fold', fold, ': dùng checkpoint, không fit lại', flush=True)
                records.append(record)
                continue

            # Chuẩn bị dữ liệu fit và fit model nằm trong cùng phép đo fit_s.
            started = time.perf_counter()
            fit_data = self.prepareBoostingData(X.loc[is_fit, columns], schema, case['model'])
            estimator = self.createBoostingModel(case, feature_columns=columns)
            estimator.fit(fit_data, y.loc[is_fit])
            fit_s = time.perf_counter() - started

            started = time.perf_counter()
            category_types = {}
            for column in schema['categorical']:
                category_types[column] = fit_data[column].dtype
            probe_data = self.prepareBoostingData(
                X.loc[is_probe, columns], schema, case['model'], category_types)
            score = estimator.predict_proba(probe_data)[:, 1]
            score_fit = estimator.predict_proba(fit_data)[:, 1]
            predict_s = time.perf_counter() - started
            record = {
                'case_id': case_id, 'set': case['set'], 'model': case['model'],
                'fold': fold, 'config': json.dumps(case['config'], sort_keys=True),
                'fit_n': int(is_fit.sum()), 'probe_n': int(is_probe.sum()),
                'features_n': len(columns),
                'ap': average_precision_score(probe_y, score),
                'roc_auc': roc_auc_score(probe_y, score),
                'train_ap': average_precision_score(y.loc[is_fit], score_fit),
                'brier': brier_score_loss(probe_y, score),
                'fit_s': fit_s, 'predict_s': predict_s,
                'n_jobs_actual': self.plan['threads'],
                'library_version': self.plan['libraries'][case['model']]
            }
            self.saveCheckpoint(path, probe_ids, probe_y, score, record, fold_case)
            records.append(record)
            print(case_id, 'fold', fold, 'AP=', round(record['ap'], 5),
                  'fit_s=', round(fit_s, 1), 'predict_s=', round(predict_s, 1), flush=True)
            del estimator, fit_data, probe_data, score, score_fit
            gc.collect()
        return records

    def runFamily(self, model_name, catalogue, train_data, y, folds):
        """Run one model family on A and B, keeping catalogue and fold order."""
        records = []
        for feature_set in ['A', 'B']:
            feature_columns = self.schemas[feature_set]['feature_order']
            X = train_data.loc[:, feature_columns]
            assert (X[self.plan['log_columns']].min() >= 0).all()
            for case_id, case in catalogue.items():
                if case['model'] != model_name or case['set'] != feature_set:
                    continue
                fold_results = self.runCrossValidation(case_id, case, X, y, folds)
                records.extend(fold_results)
            del X
            gc.collect()
        return records

    def calibrationPredictions(self, case_id, case, X, y, folds):
        if not X.index.equals(y.index) or not X.index.equals(folds.index):
            raise ValueError('Feature, label and fold IDs must have the same order.')
        if set(folds.unique()) != {0, 1, 2}:
            raise ValueError('Use the three existing training folds.')
        raw_oof = pd.Series(np.nan, index=X.index, dtype=float)
        cal_oof = pd.Series(np.nan, index=X.index, dtype=float)
        records = []
        for fold in [0, 1, 2]:
            is_fit = folds != fold
            is_probe = folds == fold
            probe_ids = X.index[is_probe]
            probe_y = y.loc[is_probe]
            folder = self.cache_dir / case_id.lower()
            raw_path = folder / f'fold_{fold}.npz'
            raw_checkpoint = self.loadCheckpoint(raw_path, probe_ids, probe_y, case)
            if raw_checkpoint is None:
                raise ValueError('Run base-model CV before calibration: ' + case_id)
            raw_score, _ = raw_checkpoint
            raw_oof.loc[probe_ids] = raw_score

            path = folder / f'calibration_outer_{fold}.npz'
            checkpoint = self.loadCheckpoint(path, probe_ids, probe_y, case)
            if checkpoint is None:
                calibrated = self.createCalibratedModel(case)
                started = time.perf_counter()
                with warnings.catch_warnings(record=True) as events:
                    warnings.simplefilter('always', ConvergenceWarning)
                    calibrated.fit(X.loc[is_fit], y.loc[is_fit])
                fit_s = time.perf_counter() - started
                score = calibrated.predict_proba(X.loc[is_probe])[:, 1]
                converged = True
                for event in events:
                    if issubclass(event.category, ConvergenceWarning):
                        converged = False
                record = {'fold': fold, 'fit_n': int(is_fit.sum()),
                          'probe_n': int(is_probe.sum()), 'fit_s': fit_s,
                          'converged': converged}
                self.saveCheckpoint(path, probe_ids, probe_y, score, record, case)
                del calibrated
                gc.collect()
            else:
                score, record = checkpoint
                print('Sigmoid outer fold', fold, ': dùng checkpoint, không fit lại')
            cal_oof.loc[probe_ids] = score
            records.append(record)
            print('Sigmoid outer fold', fold, 'OK', flush=True)
        if raw_oof.isna().any() or cal_oof.isna().any():
            raise ValueError('OOF predictions are incomplete.')
        return raw_oof, cal_oof, records

    def fitModel(self, case, X, y, use_sigmoid):
        if use_sigmoid:
            model = self.createCalibratedModel(case)
        elif case['model'] == 'CAT':
            model = self.createBoostingModel(case)
        else:
            model = self.createPipeline(case)
        with warnings.catch_warnings(record=True) as events:
            warnings.simplefilter('always', ConvergenceWarning)
            model.fit(X, y)
        if any(issubclass(w.category, ConvergenceWarning) for w in events):
            raise ValueError('Mô hình cuối chưa hội tụ.')
        if case['model'] == 'RF':
            if use_sigmoid:
                model.estimator.set_params(model__n_jobs=1)
                model.calibrated_classifiers_[0].estimator.set_params(model__n_jobs=1)
            else:
                model.set_params(model__n_jobs=1)
        return model

    @staticmethod
    def policyMetrics(y, score, threshold, dataset, policy):
        y = np.asarray(y)
        score = np.asarray(score)
        prediction = (score >= threshold).astype('int8')
        tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
        return {
            'dataset': dataset, 'policy': policy, 'threshold': float(threshold),
            'n': len(y), 'positive_n': int(y.sum()),
            'ap': average_precision_score(y, score), 'roc_auc': roc_auc_score(y, score),
            'brier': brier_score_loss(y, score), 'accuracy': accuracy_score(y, prediction),
            'precision': precision_score(y, prediction, zero_division=0),
            'recall': recall_score(y, prediction, zero_division=0),
            'f1': f1_score(y, prediction, zero_division=0), 'alert_rate': float(prediction.mean()),
            'tn': int(tn), 'fp': int(fp), 'fn': int(fn), 'tp': int(tp),
            'cost_5_to_1': float((5 * fn + fp) / len(y))
        }

    @staticmethod
    def capacityMetrics(ids, y, score, dataset, fraction=0.1):
        ranked = pd.DataFrame({'SK_ID_CURR': np.asarray(ids),
                               'TARGET': np.asarray(y), 'score': np.asarray(score)})
        ranked = ranked.sort_values(['score', 'SK_ID_CURR'], ascending=[False, True], kind='stable')
        k = int(np.ceil(fraction * len(ranked)))
        captured = int(ranked.head(k)['TARGET'].sum())
        prevalence = float(ranked['TARGET'].mean())
        return {
            'dataset': dataset, 'fraction': fraction, 'review_n': k, 'captured_positive_n': captured,
            'precision': captured / k, 'recall': captured / int(ranked['TARGET'].sum()),
            'lift': (captured / k) / prevalence,
            'tie_break': 'score descending, SK_ID_CURR ascending'
        }

    @staticmethod
    def makeCacheKey(X, y, folds, plan, schemas, cache_version, rf_jobs=4):
        """One cache identity: actual train input and the settings affecting fit.

        Bump cache_version when changing preprocessing/training implementation.
        No source-tree, environment, model-artifact or report hashes are used.
        """
        if not X.index.equals(y.index) or not X.index.equals(folds.index):
            raise ValueError('Cache inputs must have aligned IDs.')
        identity = {'cache_version': cache_version, 'plan': plan, 'schemas': schemas,
                    'rf_jobs': rf_jobs,
                    'columns': X.columns.tolist(), 'dtypes': X.dtypes.astype(str).tolist()}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode('utf-8'))
        for start in range(0, len(X), 10000):
            batch = X.iloc[start:start + 10000]
            row_hashes = pd.util.hash_pandas_object(batch, index=True)
            digest.update(row_hashes.to_numpy().tobytes())
        digest.update(y.to_numpy().tobytes())
        digest.update(folds.to_numpy().tobytes())
        return digest.hexdigest()[:20]

    def loadCheckpoint(self, path, ids, y, case):
        """Return score/record, or None only when the checkpoint does not exist."""
        if not path.exists():
            return None
        expected_case = json.dumps(case, sort_keys=True)
        with np.load(path, allow_pickle=False) as saved:
            if str(saved['cache_key']) != self.cache_key or str(saved['case']) != expected_case:
                raise ValueError('Checkpoint belongs to different data/settings: ' + str(path))
            if not np.array_equal(saved['ids'], np.asarray(ids)):
                raise ValueError('Checkpoint IDs/order do not match: ' + str(path))
            if not np.array_equal(saved['y'], np.asarray(y)):
                raise ValueError('Checkpoint labels do not match: ' + str(path))
            score = saved['score']
            record = json.loads(str(saved['record']))
        if score.shape != (len(ids),) or not np.isfinite(score).all():
            raise ValueError('Checkpoint scores are incomplete or nonfinite.')
        if ((score < 0) | (score > 1)).any():
            raise ValueError('Checkpoint probabilities are outside [0, 1].')
        return score, record

    def saveCheckpoint(self, path, ids, y, score, record, case):
        if not np.isfinite(score).all() or ((score < 0) | (score > 1)).any():
            raise ValueError('Predicted probabilities must be finite and in [0, 1].')
        np.savez_compressed(path, cache_key=self.cache_key,
            case=json.dumps(case, sort_keys=True), ids=np.asarray(ids), y=np.asarray(y),
            score=score, record=json.dumps(record))

    @staticmethod
    def thresholdEvaluation(y, score):
        """Existing validation-only cost scenarios and tie-break, unchanged."""
        y = np.asarray(y)
        score = np.asarray(score)
        predictions = pd.DataFrame({'score': score, 'TARGET': y})
        thresholds = predictions.groupby('score', sort=True)['TARGET'].agg(n='size', positive_n='sum')
        thresholds = thresholds.sort_index(ascending=False)
        thresholds = thresholds.reset_index().rename(columns={'score': 'threshold'})
        positive_n = int(y.sum())
        negative_n = int((y == 0).sum())
        thresholds['tp'] = thresholds['positive_n'].cumsum()
        thresholds['fp'] = thresholds['n'].cumsum() - thresholds['tp']
        thresholds['fn'] = positive_n - thresholds['tp']
        thresholds['tn'] = negative_n - thresholds['fp']
        all_negative = pd.DataFrame([{
            'threshold': np.nextafter(score.max(), np.inf), 'n': 0, 'positive_n': 0,
            'tp': 0, 'fp': 0, 'fn': positive_n, 'tn': negative_n}])
        thresholds = pd.concat([all_negative, thresholds], ignore_index=True)
        thresholds['recall'] = thresholds['tp'] / positive_n
        thresholds['alert_rate'] = (thresholds['tp'] + thresholds['fp']) / len(y)
        sensitivity_rows = []
        for fn_cost in [2, 5, 10, 20]:
            candidate = thresholds.copy()
            candidate['relative_cost'] = (fn_cost * candidate['fn'] + candidate['fp']) / len(y)
            candidate = candidate.sort_values(['relative_cost', 'recall', 'threshold'],
                ascending=[True, False, False], kind='stable')
            chosen = candidate.iloc[0]
            sensitivity_rows.append({
                'fn_cost': fn_cost, 'fp_cost': 1, 'threshold': float(chosen['threshold']),
                'validation_cost': float(chosen['relative_cost']), 'recall': float(chosen['recall']),
                'alert_rate': float(chosen['alert_rate']), 'tp': int(chosen['tp']),
                'fp': int(chosen['fp']), 'fn': int(chosen['fn']), 'tn': int(chosen['tn'])})
        thresholds['cost_5_to_1'] = (5 * thresholds['fn'] + thresholds['fp']) / len(y)
        return thresholds, pd.DataFrame(sensitivity_rows)
