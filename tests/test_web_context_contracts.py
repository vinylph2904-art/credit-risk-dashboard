"""Managed contexts and drill-through use the same observations without database I/O."""
from unittest.mock import patch

import pandas as pd
import pytest

from models.CreditRiskPortfolio import CreditRiskPortfolio
from web.app import app
from web import portfolio_context as views, runtime
from web.drilldown import select_chart_records


def portfolio_fixture():
    ids = list(range(1, 7))
    profiles = pd.DataFrame({
        'source_application_id': ids, 'profile_id': ids,
        'case_label': [str(value) for value in ids],
        'NAME_INCOME_TYPE': ['Working'] * 3 + ['Pensioner'] * 3,
        'NAME_CONTRACT_TYPE': ['Cash loans'] * 3 + ['Revolving loans'] * 3,
        'AGE_YEARS': [25, 35, 45, 55, 65, 75], 'AMT_CREDIT': [100.] * 6,
        'review_status': ['new', 'in_review', 'reviewed'] * 2,
        'score': [0., .05, .1, .25, .5, 1.], 'alert': [0, 0, 0, 1, 1, 1],
        'assignee': ['analyst', '', 'analyst'] * 2,
    })
    bureau = pd.DataFrame({
        'SK_ID_CURR': ids, 'SK_ID_BUREAU': ids,
        'CREDIT_ACTIVE': ['Active'] * 6, 'CREDIT_CURRENCY': ['currency 1'] * 6,
        'DAYS_CREDIT': [-100] * 6, 'DAYS_CREDIT_UPDATE': [-1] * 6,
        'CREDIT_DAY_OVERDUE': [0, 5, 40, 90, 100, 0],
        'AMT_CREDIT_SUM_DEBT': [100.] * 6, 'AMT_CREDIT_SUM_OVERDUE': [0., 10., 10., 0., 20., 0.],
    })
    cards = pd.DataFrame({
        'SK_ID_CURR': ids, 'SK_ID_PREV': ids, 'MONTHS_BALANCE': [-1] * 6,
        'AMT_BALANCE': [0, 25, 50, 75, 100, 150],
        'AMT_CREDIT_LIMIT_ACTUAL': [100.] * 6, 'SK_DPD': [0] * 6,
    })
    payments = pd.DataFrame({
        'SK_ID_CURR': ids, 'SK_ID_PREV': ids, 'NUM_INSTALMENT_VERSION': [1] * 6,
        'NUM_INSTALMENT_NUMBER': [1] * 6, 'DAYS_INSTALMENT': [-10] * 6,
        'DAYS_ENTRY_PAYMENT': [-10] * 3 + [-5] * 3,
        'AMT_INSTALMENT': [100.] * 6, 'AMT_PAYMENT': [100.] * 6,
    })
    monthly = pd.DataFrame({
        'SK_ID_CURR': ids * 2, 'loan_id': ids * 2,
        'MONTHS_BALANCE': [-2] * 6 + [-1] * 6, 'state': ['0'] * 6 + ['1'] * 6,
    })

    class FixturePortfolio(CreditRiskPortfolio):
        def __init__(self):
            super().__init__(None)
            self.calls = []

        def readBureau(self, selected):
            self.calls.append('bureau')
            return bureau.loc[bureau['SK_ID_CURR'].isin(selected)].copy()

        def readCard(self, selected):
            self.calls.append('card')
            return cards.loc[cards['SK_ID_CURR'].isin(selected)].copy()

        def readPayments(self, selected):
            self.calls.append('payment')
            return payments.loc[payments['SK_ID_CURR'].isin(selected)].copy()

        def readMonthly(self, selected, source, months=12):
            self.calls.append('monthly')
            return monthly.loc[monthly['SK_ID_CURR'].isin(selected)].copy()

    return profiles, FixturePortfolio()


def render_context(address, include_history=True, module=views):
    profiles, portfolio = portfolio_fixture()
    with app.test_request_context(address), patch.object(runtime, 'get_profiles', return_value=profiles), \
            patch.object(runtime, 'get_db', return_value=None), \
            patch.object(module, 'CreditRiskPortfolio', return_value=portfolio):
        return module.portfolio_context(include_history), portfolio.calls


def test_context_keeps_report_population_and_query_order():
    context, calls = render_context('/diagnostics?income=Working')
    assert calls == ['bureau', 'card', 'payment']
    assert list(context['profiles']['source_application_id']) == [1, 2, 3]
    assert context['finance']['debt'] == 300
    assert context['finance']['overdue'] == 20
    assert context['payment_report']['rate'] == 1
    assert context['work_summary']['total'] == 3


def test_filters_and_drillthrough_keep_their_population_without_reloading_history():
    context, calls = render_context('/diagnostics?financial_filter=overdue')
    assert calls == ['bureau', 'card', 'payment']
    assert list(context['profiles']['source_application_id']) == [2, 3, 4, 5]
    assert context['finance']['debt'] == 400
    selected, columns, unit = select_chart_records(context, 'score', '50.0% – 100.0%', .15)
    assert list(selected['SK_ID_CURR']) == [5]
    assert unit == 'hồ sơ' and 'score' in columns


def test_score_upper_bound_includes_one_and_unknown_drill_kind_keeps_error():
    context, _ = render_context('/diagnostics')
    selected, _, _ = select_chart_records(context, 'score', '50.0% – 100.0%', .15)
    assert list(selected['SK_ID_CURR']) == [5, 6]
    with pytest.raises(ValueError, match='Loại phân tích không hợp lệ'):
        select_chart_records(context, 'invalid', '', .15)


def test_history_drillthrough_keeps_month_direction_and_period_units():
    context, _ = render_context('/diagnostics')
    periods, _, unit = select_chart_records(context, 'payment', 'Trả đủ sau hạn', .15)
    assert list(periods['SK_ID_CURR']) == [4, 5, 6]
    assert unit == 'kỳ / phiên bản'
    month, _, unit = select_chart_records(context, 'month', '-1', .15)
    assert len(month) == 6 and unit == 'khoản–tháng đủ trạng thái'
    transitions, _, unit = select_chart_records(context, 'transition', '0:1', .15)
    assert len(transitions) == 6 and unit == 'cặp chuyển tháng'
    with pytest.raises(ValueError, match='trước mốc nộp đơn'):
        select_chart_records(context, 'month', '0', .15)
