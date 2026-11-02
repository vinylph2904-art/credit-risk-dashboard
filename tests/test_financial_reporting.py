"""Financial denominators must remain separate from alerts and missing values."""
import json
import re

import numpy as np
import pandas as pd
import pytest

from web.financial import (financial_summary, financial_groups, bureau_summary,
    ratio_distribution, segment_labels, overview_figures, portfolio_figures,
    history_by_segment, history_figure, HISTORY_SOURCES)
from web.charts import DashboardCharts


def test_monthly_combines_percentage_and_counts_on_opposite_axes_without_filling_gaps():
    monthly = pd.DataFrame({'MONTHS_BALANCE': [-3, -1], 'share': [.125, 0.],
                            'known_n': [80, 47], 'overdue_n': [10, 0]})
    original = monthly.copy(deep=True)
    html = DashboardCharts().monthly(monthly, 'history-test')
    payload = json.loads(re.search(r'<script[^>]+>(.*)</script>', html).group(1))
    layout = payload['figure']['layout']
    line, bars = payload['figure']['data']
    assert layout['yaxis']['side'] == 'left' and layout['yaxis']['tickformat'] == '.1%'
    assert layout['yaxis2']['side'] == 'right' and layout['yaxis2']['overlaying'] == 'y'
    assert line['type'] == 'scatter' and line['yaxis'] == 'y'
    assert bars['type'] == 'bar' and bars['yaxis'] == 'y2'
    assert line['x'] == bars['x'] == [-3, -2, -1]
    assert line['y'] == [.125, None, 0.] and bars['y'] == [80., None, 47.]
    assert bars['text'] == ['80', None, '47']  # Counts stay counts on the right axis.
    assert line['connectgaps'] is False and line['zorder'] > bars['zorder']
    assert payload['interaction'] == {'type': 'drill', 'kind': 'month', 'key': 'x'}
    pd.testing.assert_frame_equal(monthly, original)


def test_chart_labels_keep_percentages_and_hide_unreadable_small_stacked_segments():
    import plotly.graph_objects as go
    figure = go.Figure(go.Bar(x=[.75, .04, None], y=['A', 'B', 'C'], orientation='h'))
    figure.update_layout(barmode='stack', xaxis={'tickformat': '.0%'})
    html = DashboardCharts()._html(figure, 'label-test')
    payload = json.loads(re.search(r'<script[^>]+>(.*)</script>', html).group(1))
    trace = payload['figure']['data'][0]
    assert trace['text'] == ['75,0%', None, None]
    assert payload['figure']['layout']['separators'] == ',.'
    assert trace['textposition'] == 'inside'
    assert trace['x'] == [.75, .04, None]


def test_financial_money_and_label_denominators_and_original_values():
    data = pd.DataFrame({'AMT_CREDIT': [100., 900., np.nan, 200.],
        'AMT_INCOME_TOTAL': [100., 1000., 0., 200.],
        'AMT_ANNUITY': [10., 100., 10., np.nan],
        'AMT_GOODS_PRICE': [100., 0., 100., 200.], 'TARGET': [1., 0., 1., np.nan]})
    original = data.copy(deep=True)
    result = financial_summary(data)
    assert result['credit'] == 1200
    assert result['credit_n'] == 3
    assert result['rate'] == pytest.approx(2/3)
    assert result['credit_share'] == .1  # Unlabeled money is outside BOTH sides.
    assert result['credit_income'] == 1
    assert result['annuity_income'] == .1
    assert result['credit_goods_n'] == 2
    pd.testing.assert_frame_equal(data, original)


def test_unknown_money_and_zero_are_different_and_no_label_inference():
    data = pd.DataFrame({'AMT_CREDIT': [np.nan, np.inf, -1],
        'AMT_INCOME_TOTAL': [1, 0, -1], 'AMT_ANNUITY': [0, 1, 2],
        'AMT_GOODS_PRICE': [1, 0, 1], 'alert': [1, 1, 0]})
    result = financial_summary(data)
    assert result['credit'] is None
    assert result['credit_income'] is None
    assert result['annuity_income'] == 0
    assert 'rate' not in result
    data.loc[0, 'AMT_CREDIT'] = 0
    assert financial_summary(data)['credit'] == 0


def test_segment_counts_and_amounts_reconcile_with_missing_category():
    data = pd.DataFrame({'AMT_CREDIT': [0., 250000., 500000., np.nan],
        'AMT_INCOME_TOTAL': [1.] * 4, 'AMT_ANNUITY': [1.] * 4,
        'AMT_GOODS_PRICE': [1.] * 4, 'TARGET': [0, 1, 0, 1]})
    rows = financial_groups(data, 'credit_band')
    assert sum(row['n'] for row in rows) == 4
    assert sum(row['credit'] or 0 for row in rows) == 750000
    assert {row['label'] for row in rows} == {'Dưới 250.000', '250.000–<500.000', '500.000–<1.000.000', 'Chưa có thông tin'}
    with pytest.raises(ValueError):
        segment_labels(data, 'untrusted-column')


@pytest.mark.parametrize('dimension,column,values,expected', [
    ('credit_band', 'AMT_CREDIT', [1000000., 500000., 250000., 0., np.nan],
     ['Dưới 250.000', '250.000–<500.000', '500.000–<1.000.000', 'Từ 1.000.000', 'Chưa có thông tin']),
    ('income_band', 'AMT_INCOME_TOTAL', [300000., 200000., 100000., 0., np.nan],
     ['Dưới 100.000', '100.000–<200.000', '200.000–<300.000', 'Từ 300.000', 'Chưa có thông tin']),
    ('age_band', 'AGE_YEARS', [60., 50., 40., 30., 0., np.nan],
     ['Dưới 30', '30–39', '40–49', '50–59', 'Từ 60', 'Chưa có thông tin']),
])
def test_numeric_segments_follow_band_order_with_unknown_last(dimension, column, values, expected):
    data = pd.DataFrame({key: [1.] * len(values) for key in
        ['AMT_CREDIT', 'AMT_INCOME_TOTAL', 'AMT_ANNUITY', 'AMT_GOODS_PRICE']})
    data[column] = values
    original = data.copy(deep=True)
    groups = financial_groups(data, dimension)
    assert [row['label'] for row in groups] == expected
    assert sum(row['n'] for row in groups) == len(data)
    pd.testing.assert_frame_equal(data, original)


def test_nominal_segments_keep_descending_credit_order():
    data = pd.DataFrame({'AMT_CREDIT': [10., 100.], 'AMT_INCOME_TOTAL': [1., 1.],
        'AMT_ANNUITY': [1., 1.], 'AMT_GOODS_PRICE': [1., 1.],
        'NAME_INCOME_TYPE': ['Working', 'Pensioner']})
    assert [row['label'] for row in financial_groups(data, 'income')] == ['Hưu trí', 'Đi làm']


def test_horizontal_history_shows_source_denominators_and_preserves_missing_rates():
    data = pd.DataFrame(index=range(4))
    for _, flag, count, share in HISTORY_SOURCES.values():
        data[flag], data[count], data[share] = [1, 1, 0, 1], [2, 2, 0, 0], [.5, 0., np.nan, .5]
    data['HAS_USABLE_CARD'] = 0
    original = data.copy(deep=True)
    html = history_figure(data, 'finance-overview-history-summary')
    payload = json.loads(re.search(r'<script[^>]+>(.*)</script>', html).group(1))
    trace = payload['figure']['data'][0]
    assert trace['orientation'] == 'h'
    assert trace['y'] == ['Bureau theo tháng', 'POS', 'Thẻ tín dụng', 'Kỳ trả góp']
    assert trace['x'] == [.5, .5, None, .5]
    assert trace['customdata'] == [2, 2, 0, 2]
    assert payload['figure']['layout']['yaxis']['ticktext'] == [
        'Bureau', 'POS', 'Thẻ tín dụng', 'Trả góp']
    assert '%{customdata:,}' in trace['hovertemplate']
    pd.testing.assert_frame_equal(data, original)


def test_bureau_pair_and_dpd_denominators_stay_separate():
    data = pd.DataFrame({'loan_n': [2, 1], 'money_n': [1, 0],
        'dpd_n': [2, 1], 'overdue_n': [1, 1], 'debt': [100., np.nan],
        'overdue': [20., np.nan], 'outside_overdue': [np.nan, 50.]})
    result = bureau_summary(data)
    assert result['share'] == .2
    assert result['rate'] == pytest.approx(2/3)
    assert result['outside_overdue'] == 50


def test_histogram_overflow_preserves_tail_instead_of_dropping_outliers():
    data = pd.DataFrame({'RATIO_CREDIT_INCOME_RECORDED': [0., 1., 2., 3., 100000., np.nan, np.inf]})
    html = ratio_distribution(data, 'credit_income')
    payload = json.loads(re.search(r'>(\{"figure".*)</script>', html).group(1))
    assert sum(payload['figure']['data'][0]['y']) == 5
    assert payload['figure']['data'][0]['x'][-1].startswith('≥')


def test_overview_and_analysis_have_distinct_questions_and_chart_sets():
    data = pd.DataFrame({'AMT_CREDIT': [100., 300.] * 4,
        'AMT_INCOME_TOTAL': [100., 200.] * 4, 'AMT_ANNUITY': [10., 20.] * 4,
        'AMT_GOODS_PRICE': [100., 300.] * 4, 'TARGET': [0, 1] * 4,
        'NAME_CONTRACT_TYPE': ['Cash loans'] * 8,
        'NAME_INCOME_TYPE': ['Working', 'Pensioner'] * 4,
        'FLAG_OWN_CAR': ['Y', 'N'] * 4, 'FLAG_OWN_REALTY': ['Y'] * 8,
        'RATIO_CREDIT_INCOME_RECORDED': [1., 1.5] * 4,
        'RATIO_ANNUITY_INCOME_RECORDED': [.1] * 8,
        'RATIO_CREDIT_GOODS_RECORDED': [1.] * 8})
    for _, flag, count, share in HISTORY_SOURCES.values():
        data[flag], data[count], data[share] = 1, 4, .25
    groups = financial_groups(data, 'income')
    overview = overview_figures(data, 'research', 'credit_income')
    analysis = portfolio_figures(data, groups, 'research', 'income', 'credit_income',
        {row['label']: '/' for row in groups}, financial_summary(data), 'installments')
    assert len(overview) == len(analysis) == 6
    for panel in overview:
        payload = json.loads(re.search(r'<script[^>]+>(.*)</script>', panel['html']).group(1))
        assert payload['interaction'] is None
    assert [re.search(r'id="([^"]+)"', row['html']).group(1) for row in overview] == [
        'finance-overview-credit-composition', 'finance-overview-loan-distribution',
        'finance-overview-income-distribution', 'finance-overview-history-summary',
        'finance-overview-ratio-distribution', 'finance-overview-asset-ownership']
    for index in [0, 1, 3, 4, 5]:
        payload = json.loads(re.search(r'<script[^>]+>(.*)</script>', analysis[index]['html']).group(1))
        assert payload['figure']['data'][0]['y'] == [row['label'] for row in groups]
        interaction = payload['interaction']
        if index != 3:
            assert interaction == {'type': 'filter', 'key': 'y', 'urls': {row['label']: '/' for row in groups}}
    overview_ids = {re.search(r'id="([^"]+)"', row['html']).group(1) for row in overview}
    analysis_ids = {re.search(r'id="([^"]+)"', row['html']).group(1) for row in analysis}
    assert overview_ids.isdisjoint(analysis_ids)
    assert {row['title'] for row in overview}.isdisjoint({row['title'] for row in analysis})
    assert any('Phân bố' in row['title'] for row in overview)
    assert not any('Phân bố' in row['title'] for row in analysis)
    assert any('tham chiếu' in row['title'] for row in analysis)
    assert any('Lịch sử trả góp theo phân khúc' == row['title'] for row in analysis)


def test_segment_history_keeps_unavailable_separate_from_no_observed_signal():
    data = pd.DataFrame({'NAME_CONTRACT_TYPE': ['Cash loans'] * 3,
        'HAS_USABLE_INSTALLMENTS': [1, 1, 0],
        'INS_OBS_VERSIONED_PERIOD_N': [2, 2, 0],
        'INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE': [.5, 0., 0.]})
    html = history_by_segment(data, 'product', ['Vay tiền mặt'], 'installments', {})
    payload = json.loads(re.search(r'>(\{"figure".*)</script>', html).group(1))
    rows = payload['figure']['data']
    assert len(rows) == 3
    assert [row['customdata'][0] for row in rows] == [1, 1, 1]
    assert rows[-1]['name'] == 'Chưa xác định'
