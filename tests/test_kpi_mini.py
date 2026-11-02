"""Mini charts must preserve denominators, group eligibility and missing values."""
import math

import pandas as pd
import pytest

from web.kpi_dimensions import financial_mini, mini_points
from web.kpi_history_mini import history_mini_charts


@pytest.fixture
def mini_profiles():
    count = 60
    return pd.DataFrame({
        'source_application_id': range(count),
        'AGE_YEARS': [25.] * 20 + [35.] * 20 + [65.] * 20,
        'NAME_CONTRACT_TYPE': ['Cash loans'] * 30 + ['Revolving loans'] * 30,
        'NAME_INCOME_TYPE': ['Working'] * 20 + ['Pensioner'] * 40,
        'AMT_CREDIT': [100.] * count,
        'AMT_INCOME_TOTAL': [100000.] * 30 + [300000.] * 30,
        'AMT_ANNUITY': [10.] * count,
        'AMT_GOODS_PRICE': [100.] * count,
        'TARGET': [0.] * 30 + [1.] * 30,
        'RATIO_CREDIT_INCOME_RECORDED': [1.] * count,
        'RATIO_ANNUITY_INCOME_RECORDED': [.1] * count,
        'RATIO_CREDIT_GOODS_RECORDED': [1.] * count,
    })


def test_donut_includes_small_groups_in_remaining_and_reconciles_total():
    rows = [{'label': str(i), 'value': i, 'n': 10 if i < 6 else 2}
            for i in range(1, 8)]
    result = mini_points(rows, 'Composition', 'donut')
    assert len(result['points']) == 5
    assert result['truncated'] is True
    assert sum(point['value'] for point in result['points']) == 28
    assert sum(point['share'] for point in result['points']) == pytest.approx(1)
    remaining = result['points'][-1]
    assert remaining['value'] == 14 and remaining['n'] == 14
    for previous, current in zip(result['points'], result['points'][1:]):
        assert current['offset'] == pytest.approx(previous['offset'] + previous['share'] * 100)


@pytest.mark.parametrize('chart', ['donut', 'bar', 'stacked', 'horizontal'])
def test_invalid_observations_do_not_become_zero(chart):
    rows = [{'label': str(i), 'value': value, 'n': 10}
            for i, value in enumerate([None, math.nan, math.inf, -1])]
    assert mini_points(rows, 'Missing', chart)['points'] == []


def test_zero_bars_and_unbounded_ratios_remain_visible_as_real_values():
    zero = mini_points([{'label': str(i), 'value': 0, 'n': 5} for i in range(2)], 'Zero')
    assert [point['height'] for point in zero['points']] == [0, 0]
    ratios = mini_points([{'label': 'A', 'value': .5, 'n': 5},
                          {'label': 'B', 'value': 1.5, 'n': 5}], 'Ratios', 'horizontal')
    assert [point['value'] for point in ratios['points']] == [.5, 1.5]
    assert ratios['points'][1]['height'] == 34
    assert not mini_points([{'label': 'A', 'value': 0, 'n': 5},
                            {'label': 'B', 'value': 0, 'n': 5}], 'Zero', 'donut')['points']


def test_top_five_excludes_undersized_groups_and_keeps_stable_ties():
    rows = [{'label': label, 'value': 10, 'n': 5} for label in 'FEDCBA']
    rows.append({'label': 'Too small', 'value': 100, 'n': 4})
    result = mini_points(rows, 'Groups')
    assert [point['label'] for point in result['points']] == list('ABCDE')
    assert result['truncated'] and result['caption'].endswith('Top 5')


def test_financial_mini_avoids_selected_dimension_and_does_not_mutate_profiles(mini_profiles):
    original = mini_profiles.copy(deep=True)
    result = financial_mini(mini_profiles, 'credit', 'credit_n', 'product')
    assert result['dimension'] == 'age_band'
    assert len(result['points']) == 3
    pd.testing.assert_frame_equal(original, mini_profiles)


def test_difficult_credit_chart_measures_contributions_not_within_group_rates(mini_profiles):
    result = financial_mini(mini_profiles, 'credit_share', 'label_credit_n')
    contributions = {point['label']: point['value'] for point in result['points']}
    assert contributions['Đi làm'] == 0
    assert contributions['Hưu trí'] == 1
    assert sum(contributions.values()) == 1


def test_history_profile_count_is_distinct_and_metadata_side_effect_is_preserved(mini_profiles):
    profiles = mini_profiles.copy()
    profiles['NAME_CONTRACT_TYPE'] = 'Cash loans'
    ids = list(range(60))
    monthly = {'data': pd.DataFrame({'SK_ID_CURR': ids * 2})}
    periods = pd.DataFrame({'SK_ID_CURR': ids * 2,
                           'status': ['Trả đủ đúng hạn'] * 60 + ['Trả đủ sau hạn'] * 60})
    cards = pd.DataFrame({'SK_ID_CURR': ids, 'utilization': [1.5] * 60})
    values = {'profiles': profiles, 'payment_report': {'data': periods},
              'card_report': {'data': cards}}
    result = history_mini_charts(values, monthly)
    assert sum(point['value'] for point in result['history_profiles']) == 60
    assert values['kpi_mini_meta']['history_profiles']['caption'] == 'Theo nhóm tuổi'
    assert all(point['value'] == .5 for point in result['on_time'])
    assert all(point['value'] == 1.5 for point in result['utilization'])
    assert set(values['kpi_mini_meta']) == set(result)


def test_bureau_mini_keeps_money_and_dpd_denominators_separate(mini_profiles):
    loans = pd.DataFrame({'SK_ID_CURR': range(60), 'CREDIT_TYPE': ['Credit card'] * 30 + ['Consumer credit'] * 30,
                          'money_valid': [True] * 60, 'dpd_valid': [True] * 40 + [False] * 20,
                          'debt': [100.] * 60, 'overdue': [10.] * 60,
                          'is_overdue': [False] * 20 + [True] * 40})
    values = {'profiles': mini_profiles, 'finance': {'data': loans}}
    result = history_mini_charts(values)
    assert sum(point['value'] for point in result['debt']) == 6000
    assert [point['value'] for point in result['money_share']] == [.1] * 3
    assert [point['value'] for point in result['loan_share']] == [0, 1]
