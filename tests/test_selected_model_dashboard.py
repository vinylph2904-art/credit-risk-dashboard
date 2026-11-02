"""Regression checks for the frozen selected model in the web runtime."""
from pathlib import Path

from bs4 import BeautifulSoup
from catboost import Pool
import numpy as np
import pandas as pd
import pytest

from auth_database import AuthDatabase
from models.CreditRiskModel import CreditRiskModel
from models.HomeCreditPreparation import HomeCreditPreparation
from web import runtime
from web.analytics import base_model_contributions
from web.app import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def selected():
    model = CreditRiskModel(ROOT).loadModel()
    source = pd.read_parquet(ROOT / 'data/features/b/validation.parquet').head(100).set_index('SK_ID_CURR')
    return model, source


def test_runtime_predictions_and_shap_use_frozen_selected_artifact(selected):
    model, source = selected
    assert model.version == 'catboost-selected-a8763faa0c2ef0786f72'
    assert len(model.feature_order) == 182
    assert model.threshold == 0.14539365168823878
    inputs = model.prepareInput(source.loc[:, model.feature_order])
    saved = pd.read_parquet(ROOT / model.metadata['evaluation']['folder'] /
                            'validation_predictions.parquet').set_index('SK_ID_CURR')
    np.testing.assert_allclose(model.predict(inputs)['score'], saved.loc[inputs.index, 'score'], rtol=0, atol=1e-12)
    terms = model.model.get_feature_importance(Pool(inputs.head(1), cat_features=model.categorical), type='ShapValues')[0]
    margin = model.model.predict(inputs.head(1), prediction_type='RawFormulaVal')[0]
    assert terms.sum() == pytest.approx(margin, abs=1e-10)
    contribution = base_model_contributions(model, source.loc[:, model.feature_order].head(1))
    expected = sorted(zip(model.feature_order, terms[:-1]), key=lambda row: -abs(row[1]))[:10]
    assert [row['feature'] for row in contribution] == [row[0] for row in expected]
    np.testing.assert_allclose([row['value'] for row in contribution], [row[1] for row in expected], atol=1e-10)


def test_selected_simulation_uses_original_goods_price_without_extra_model_inputs(selected):
    model, source = selected
    assert 'AMT_GOODS_PRICE' not in model.feature_order
    row = source.loc[source['AMT_GOODS_PRICE'].gt(0) & source['AMT_CREDIT'].gt(0)].head(1)
    original = row.copy(deep=True)
    changes = {'AMT_CREDIT': float(row.iloc[0]['AMT_CREDIT']) * .8,
               'AMT_ANNUITY': float(row.iloc[0]['AMT_ANNUITY']) * .8}
    result = model.simulate(row, changes)
    expected = row.assign(**changes)
    expected = HomeCreditPreparation.addApplicationRatios(expected)
    score = model.predict(model.prepareInput(expected.loc[:, model.feature_order]))['score'].iloc[0]
    assert result['scenario_score'] == pytest.approx(score, abs=1e-12)
    ratio = next(item for item in result['comparisons'] if item['label'] == 'Credit / Goods price')
    assert ratio['scenario'] == pytest.approx(changes['AMT_CREDIT'] / row.iloc[0]['AMT_GOODS_PRICE'])
    pd.testing.assert_frame_equal(row, original)
    assert model.simulate(row, {})['delta_pp'] == 0


def test_model_http_page_uses_selected_validation_reports(monkeypatch):
    database = AuthDatabase()
    monkeypatch.setattr(runtime, 'get_db', lambda: database)
    monkeypatch.setitem(app.config, 'TESTING', True)
    client = app.test_client()
    csrf = BeautifulSoup(client.get('/login').data, 'html.parser').select_one('[name=csrf_token]')['value']
    assert client.post('/login', data={'username': 'analyst_test', 'password': 'test-password!',
                                      'csrf_token': csrf}).status_code == 302
    page = client.get('/model')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert '182 đặc trưng đầu vào' in text
    assert 'Validation · dùng để chọn ngưỡng' in text
    assert 'CatBoost — Filter 182' in text
    for chart in ['pr', 'roc', 'confusion', 'calibration', 'threshold', 'gains']:
        assert f'evaluation-{chart}' in text
    image = client.get('/model/evaluation.png')
    assert image.status_code == 200 and image.mimetype == 'image/png'
    assert image.data == (ROOT / runtime.model.metadata['evaluation']['folder'] / 'figures/validation.png').read_bytes()
