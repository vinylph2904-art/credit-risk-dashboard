"""Scenario contracts: preserve cohorts, rank ties, recompute inputs without writes."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from models.CreditRiskModel import CreditRiskModel
from models.HomeCreditPreparation import HomeCreditPreparation
from web.analytics import policy_scenario


def test_threshold_scenario_expands_from_full_scored_cohort_and_preserves_source():
    data = pd.DataFrame({'profile_id': [1, 2, 3, 4], 'source_application_id': [11, 12, 13, 14],
        'score': [.12, .15, .20, np.nan], 'AMT_CREDIT': [100., np.nan, 300., 9999.],
        'review_status': ['new', 'in_review', 'reviewed', 'new'], 'alert': [0, 1, 1, np.nan]})
    before = data.copy(deep=True)
    result = policy_scenario(data, .15, .12)
    assert result['baseline']['scored_n'] == 3
    assert result['baseline']['alert_n'] == 2 and result['scenario']['alert_n'] == 3
    assert result['baseline']['pending_n'] == 1 and result['scenario']['pending_n'] == 2
    assert result['scenario']['alert_credit'] == 400
    assert result['scenario']['alert_credit_share'] == 1
    assert result['scenario']['excluded_money_n'] == 1
    pd.testing.assert_frame_equal(data, before)


def test_capacity_respects_review_scope_hard_limit_and_ties():
    data = pd.DataFrame({'profile_id': [1, 2, 3, 4, 5], 'source_application_id': [40, 20, 30, 10, 50],
        'score': [.4, .3, .3, .9, .1], 'AMT_CREDIT': [100.] * 5,
        'review_status': ['new', 'new', 'in_review', 'reviewed', 'new']})
    selected = policy_scenario(data, .2, .2, 2)['scenario']['capacity']
    assert [row['id'] for row in selected['profiles']] == [40, 20]
    assert selected['selected_n'] == 2 and selected['remaining_n'] == 1
    assert selected['ties_n'] == 2 and selected['unselected_ties_n'] == 1
    excess = policy_scenario(data, .2, .2, 9)['scenario']['capacity']
    assert excess['selected_n'] == 3 and excess['unused_n'] == 6
    zero = policy_scenario(data, .2, .2, 0)['scenario']['capacity']
    assert zero['selected_n'] == 0 and zero['cutoff'] is None and zero['remaining_n'] == 3
    entire = policy_scenario(data, .2, .2, 5, 'portfolio')['scenario']['capacity']
    assert entire['selected_n'] == 5 and entire['profiles'][0]['id'] == 10


def test_empty_or_unknown_money_scenario_does_not_invent_values():
    data = pd.DataFrame({'profile_id': [1], 'source_application_id': [10], 'score': [.5],
        'AMT_CREDIT': [np.nan], 'review_status': ['new']})
    result = policy_scenario(data, .2, .2, 1)
    assert result['scenario']['alert_credit'] is None
    assert result['scenario']['alert_credit_share'] is None
    assert result['scenario']['capacity']['credit'] is None
    empty = policy_scenario(data.iloc[:0], .2, .2, 5)
    assert empty['scenario']['alert_rate'] is None
    assert empty['scenario']['capacity']['unused_n'] == 5


@pytest.mark.parametrize('threshold,capacity,scope', [(np.nan, 1, 'backlog'),
    (np.inf, 1, 'backlog'), (-.1, 1, 'backlog'), (1.1, 1, 'backlog'),
    (.2, -1, 'backlog'), (.2, 1.5, 'backlog'), (.2, 1, 'unknown')])
def test_invalid_policy_inputs_rejected(threshold, capacity, scope):
    with pytest.raises(ValueError):
        policy_scenario(pd.DataFrame(), .2, threshold, capacity, scope)


def simulation_fixture():
    data = pd.DataFrame({'AMT_INCOME_TOTAL': [200.], 'AMT_CREDIT': [1000.],
        'AMT_ANNUITY': [50.], 'AMT_GOODS_PRICE': [1200.], 'CNT_FAM_MEMBERS': [2.],
        'HAS_USABLE_BUREAU': [0.], 'BUR_DEBT': [np.nan], 'EXT_SOURCE_1': [.3]})
    data = HomeCreditPreparation.addApplicationRatios(data)
    runtime = CreditRiskModel(Path.cwd())
    runtime.feature_order = data.columns.tolist()
    runtime.numeric = data.columns.tolist()
    runtime.categorical = []
    runtime.log_columns = []
    runtime.family = 'CAT'
    runtime.threshold, runtime.version = .2, 'fixture'
    observed = []
    def predict_proba(frame):
        observed.append(frame.copy(deep=True))
        return np.tile([.7, .3], (len(frame), 1))
    runtime.model = SimpleNamespace(predict_proba=predict_proba)
    return runtime, data, observed


def test_profile_simulation_updates_dependent_ratios_and_preserves_other_features():
    model, source, observed = simulation_fixture()
    before = source.copy(deep=True)
    model.simulate(source, {'AMT_INCOME_TOTAL': 100.})
    sent = observed[-1].iloc[0]
    assert sent['RATIO_CREDIT_INCOME_RECORDED'] == 10
    assert sent['RATIO_ANNUITY_INCOME_RECORDED'] == .5
    assert sent['INCOME_DIV_FAMILY_SIZE_RECORDED'] == 50
    assert sent['RATIO_CREDIT_GOODS_RECORDED'] == np.float32(before.iloc[0]['RATIO_CREDIT_GOODS_RECORDED'])
    assert sent['EXT_SOURCE_1'] == np.float32(.3) and sent['HAS_USABLE_BUREAU'] == 0
    assert pd.isna(sent['BUR_DEBT'])
    pd.testing.assert_frame_equal(source, before)
    model.simulate(source, {'AMT_CREDIT': 600., 'AMT_ANNUITY': 30.})
    sent = observed[-1].iloc[0]
    assert sent['RATIO_CREDIT_INCOME_RECORDED'] == 3
    assert sent['RATIO_CREDIT_GOODS_RECORDED'] == .5
    assert sent['RATIO_ANNUITY_INCOME_RECORDED'] == np.float32(.15)


def test_unchanged_profile_is_exact_and_ratio_zero_rules_remain_original():
    model, source, observed = simulation_fixture()
    result = model.simulate(source, {'AMT_INCOME_TOTAL': 200.})
    pd.testing.assert_frame_equal(observed[0], observed[1])
    assert result['delta_pp'] == 0
    source['AMT_INCOME_TOTAL'] = 0
    zero = HomeCreditPreparation.addApplicationRatios(source.copy())
    assert pd.isna(zero.iloc[0]['RATIO_CREDIT_INCOME_RECORDED'])
    assert zero.iloc[0]['INCOME_DIV_FAMILY_SIZE_RECORDED'] == 0


@pytest.mark.parametrize('changes', [{'EXT_SOURCE_1': .8}, {'TARGET': 0}, {'AMT_CREDIT': 500},
    {'AMT_INCOME_TOTAL': 0}, {'AMT_INCOME_TOTAL': -1}, {'AMT_INCOME_TOTAL': True},
    {'AMT_INCOME_TOTAL': np.inf}, {'AMT_INCOME_TOTAL': float('nan')},
    {'AMT_INCOME_TOTAL': '100'}, {'AMT_INCOME_TOTAL': 10**400}])
def test_profile_rejects_incomplete_or_unsupported_edits(changes):
    model, source, observed = simulation_fixture()
    with pytest.raises(ValueError):
        model.simulate(source, changes)
    assert not observed
