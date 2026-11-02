"""Artifact/inference checks for native categories, calibration and SHAP."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostClassifier, Pool
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import StratifiedKFold

from models.CreditRiskModel import CreditRiskModel
from web.analytics import base_model_contributions


@pytest.mark.parametrize('sigmoid', [False, True])
def test_catboost_artifact_scores_and_contributions(sigmoid):
    root = Path(__file__).resolve().parents[1] / 'tmp' / f'catboost_runtime_fixture_{str(sigmoid).lower()}'
    (root / 'artifacts').mkdir(parents=True, exist_ok=True)
    raw = pd.DataFrame({'amount': [0., 1., np.nan, 3., 4., 5.] * 6,
                        'category': ['A', 'B', None, 'A', 'B', 'C'] * 6})
    prepared = raw.copy()
    prepared['amount'] = prepared['amount'].astype('float32')
    prepared['category'] = prepared['category'].fillna('__MISSING__')
    y = np.array([0, 0, 1, 0, 1, 0] * 6)
    base = CatBoostClassifier(iterations=8, depth=2, random_seed=42,
        thread_count=1, cat_features=('category',), allow_writing_files=False, verbose=False)
    model = CalibratedClassifierCV(base, method='sigmoid', ensemble=False,
        cv=StratifiedKFold(3, shuffle=True, random_state=42)) if sigmoid else base
    model.fit(prepared, y)
    joblib.dump(model, root / 'artifacts/model.joblib')
    metadata = {'model_path': 'artifacts/model.joblib', 'feature_order': ['amount', 'category'],
        'numeric': ['amount'], 'categorical': ['category'], 'log_columns': [],
        'model_family': 'CAT', 'main_threshold': .2, 'model_version': 'test'}
    (root / 'artifacts/inference_metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
    runtime = CreditRiskModel(root).loadModel()
    data = runtime.prepareInput(raw[['category', 'amount']])
    pd.testing.assert_frame_equal(data, prepared)
    np.testing.assert_array_equal(runtime.predict(data)['score'], model.predict_proba(prepared)[:, 1])
    novel = pd.DataFrame({'amount': [np.nan, 0.], 'category': ['NEW', None]})
    assert np.isfinite(runtime.predict(runtime.prepareInput(novel))['score']).all()
    with pytest.raises(ValueError, match='vô hạn'):
        runtime.prepareInput(pd.DataFrame({'amount': [np.inf], 'category': ['A']}))
    fitted_base = model.calibrated_classifiers_[0].estimator if sigmoid else model
    terms = fitted_base.get_feature_importance(Pool(data.head(1), cat_features=['category']), type='ShapValues')[0]
    np.testing.assert_allclose(terms.sum(), fitted_base.predict(data.head(1), prediction_type='RawFormulaVal')[0], atol=1e-10)
    contributions = base_model_contributions(runtime, raw.head(1))
    assert {row['feature'] for row in contributions} == {'amount', 'category'}
    np.testing.assert_allclose(sum(row['value'] for row in contributions), terms[:-1].sum(), atol=1e-10)
