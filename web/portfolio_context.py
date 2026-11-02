"""Prepare managed portfolio, workflow and risk dashboard values."""
from flask import request
from models.CreditRiskStatistic import CreditRiskStatistic
from models.CreditRiskPortfolio import CreditRiskPortfolio
from web.drilldown import select_chart_records
from web.analytics import SEGMENTS, SEGMENT_ORDERS, ordered_segments, pending_priority, risk_bins, segment_report
from web import runtime
from web import request_helpers as query


def prediction_context(selected_profiles=None):
    if any(request.args.get(name) for name in ['status', 'alert', 'unassigned', 'archived']):
        raise ValueError('Lọc trạng thái, cảnh báo và phân công tại Danh sách hồ sơ. Tổng quan dùng bộ lọc phân khúc.')
    filters = query.read_cohort_filters()
    base = runtime.get_profiles()
    baseline = CreditRiskStatistic(base, runtime.model.threshold).summary()
    baseline_amounts = CreditRiskStatistic(base, runtime.model.threshold).creditAmounts()
    profiles = CreditRiskStatistic.applyCohortFilters(base, filters) if selected_profiles is None else selected_profiles
    stats = CreditRiskStatistic(profiles, runtime.model.threshold)
    summary = stats.summary()
    queue = profiles.loc[(profiles['alert'] == 1) & (profiles['review_status'] != 'reviewed')]
    queue = queue.sort_values(['score', 'source_application_id'], ascending=[False, True]).head(10)
    product_sizes = stats.scored.groupby('NAME_CONTRACT_TYPE').size()
    income_groups = stats.groupRisk('NAME_INCOME_TYPE', baseline_alert_share=baseline['alert_share'])
    focus = max(income_groups, key=lambda group: (group['pending_alert_n'], group['alert_n'], group['n'])) if income_groups else None
    if focus and not focus['alert_n']:
        focus = None
    chips = []
    labels = {'product': 'Loại vay', 'income': 'Nguồn thu', 'amount_min': 'Số tiền từ',
              'amount_max': 'Số tiền đến', 'age_min': 'Tuổi từ', 'age_max': 'Tuổi đến',
              'availability': 'Dữ liệu'}
    for name, value in filters.items():
        if value is None or value == '':
            continue
        display = runtime.PRODUCTS.get(value, value) if name == 'product' else value
        if name == 'income':
            display = runtime.INCOME_TYPES[value]
        elif name == 'availability':
            display = runtime.AVAILABILITY[value]
        chips.append({'label': labels[name], 'value': display,
                      'remove_url': query.cohort_url('dashboard', **{name: None})})
    category_filters = dict(filters, amount_min=None, amount_max=None, age_min=None, age_max=None)
    before_ranges = CreditRiskStatistic.applyCohortFilters(base, category_filters)
    delta = summary['alert_share'] - baseline['alert_share'] if summary['scored_n'] else None
    return {'summary': summary, 'baseline': baseline, 'baseline_amounts': baseline_amounts,
            'filters': filters, 'filter_chips': chips,
            'delta_alert_share': delta, 'distribution': stats.distribution(),
            'product_groups': stats.groupRisk('NAME_CONTRACT_TYPE', baseline_alert_share=baseline['alert_share']),
            'income_groups': income_groups, 'focus': focus, 'queue': runtime.records(queue),
            'workflow': stats.alertWorkflow(), 'amounts': stats.creditAmounts(),
            'readiness': stats.dataReadiness(), 'diagnostic': stats.diagnostic(),
            'small_product_n': int(product_sizes.loc[product_sizes < 5].sum()),
            'range_missing': {'amount': int(before_ranges['AMT_CREDIT'].isna().sum()),
                              'age': int(before_ranges['AGE_YEARS'].isna().sum())}}


def _financial_filter_ids(financial_filter, finance, portfolio, ids, source, months,
                          card_data, payment_data):
    loans = finance['data']
    if financial_filter == 'money':
        return loans.loc[loans['money_valid'], 'SK_ID_CURR']
    if financial_filter == 'overdue_money':
        return loans.loc[loans['money_valid'] & (loans['overdue'] > 0), 'SK_ID_CURR']
    if financial_filter == 'overdue':
        return loans.loc[loans['is_overdue'], 'SK_ID_CURR']
    if financial_filter == 'dpd90':
        return loans.loc[loans['dpd_valid'] & (loans['dpd'] > 90), 'SK_ID_CURR']
    if financial_filter == 'exceptions':
        return loans.loc[loans['needs_check'], 'SK_ID_CURR']
    if financial_filter == 'card_over':
        card = portfolio.cardReport(card_data)['data']
        return card.loc[card['utilization'] > 1, 'SK_ID_CURR']
    if financial_filter == 'payment_late':
        periods = portfolio.paymentReport(payment_data)['data']
        return periods.loc[periods['status'] == 'Trả đủ sau hạn', 'SK_ID_CURR']
    if source != 'bureau':
        raise ValueError('Ma trận trạng thái dùng nguồn bureau.')
    from_state = request.args.get('from_state', '')
    to_state = request.args.get('to_state', '')
    states = ['0', '1', '2', '3', '4', '5', 'C']
    if from_state not in states or to_state not in states:
        raise ValueError('Cặp trạng thái không hợp lệ.')
    monthly = portfolio.monthlyReport(portfolio.readMonthly(ids, source, months), source)
    pairs = monthly['pairs']
    return pairs.loc[(pairs['from_state'] == from_state) & (pairs['to_state'] == to_state), 'SK_ID_CURR']


def _workload_summary(profiles):
    work = profiles.copy()
    work['is_new'] = work['review_status'] == 'new'
    work['is_reviewing'] = work['review_status'] == 'in_review'
    work['is_reviewed'] = work['review_status'] == 'reviewed'
    work['is_pending_alert'] = (work['alert'] == 1) & ~work['is_reviewed']
    work['assignee_label'] = work['assignee'].str.strip().replace('', 'Chưa phân công')
    workload = work.groupby('assignee_label').agg(
        total=('profile_id', 'size'), new_n=('is_new', 'sum'), reviewing_n=('is_reviewing', 'sum'),
        reviewed_n=('is_reviewed', 'sum'), pending_alert_n=('is_pending_alert', 'sum')).reset_index()
    total = len(profiles)
    reviewed_n = int(work['is_reviewed'].sum())
    workflow = {'total': total, 'new_n': int(work['is_new'].sum()),
                'reviewing_n': int(work['is_reviewing'].sum()), 'reviewed_n': reviewed_n,
                'pending_n': total - reviewed_n, 'reviewed_share': reviewed_n / total if total else None,
                'unassigned_n': int(((work['assignee'].str.strip() == '') & ~work['is_reviewed']).sum()),
                'scored_n': int(work['score'].notna().sum()), 'alert_n': int((work['alert'] == 1).sum()),
                'unscored_n': int(work['score'].isna().sum())}
    return runtime.records(workload), workflow



def _portfolio_options(bureau):
    currencies = sorted(bureau['CREDIT_CURRENCY'].dropna().unique().tolist())
    default_currency = 'currency 1' if 'currency 1' in currencies else (currencies[0] if currencies else '')
    currency = request.args.get('currency') or default_currency
    if currency and currency not in currencies:
        # Lựa chọn tiền đã giữ từ phân khúc khác vẫn là bộ lọc hợp lệ, có thể không có khoản.
        if currency not in ['currency 1', 'currency 2', 'currency 3', 'currency 4']:
            raise ValueError('Mã tiền không hợp lệ.')
        currencies = sorted(set(currencies + [currency]))
    credit_status = request.args.get('credit_status', 'Active')
    if credit_status not in runtime.CREDIT_STATES:
        raise ValueError('Trạng thái khoản bureau không hợp lệ.')
    source = request.args.get('source', 'bureau')
    if source not in ['bureau', 'pos', 'card']:
        raise ValueError('Nguồn lịch sử không hợp lệ.')
    month_value = request.args.get('months', '12')
    if month_value not in ['3', '6', '12', '24', 'all']:
        raise ValueError('Cửa sổ lịch sử không hợp lệ.')
    months = None if month_value == 'all' else int(month_value)
    breakdown = request.args.get('breakdown', 'income')
    if breakdown not in ['income', 'product']:
        raise ValueError('Chiều phân khúc không hợp lệ.')
    group_column = 'NAME_INCOME_TYPE' if breakdown == 'income' else 'NAME_CONTRACT_TYPE'
    return currencies, currency, credit_status, source, month_value, months, breakdown, group_column


def _finance_group_links(finance, breakdown):
    finance_groups = runtime.records(finance['groups'])
    labels = runtime.INCOME_TYPES if breakdown == 'income' else runtime.PRODUCTS
    for row in finance_groups:
        row['label'] = labels.get(row['segment'], row['segment'] or 'Chưa rõ')
        row['url'] = query.cohort_url('applications', **{breakdown: row['segment']}) if row['segment'] in labels else None
        row['filter_url'] = query.filter_url(breakdown, row['segment']) if row['segment'] in labels else None
    return finance_groups


def _selection_chips(filters):
    chips = []
    filter_labels = {'product': 'Loại vay', 'income': 'Nguồn thu', 'amount_min': 'Tiền từ',
                     'amount_max': 'Tiền đến', 'age_min': 'Tuổi từ', 'age_max': 'Tuổi đến', 'availability': 'Dữ liệu'}
    for name, value in filters.items():
        if value is None or value == '':
            continue
        label = runtime.PRODUCTS.get(value, value) if name == 'product' else value
        if name == 'income':
            label = runtime.INCOME_TYPES[value]
        if name == 'availability':
            label = runtime.AVAILABILITY[value]
        chips.append({'label': filter_labels[name], 'value': label,
                      'remove_url': query.cohort_url(request.endpoint, **{name: None})})
    return chips


def _finance_focus(finance, finance_groups, group_column):
    finance_focus = None
    if finance['overdue'] and finance['debt']:
        candidates = [row for row in finance_groups if row['overdue'] is not None and row['overdue'] > 0]
        if candidates:
            finance_focus = max(candidates, key=lambda row: row['overdue'])
            finance_focus = dict(finance_focus, debt_share=finance_focus['debt'] / finance['debt'],
                                 overdue_amount_share=finance_focus['overdue'] / finance['overdue'])
            loans = finance['data']
            in_segment = loans[group_column] == finance_focus['segment']
            positive_overdue = loans['money_valid'] & (loans['overdue'] > 0)
            finance_focus['overdue_money_n'] = int((in_segment & positive_overdue).sum())
    return finance_focus


def portfolio_context(include_history=False, include_archived=False):
    filters = query.read_cohort_filters()
    profiles = CreditRiskStatistic.applyCohortFilters(runtime.get_profiles(include_archived), filters)
    portfolio = CreditRiskPortfolio(runtime.get_db())
    ids = profiles['source_application_id'].tolist()
    bureau = portfolio.readBureau(ids)
    (currencies, currency, credit_status, source, month_value, months,
     breakdown, group_column) = _portfolio_options(bureau)
    finance = portfolio.bureauReport(bureau, profiles, currency, credit_status, group_column)
    financial_filter = request.args.get('financial_filter', '')
    if financial_filter and financial_filter not in runtime.FINANCIAL_FILTERS:
        raise ValueError('Bộ lọc tài chính không hợp lệ.')
    card_data = None
    payment_data = None
    monthly = None
    if include_history or financial_filter == 'card_over':
        card_data = portfolio.readCard(ids)
    if include_history or financial_filter == 'payment_late':
        payment_data = portfolio.readPayments(ids)
    if financial_filter:
        chosen_ids = _financial_filter_ids(financial_filter, finance, portfolio, ids, source,
                                           months, card_data, payment_data)
        profiles = profiles.loc[profiles['source_application_id'].isin(chosen_ids)].copy()
        ids = profiles['source_application_id'].tolist()
        finance = portfolio.bureauReport(bureau, profiles, currency, credit_status, group_column)
    card = None
    payments = None
    if card_data is not None:
        card = portfolio.cardReport(card_data.loc[card_data['SK_ID_CURR'].isin(ids)])
    if payment_data is not None:
        payments = portfolio.paymentReport(payment_data.loc[payment_data['SK_ID_CURR'].isin(ids)])
    drill_kind = request.args.get('drill_kind', '')
    if drill_kind:
        selected, _, _ = select_chart_records(
            {'profiles': profiles, 'portfolio': portfolio, 'finance': finance,
             'card_report': card, 'payment_report': payments, 'history_source': source, 'months': months},
            drill_kind, request.args.get('drill_value', ''), runtime.model.threshold)
        profiles = profiles.loc[profiles['source_application_id'].isin(selected['SK_ID_CURR'])].copy()
        finance = portfolio.bureauReport(bureau, profiles, currency, credit_status, group_column)
        if card_data is not None:
            card = portfolio.cardReport(card_data.loc[card_data['SK_ID_CURR'].isin(profiles['source_application_id'])])
        if payment_data is not None:
            payments = portfolio.paymentReport(payment_data.loc[payment_data['SK_ID_CURR'].isin(profiles['source_application_id'])])
    enriched = profiles.merge(finance['by_profile'], left_on='source_application_id', right_index=True,
                              how='left', validate='one_to_one')
    workload, workflow = _workload_summary(profiles)
    finance_groups = _finance_group_links(finance, breakdown)
    chips = _selection_chips(filters)
    finance_focus = _finance_focus(finance, finance_groups, group_column)
    return {'profiles': enriched, 'portfolio': portfolio, 'finance': finance,
            'finance_groups': finance_groups, 'breakdown': breakdown, 'selection_chips': chips,
            'finance_focus': finance_focus,
            'workload': workload,
            'work_summary': workflow, 'cohort_filters': filters, 'filters': filters,
            'currency_options': currencies, 'financial_currency': currency, 'credit_status': credit_status,
            'financial_filter': financial_filter, 'history_source': source, 'history_months': month_value,
            'months': months, 'card_report': card, 'payment_report': payments}



def risk_analytics_context():
    values = portfolio_context()
    predictions = prediction_context(values['profiles'])
    predictions.pop('filters', None)
    values.update(predictions)
    key = request.args.get('segment', 'product')
    metric = request.args.get('segment_metric', 'alert_share')
    chart_order = request.args.get('segment_order', 'alerted_credit')
    table_order = request.args.get('segment_sort', 'alerted_credit')
    direction = request.args.get('segment_direction', 'desc')
    if key not in SEGMENTS or metric not in ['alert_share', 'mean_score']:
        raise ValueError('Lựa chọn phân tích phân khúc không hợp lệ.')
    if chart_order not in SEGMENT_ORDERS or table_order not in SEGMENT_ORDERS or direction not in ['asc','desc']:
        raise ValueError('Cách sắp xếp phân khúc không hợp lệ.')
    groups = segment_report(values['profiles'], key)
    for row in groups:
        selection = f"{key}:{row['label']}"
        selected = request.args.get('drill_kind') == 'risk_segment' and request.args.get('drill_value') == selection
        row['filter_url'] = query.cohort_url(request.endpoint,
            drill_kind=None if selected else 'risk_segment', drill_value=None if selected else selection)
        row['queue_url'] = query.cohort_url('applications', drill_kind='risk_segment', drill_value=selection)
    eligible = ordered_segments([row for row in groups if row['n'] >= 5], chart_order)[:6]
    profiles = values['profiles']
    scored = profiles.loc[profiles['score'].notna()]
    priority = pending_priority(profiles)
    usable_bureau = profiles['HAS_USABLE_BUREAU'].eq(1)
    overdue_signal = usable_bureau & (profiles['BUR_OVERDUE_DAYS_MAX'].gt(0) | profiles['BUR_C1_OVERDUE_MAX'].gt(0))
    summary_groups = ordered_segments([row for row in segment_report(profiles, 'credit_band')
        if row['n'] >= 5 and row['alerted_credit'] is not None and row['alerted_credit'] > 0], 'alerted_credit')[:3]
    bins = risk_bins(scored['score'], runtime.model.threshold)
    values.update(segment_options=SEGMENTS, segment_key=key, segment_metric=metric,
        segment_rows=ordered_segments(groups, table_order, direction=='desc'),
        segment_order=chart_order, segment_sort=table_order, segment_direction=direction,
        segment_order_options=SEGMENT_ORDERS, chart_group_n=len(eligible), summary_groups=summary_groups,
        small_segment_n=sum(row['n'] for row in groups if row['n'] < 5),
        priority_profiles=runtime.records(priority), priority_total=values['workflow']['pending_n'],
        latest_scored_at=scored['scored_at'].max() if len(scored) else None,
        history_signals={'bureau_n': int(usable_bureau.sum()), 'overdue_n': int(overdue_signal.sum()),
                         'no_bureau_n': int(profiles['HAS_USABLE_BUREAU'].eq(0).sum()),
                         'installment_n': int((profiles['HAS_USABLE_INSTALLMENTS'].eq(1)
                            & profiles['INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE'].gt(0)).sum())},
        risk_histogram=runtime.charts.riskHistogram(bins, runtime.model.threshold, 'risk-histogram'),
        segment_chart=runtime.charts.alertSegments(eligible, metric, 'risk-segments'),
        exposure_chart=runtime.charts.applicationExposure(eligible, 'credit-exposure'),
        concentration_chart=runtime.charts.riskConcentration(eligible, 'risk-concentration'),
        overview_exposure=runtime.charts.creditSplit(values['amounts'], 'overview-exposure',
            query.cohort_url('applications',alert='0'),query.cohort_url('applications',alert='1')))
    return values

