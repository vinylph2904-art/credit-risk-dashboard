"""Reading aids and filter controls must preserve the scope of the report."""
from datetime import datetime
import json
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pandas as pd
import pytest

from web.app import app
from web import financial_context as views, request_helpers as query, runtime
from web.financial import HISTORY_SOURCES, overview_figures


@pytest.fixture
def frame():
    data = pd.DataFrame({
        'AMT_CREDIT': [930000., 70000., 5000000.],
        'AMT_INCOME_TOTAL': [100000., 200000., 300000.],
        'AMT_ANNUITY': [10000., 20000., 30000.],
        'AMT_GOODS_PRICE': [930000., 70000., 5000000.],
        'TARGET': [0., 1., None], 'NAME_CONTRACT_TYPE': ['Cash loans'] * 3,
        'AGE_YEARS': [25., 35., 65.],
        'NAME_INCOME_TYPE': ['Working', 'Pensioner', 'Working'],
        'FLAG_OWN_CAR': ['Y', 'N', 'Y'], 'FLAG_OWN_REALTY': ['Y', 'Y', 'N'],
        'RATIO_CREDIT_INCOME_RECORDED': [9.3, .35, None],
        'RATIO_ANNUITY_INCOME_RECORDED': [.1] * 3,
        'RATIO_CREDIT_GOODS_RECORDED': [1.] * 3,
    })
    for _, flag, count, share in HISTORY_SOURCES.values():
        data[flag], data[count], data[share] = 1, 4, .25
    return data


@pytest.fixture
def report_context(monkeypatch, frame):
    monkeypatch.setattr(views, 'financial_data', lambda: (
        'research', 'test', frame, frame, query.read_cohort_filters(), 'credit_band', ''))
    monkeypatch.setattr(views, 'financial_history_context', lambda *args: (
        dict(overdue=0, debt=100, money_n=3, share=0, rate=0,
             overdue_n=0, dpd_n=3, outside_overdue=0),
        dict(refused_rate=0, refused_profile_rate=0, previous_n=3,
             previous_profile_n=3, previous_unknown_n=0)))
    return lambda: views.financial_context(overview=True)


def test_filter_chips_preserve_zero_and_other_controls(report_context):
    with app.test_request_context('/?product=Cash+loans&amount_min=0&ratio=annuity_income&currency=currency+2'):
        context = report_context()
        assert context['is_filtered'] is False  # An applied filter may keep every row.
        chips = context['active_financial_filters']
        assert len(chips) == 2
        product_url = parse_qs(urlsplit(chips[0]['url']).query)
        assert 'product' not in product_url
        assert product_url['amount_min'] == ['0']
        assert product_url['ratio'] == ['annuity_income']
        assert product_url['currency'] == ['currency 2']
        cleared = parse_qs(urlsplit(context['clear_financial_filters_url']).query)
        assert 'product' not in cleared and 'amount_min' not in cleared
        assert cleared['ratio'] == ['annuity_income'] and cleared['currency'] == ['currency 2']
        assert chips[1]['label'].endswith(': 0')
        assert next(k for k in context['kpis'] if k['key'] == 'credit_share')['n'] == 2


def test_filter_chips_do_not_round_the_applied_limits(report_context):
    with app.test_request_context('/?amount_min=0.00001&age_max=32.5'):
        labels = [item['label'] for item in report_context()['active_financial_filters']]
        assert any(label.endswith(': 0,00001') for label in labels)
        assert any(label.endswith(': 32,5') for label in labels)


def test_chart_hover_keeps_correct_denominators_and_empty_states(frame):
    panels = overview_figures(frame, 'research', 'credit_income')
    chart = BeautifulSoup(panels[0]['html'], 'html.parser')
    payload = json.loads(chart.select_one('.chart-data').string)
    assert payload['figure']['data'][0]['values'] == [930000, 70000]
    assert payload['figure']['data'][0]['customdata'] == [[1, 2], [1, 2]]
    assert not any(panel.get('summary') for panel in panels)
    empty = overview_figures(frame.iloc[:0], 'research', 'credit_income')
    assert len(empty) == 6
    empty_chart = BeautifulSoup(empty[0]['html'], 'html.parser')
    assert json.loads(empty_chart.select_one('.chart-data').string)['figure']['layout']['annotations']


def test_real_template_keeps_five_kpis_and_exposes_applied_filters(report_context):
    with app.test_request_context('/?product=Cash+loans&amount_min=0'):
        context = report_context()
        html = app.jinja_env.get_template('financial_dashboard.html').render(
            **context, financial_view=True, plotly_enabled=True, active='dashboard',
            csrf_token='test', asset_version=runtime.ASSET_VERSION,
            is_admin=False, is_manager=False, signed_in_user='analyst',
            current_user={'role': 'analyst'}, roles={'analyst': 'Phân tích'},
            user_display_name='Analyst', home_endpoint='dashboard',
            model_version='test', model_threshold=.5, viewed_at=datetime(2026, 10, 30),
            products=runtime.PRODUCTS, income_types=runtime.INCOME_TYPES,
            credit_states=runtime.CREDIT_STATES, cohort_url=query.cohort_url,
        )
        page = BeautifulSoup(html, 'html.parser')
        assert len(page.select('[data-financial-kpi]')) == 5
        assert page.select_one('.financial-kpi-sample') is None
        assert page.select_one('#financial-analysis-title') is None
        assert len(page.select('.financial-chart-grid > .report-panel')) == 6
        assert page.select_one('.financial-chart-summary') is None
        assert len(page.select('.financial-dashboard-header .financial-filter-chip')) == 2
        assert page.select_one('#financial-filters') is None
        assert page.select_one('link[href*="financial_workspace.css"]')
        assert page.select_one('.topbar h1').get_text(strip=True) == 'Tổng quan tài chính & tín dụng'
        assert page.select_one('.topbar .financial-topbar-title .financial-scopebar')
        assert page.select_one('.page .financial-scopebar') is None
        assert page.select_one('.financial-analysis-link') is None
        assert page.select_one('.topbar #financial-ratio') is None
        assert page.select_one('.financial-chart-grid [data-chart-position="5"] #financial-ratio')
        assert page.select_one('.topbar [data-open="financial-filters"]') is None
        assert len(page.select('.page #financial-ratio')) == 1
        assert page.select_one('.page h1') is None
        assert page.select_one('.sidebar-account strong').get_text(strip=True) == 'Analyst'
        account = page.select_one('.sidebar-account a.sidebar-user')
        assert account and account['href'] == '/account'
        assert page.select_one('details.sidebar-account') is None
        assert page.select_one('.sidebar-account-panel') is None
        assert page.select_one('.topbar-user') is None
        chart_ids = [node['id'] for node in page.select('.dashboard-chart')]
        assert len(chart_ids) == len(set(chart_ids)) == 6
