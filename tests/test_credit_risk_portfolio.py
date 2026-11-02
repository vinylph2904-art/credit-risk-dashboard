"""Regression cho KPI tài chính mới; không huấn luyện hoặc lựa chọn model."""
import numpy as np
import pandas as pd
import pytest

from models.CreditRiskPortfolio import CreditRiskPortfolio


def profiles():
    return pd.DataFrame([
        [1, 101, 'HC-1', 'Working', 'Cash loans', 'new'],
        [2, 102, 'HC-2', 'Pensioner', 'Cash loans', 'reviewed'],
    ], columns=['source_application_id', 'profile_id', 'case_label',
                'NAME_INCOME_TYPE', 'NAME_CONTRACT_TYPE', 'review_status'])


def bureau_data():
    return pd.DataFrame([
        [1, 11, 'Active', 'currency 1', -100, -1, 5, 100., 10.],
        [1, 12, 'Active', 'currency 1', -100, -1, 0, 200., 0.],
        [2, 13, 'Active', 'currency 1', -100, -1, 40, np.nan, 20.],
        [2, 14, 'Active', 'currency 1', -100, -1, 90, 0., 5.],
        [1, 15, 'Closed', 'currency 1', -100, -1, 100, 500., 30.],
        [1, 16, 'Active', 'currency 2', -100, -1, 5, 50., 2.],
        [1, 17, 'Active', 'currency 1', -100, 1, 5, 999., 50.],
    ], columns=['SK_ID_CURR', 'SK_ID_BUREAU', 'CREDIT_ACTIVE', 'CREDIT_CURRENCY',
                'DAYS_CREDIT', 'DAYS_CREDIT_UPDATE', 'CREDIT_DAY_OVERDUE',
                'AMT_CREDIT_SUM_DEBT', 'AMT_CREDIT_SUM_OVERDUE'])


def test_money_cards_share_population_but_dpd_keeps_own_denominator():
    result = CreditRiskPortfolio.bureauReport(bureau_data(), profiles(), 'currency 1')
    assert result['money_n'] == 2
    assert result['debt'] == 300
    assert result['overdue'] == 10
    assert result['money_share'] == pytest.approx(10 / 300)
    assert result['dpd_n'] == 4
    assert result['overdue_n'] == 3
    assert result['loan_share'] == .75
    assert result['exception_n'] == 1
    assert result['invalid_time_n'] == 1
    assert pd.isna(result['by_profile'].loc[2, 'bureau_debt'])
    assert sum(row['n'] for row in result['buckets']) == result['loans_n']


def test_conflicting_loan_keys_do_not_double_money():
    data = bureau_data()
    duplicate = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match='bureau'):
        CreditRiskPortfolio.bureauReport(duplicate, profiles(), 'currency 1')


def test_currency_empty_scope_is_missing_not_zero():
    result = CreditRiskPortfolio.bureauReport(bureau_data(), profiles(), 'currency 4')
    assert result['debt'] is None
    assert result['overdue'] is None
    assert result['money_share'] is None
    assert result['loan_share'] is None
    assert result['money_n'] == 0


def test_latest_card_snapshot_zero_limit_and_conflict():
    card = pd.DataFrame([
        [1, 11, -2, 200., 100., 0], [1, 11, -1, 50., 100., 0],
        [1, 12, -1, 150., 100., 0], [2, 13, -1, 10., 0., 0],
        [2, 14, -1, 80., 100., 0], [2, 14, -1, 80., 100., 0],
        [2, 15, -2, 30., 100., 0],
        [2, 15, -1, 10., 100., 0], [2, 15, -1, 20., 100., 0],
    ], columns=['SK_ID_CURR', 'SK_ID_PREV', 'MONTHS_BALANCE', 'AMT_BALANCE',
                'AMT_CREDIT_LIMIT_ACTUAL', 'SK_DPD'])
    result = CreditRiskPortfolio.cardReport(card)
    assert result['valid_n'] == 3
    assert result['median'] == .8
    assert result['excluded_n'] == 2
    assert result['ambiguous_n'] == 2
    assert result['distribution'][-1]['n'] == 1
    assert 15 not in result['data']['SK_ID_PREV'].tolist()


def test_partial_payments_and_versions_do_not_fake_on_time():
    payments = pd.DataFrame([
        [1, 11, 1, 1, -10, -12, 100., 50.],
        [1, 11, 1, 1, -10, -10, 100., 50.],
        [1, 11, 1, 1, -10, -2, 100., 10.],
        [1, 11, 1, 2, -10, -15, 100., 30.],
        [1, 11, 1, 2, -10, -5, 100., 70.],
        [1, 11, 1, 3, -10, -15, 100., 20.],
        [1, 11, 1, 4, -10, -15, 100., 100.],
        [1, 11, 2, 4, -10, -15, 120., 120.],
        [1, 11, 1, 5, -10, -15, 100., 10.],
        [1, 11, 1, 5, -10, -14, 120., 10.],
        [1, 11, 1, 6, -10, 1, 100., 100.],
        [1, 11, 1, 7, 1, -1, 100., 100.],
        [1, 11, 1, 8, -10, -15, 100., 0.],
    ], columns=['SK_ID_CURR', 'SK_ID_PREV', 'NUM_INSTALMENT_VERSION', 'NUM_INSTALMENT_NUMBER',
                'DAYS_INSTALMENT', 'DAYS_ENTRY_PAYMENT', 'AMT_INSTALMENT', 'AMT_PAYMENT'])
    result = CreditRiskPortfolio.paymentReport(payments)
    assert result['periods_n'] == 4
    assert result['completed_n'] == 2
    assert result['on_time_n'] == 1
    assert result['rate'] == .5
    assert result['excluded_periods_n'] == 3
    periods = result['data'].set_index('NUM_INSTALMENT_NUMBER')
    assert periods.loc[1, 'completed_at'] == -10
    assert periods.loc[1, 'status'] == 'Trả đủ đúng hạn'
    assert periods.loc[2, 'delay_days'] == 5
    assert periods.loc[3, 'status'] == 'Chưa thấy trả đủ'


def test_transition_time_direction_gaps_closed_and_unknown():
    history = pd.DataFrame([
        [1, 11, -3, '0'], [1, 11, -2, '1'], [1, 11, -1, 'C'],
        [2, 12, -3, '1'], [2, 12, -1, '0'],
        [2, 13, -2, 'X'], [2, 13, -1, '0'],
        [2, 14, -1, '0'], [2, 14, -1, '1'],
    ], columns=['SK_ID_CURR', 'loan_id', 'MONTHS_BALANCE', 'state'])
    result = CreditRiskPortfolio.monthlyReport(history, 'bureau')
    assert result['pair_n'] == 2
    pairs = list(zip(result['pairs']['from_state'], result['pairs']['to_state']))
    assert pairs == [('0', '1'), ('1', 'C')]
    assert result['ambiguous_n'] == 2
    assert result['monthly'].iloc[-1]['known_n'] == 2


def test_empty_input_reports():
    class NoQuery:
        def queryDataset(self, *args):
            raise AssertionError('Empty cohort should not query a source table')
    portfolio = CreditRiskPortfolio(NoQuery())
    assert portfolio.bureauReport(portfolio.readBureau([]), profiles(), '')['debt'] is None
    assert portfolio.cardReport(portfolio.readCard([]))['median'] is None
    assert portfolio.paymentReport(portfolio.readPayments([]))['rate'] is None
    for source in ['bureau', 'pos', 'card']:
        assert portfolio.monthlyReport(portfolio.readMonthly([], source), source)['rows_n'] == 0
