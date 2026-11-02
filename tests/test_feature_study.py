"""A reduced CatBoost schema must work even when categorical columns are removed."""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from models.HomeCreditTraining import HomeCreditTraining


def test_reduced_model_can_fit_without_original_categorical_input():
    schema = {'feature_order': ['amount', 'category'], 'numeric': ['amount'], 'categorical': ['category']}
    plan = {'CAT': {'iterations': 3, 'depth': 2, 'allow_writing_files': False, 'verbose': False},
            'threads': 1, 'seed': 42}
    fixture_cache = Path(__file__).resolve().parents[1] / 'tmp/feature_study_20261026/factory_test'
    trainer = HomeCreditTraining(plan, {'B': schema}, fixture_cache, 'fixture')
    case = {'set': 'B', 'model': 'CAT', 'config': {}}
    X = pd.DataFrame({'amount': [0., 1., np.nan, 3., 4., 5.] * 4})
    y = np.array([0, 0, 1, 0, 1, 0] * 4)
    model = trainer.createBoostingModel(case, ['amount'])
    model.fit(X, y)
    score = model.predict_proba(pd.DataFrame({'amount': [np.nan, 7.]}))[:, 1]
    assert np.isfinite(score).all()
    assert list(model.feature_names_) == ['amount']
    with pytest.raises(ValueError, match='Feature subset'):
        trainer.createBoostingModel(case, ['not_in_schema'])


def test_capacity_metrics_name_the_actual_review_fraction():
    result = HomeCreditTraining.capacityMetrics(
        [1, 2, 3, 4], [1, 0, 1, 0], [.9, .8, .2, .1], 'fixture', .5)
    assert result['fraction'] == .5 and result['review_n'] == 2
    assert result['precision'] == .5 and result['recall'] == .5
    assert result['lift'] == 1.
    assert not any('top10' in key for key in result)
