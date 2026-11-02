"""Prepare financial research snapshots and comparison values."""
from functools import lru_cache
from decimal import Decimal
from flask import redirect, request, url_for
from models.CreditRiskStatistic import CreditRiskStatistic
from web.report_cache import read_research_cache
from web.financial import DIMENSIONS, RATIOS, HISTORY_SOURCES, financial_summary, financial_groups, segment_labels, bureau_summary, portfolio_figures, overview_figures
from web.kpi_dimensions import financial_mini
from web import runtime
from web import request_helpers as query


@lru_cache(maxsize=1)
def research_financial_snapshot(version):
    # Research tables are versioned snapshots; callers only filter copies.
    return read_research_cache(runtime.REPORT_CACHE_DIR,
        f'{runtime.REPORT_QUERY_VERSION}:{version}:portfolio',
        lambda: runtime.get_data().getFinancialPortfolio('research'))



@lru_cache(maxsize=2)
def research_bureau_snapshot(version, currency, credit_status):
    return read_research_cache(runtime.REPORT_CACHE_DIR,
        f'{runtime.REPORT_QUERY_VERSION}:{version}:bureau:{currency}:{credit_status}',
        lambda: runtime.get_data().getFinancialBureau('research', currency, credit_status))



@lru_cache(maxsize=1)
def research_previous_snapshot(version):
    return read_research_cache(runtime.REPORT_CACHE_DIR,
        f'{runtime.REPORT_QUERY_VERSION}:{version}:previous',
        lambda: runtime.get_data().getFinancialPrevious('research'))



@lru_cache(maxsize=4)
def managed_previous_snapshot(version, source_ids):
    # Only immutable source history is cached; notes, scores and statuses stay fresh.
    return runtime.get_data().getFinancialPrevious('managed')



def financial_data():
    scope = request.args.get('data_scope', 'research')
    if scope not in ['research', 'managed']:
        raise ValueError('Phạm vi tài chính không hợp lệ.')
    version = runtime.get_db().queryDataset("SELECT value FROM dataset_metadata WHERE name='data_version'").iloc[0]['value']
    if scope == 'research':
        reference = research_financial_snapshot(version)
    else:
        reference = runtime.get_data().getFinancialPortfolio('managed')
    filters = query.read_cohort_filters()
    data = CreditRiskStatistic.applyCohortFilters(reference, filters)
    dimension = request.args.get('segment', 'credit_band')
    if dimension not in DIMENSIONS:
        raise ValueError('Chiều phân tích không hợp lệ.')
    selected = request.args.get('finance_group', '')
    if selected:
        data = data.loc[segment_labels(data, dimension) == selected].copy()
    return scope, version, reference, data, filters, dimension, selected



def financial_history_context(scope, version, reference, data, currency, credit_status):
    """Chỉ tải phần lịch sử tổng hợp khi trang có hiển thị phần này."""
    if scope == 'research':
        bureau = research_bureau_snapshot(version, currency, credit_status)
        previous = research_previous_snapshot(version)
    else:
        bureau = runtime.get_data().getFinancialBureau(scope, currency, credit_status)
        previous = managed_previous_snapshot(version, tuple(int(i) for i in reference['source_application_id']))
    ids = data['source_application_id']
    bureau = bureau.loc[bureau['source_application_id'].isin(ids)]
    previous = previous.loc[previous['source_application_id'].isin(ids)]
    if (previous['previous_n'] != previous['unique_n']).any():
        raise ValueError('Đơn vay trước bị trùng trong nguồn báo cáo.')
    known_previous = int(previous['known_n'].sum())
    positive_previous = int(previous['refused_n'].sum())
    known_profiles = (previous['refused_n'] > 0) | (previous['known_n'] == previous['previous_n'])
    support = {'previous_n': int(previous['previous_n'].sum()),
        'refused_rate': positive_previous / known_previous if known_previous else None,
        'refused_profile_rate': float((previous.loc[known_profiles, 'refused_n'] > 0).mean()) if known_profiles.any() else None,
        'previous_profile_n': int(known_profiles.sum()),
        'previous_unknown_n': int((previous['previous_n'] - previous['known_n']).sum())}
    return bureau_summary(bureau), support



def _financial_options():
    ratio = request.args.get('ratio', 'credit_income')
    if ratio not in RATIOS:
        raise ValueError('Tỷ số tài chính không hợp lệ.')
    history_metric = request.args.get('history_metric', 'installments')
    if history_metric not in HISTORY_SOURCES:
        raise ValueError('Nguồn đối chiếu lịch sử không hợp lệ.')
    currency = request.args.get('currency', 'currency 1')
    credit_status = request.args.get('credit_status', 'Active')
    if credit_status not in runtime.CREDIT_STATES or currency not in ['currency 1', 'currency 2', 'currency 3', 'currency 4']:
        raise ValueError('Điều kiện bureau không hợp lệ.')
    return ratio, history_metric, currency, credit_status


def _financial_kpis(data, scope, summary, baseline, filtered, dimension, overview):
    keys = (['credit', 'rate', 'credit_share', 'credit_income', 'annuity_income'] if scope == 'research'
            else ['credit', 'median_credit', 'credit_income', 'annuity_income', 'credit_goods'])
    labels = {'credit': 'Tổng giá trị khoản vay', 'rate': 'Tỷ lệ khó khăn thanh toán',
        'credit_share': 'Tỷ trọng tín dụng khó khăn thanh toán', 'median_credit': 'Giá trị khoản vay trung vị',
        'credit_income': 'Hệ số đòn bẩy khoản vay', 'annuity_income': 'Tỷ lệ niên kim trên thu nhập',
        'credit_goods': 'Tỷ lệ tài trợ hàng hóa'}
    eligible = {'credit': 'credit_n', 'median_credit': 'credit_n', 'rate': 'label_n',
        'credit_share': 'label_credit_n', 'credit_income': 'credit_income_n',
        'annuity_income': 'annuity_income_n', 'credit_goods': 'credit_goods_n'}
    kpis = []
    for key in keys:
        value, base = summary.get(key), baseline.get(key)
        percent = key in ['rate', 'credit_share', 'annuity_income', 'credit_goods']
        delta = None
        if filtered and value is not None and base is not None:
            delta = (value - base) * 100 if percent else ((value / base - 1) * 100 if base else None)
        if percent:
            kind = 'percent'
        elif key in ['credit', 'median_credit']:
            kind = 'amount'
        else:
            kind = 'times'
        kpis.append({'key': key, 'label': labels[key], 'value': value, 'reference': base,
            'kind': kind,
            'n': summary.get(eligible[key], 0), 'delta': delta, 'pp': percent})
        kpis[-1]['mini'] = financial_mini(data, key, eligible[key], dimension if not overview else None)
    return kpis


def _active_financial_filters(filters, dimension, selected):
    active_filters = []
    for key, label, options in [('product', 'Khoản vay', runtime.PRODUCTS),
                                ('income', 'Thu nhập', runtime.INCOME_TYPES),
                                ('availability', 'Dữ liệu', runtime.AVAILABILITY)]:
        if filters.get(key):
            active_filters.append({'label': f'{label}: {options[filters[key]]}',
                'url': query.cohort_url(request.endpoint, **{key: None})})
    for key, label in [('amount_min', 'Khoản vay từ'), ('amount_max', 'Khoản vay đến'),
                       ('age_min', 'Tuổi từ'), ('age_max', 'Tuổi đến')]:
        value = filters.get(key)
        if value is not None:
            text = format(Decimal(str(value)), ',f')
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
            text = text.replace(',', '_').replace('.', ',').replace('_', '.')
            active_filters.append({'label': f'{label}: {text}',
                'url': query.cohort_url(request.endpoint, **{key: None})})
    if selected:
        active_filters.append({'label': f'{DIMENSIONS[dimension]}: {selected}',
            'url': query.cohort_url(request.endpoint, finance_group=None)})
    return active_filters


def financial_context(overview=False):
    scope, version, reference, data, filters, dimension, selected = financial_data()
    ratio, history_metric, currency, credit_status = _financial_options()
    bureau_report, support = (financial_history_context(scope, version, reference, data, currency, credit_status)
                              if overview else (None, None))
    summary = financial_summary(data)
    baseline = summary if len(data) == len(reference) else financial_summary(reference)
    filtered = len(data) != len(reference)
    kpis = _financial_kpis(data, scope, summary, baseline, filtered, dimension, overview)
    groups = financial_groups(data, dimension) if not overview else []
    links = {row['label']: query.cohort_url('risk_dashboard', segment=dimension, finance_group=row['label']) for row in groups}
    for row in groups:
        row['url'] = query.cohort_url('financial_records', segment=dimension, finance_group=row['label'], page=None)
    active_filters = _active_financial_filters(filters, dimension, selected)
    clear_filters = {key: None for key in runtime.COHORT_FIELDS}
    return {'data_scope': scope, 'data_version': version, 'cohort_filters': filters,
        'active_financial_filters': active_filters,
        'clear_financial_filters_url': query.cohort_url(request.endpoint, **clear_filters, finance_group=None),
        'financial_summary': summary, 'reference_n': len(reference), 'kpis': kpis,
        'financial_bureau': bureau_report, 'financial_currency': currency,
        'credit_status': credit_status, 'financial_support': support,
        'dimension': dimension, 'dimension_options': DIMENSIONS, 'selected_group': selected,
        'ratio': ratio, 'ratio_options': RATIOS, 'financial_groups': groups,
        'financial_panels': (overview_figures(data, scope, ratio) if overview else
            portfolio_figures(data, groups, scope, dimension, ratio, links, baseline, history_metric)),
        'history_metric': history_metric, 'history_options': HISTORY_SOURCES,
        'visible_group_n': min(8, len([row for row in groups if row['n'] >= 5]) or len(groups)),
        'overview': overview, 'is_filtered': filtered}



def redirect_old_financial_scope():
    if 'data_scope' not in request.args:
        return None
    scope = request.args.get('data_scope')
    if scope not in ['research', 'managed']:
        raise ValueError('Phạm vi tài chính không hợp lệ.')
    params = request.args.to_dict()
    params.pop('data_scope')
    if scope == 'managed':
        params.pop('finance_group', None)
    return redirect(url_for(request.endpoint, **params))

