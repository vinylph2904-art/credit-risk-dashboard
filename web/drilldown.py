"""Chọn đúng các quan sát tạo nên một điểm trên biểu đồ."""
import pandas as pd

from web.analytics import filter_score_range, segment_values, SEGMENTS


def _select_dpd(values, value):
    data = values['finance']['data']
    labels = [row['label'] for row in values['finance']['buckets']]
    if value not in labels:
        raise ValueError('Nhóm DPD không hợp lệ.')
    data = data.loc[data['dpd_bucket'] == value].copy()
    columns = {'SK_ID_BUREAU': 'Khoản bureau', 'dpd': 'DPD', 'debt': 'Dư nợ', 'overdue': 'Tiền quá hạn'}
    unit = 'khoản bureau'
    return data, columns, unit


def _select_payment(values, value, portfolio, ids):
    report = values.get('payment_report')
    if report is None:
        report = portfolio.paymentReport(portfolio.readPayments(ids))
    if value not in [row['label'] for row in report['distribution']]:
        raise ValueError('Kết quả kỳ trả không hợp lệ.')
    data = report['data'].loc[report['data']['status'] == value].copy()
    columns = {'SK_ID_PREV': 'Khoản', 'NUM_INSTALMENT_NUMBER': 'Kỳ',
               'NUM_INSTALMENT_VERSION': 'Phiên bản', 'scheduled': 'Theo lịch',
               'paid': 'Đã trả quan sát', 'status': 'Kết quả'}
    unit = 'kỳ / phiên bản'
    return data, columns, unit


def _select_card(values, value, portfolio, ids):
    report = values.get('card_report')
    if report is None:
        report = portfolio.cardReport(portfolio.readCard(ids))
    labels = [row['label'] for row in report['distribution']]
    if value not in labels:
        raise ValueError('Nhóm utilization không hợp lệ.')
    data = report['data'].copy()
    bins = pd.cut(data['utilization'], [0, .25, .5, .75, 1, float('inf')],
                  labels=labels, include_lowest=True)
    data = data.loc[bins == value].copy()
    columns = {'SK_ID_PREV': 'Thẻ', 'MONTHS_BALANCE': 'Tháng',
               'AMT_BALANCE': 'Số dư', 'AMT_CREDIT_LIMIT_ACTUAL': 'Hạn mức',
               'utilization': 'Utilization'}
    unit = 'thẻ'
    return data, columns, unit


def _select_history(values, kind, value, portfolio, ids):
    source = values['history_source']
    report = portfolio.monthlyReport(portfolio.readMonthly(ids, source, values['months']), source)
    if kind == 'month':
        try:
            month = int(value)
        except ValueError:
            raise ValueError('Tháng không hợp lệ.') from None
        if month >= 0:
            raise ValueError('Chỉ xem lịch sử trước mốc nộp đơn.')
        same_month = report['data']['MONTHS_BALANCE'] == month
        known_status = report['data']['known']
        data = report['data'].loc[same_month & known_status].copy()
        columns = {'loan_id': 'Khoản', 'MONTHS_BALANCE': 'Tháng',
                   'known': 'Đủ trạng thái', 'is_overdue': 'Có quá hạn'}
        if source == 'bureau':
            columns['state'] = 'Trạng thái nguồn'
        else:
            columns['dpd'] = 'DPD'
        unit = 'khoản–tháng đủ trạng thái'
    else:
        if source != 'bureau':
            raise ValueError('Chuyển trạng thái chỉ áp dụng nguồn bureau.')
        parts = value.split(':')
        if len(parts) != 2 or any(state not in report['states'] for state in parts):
            raise ValueError('Cặp chuyển trạng thái không hợp lệ.')
        pairs = report['pairs']
        data = pairs.loc[(pairs['from_state'] == parts[0]) & (pairs['to_state'] == parts[1])].copy()
        columns = {'loan_id': 'Khoản', 'from_state': 'Từ trạng thái', 'to_state': 'Sang trạng thái'}
        unit = 'cặp chuyển tháng'
    return data, columns, unit


def _select_risk(kind, value, profiles):
    parts = value.split(':', 1)
    if len(parts) != 2:
        raise ValueError('Lựa chọn rủi ro không hợp lệ.')
    if kind == 'risk_bin':
        data = filter_score_range(profiles, *parts)
    else:
        key, label = parts
        if key not in SEGMENTS:
            raise ValueError('Chiều phân khúc không hợp lệ.')
        if label == '__MISSING__':
            label = 'Chưa có thông tin'
        data = profiles.loc[segment_values(profiles, key).eq(label)].copy()
    data['SK_ID_CURR'] = data['source_application_id']
    columns = {'score': 'Điểm rủi ro', 'AMT_CREDIT': 'Giá trị khoản vay',
               'NAME_CONTRACT_TYPE': 'Loại vay', 'alert': 'Cảnh báo', 'review_status': 'Rà soát'}
    unit = 'hồ sơ'
    return data, columns, unit


def _select_score(value, threshold, profiles):
    edges = sorted(set([0, .05, .10, threshold, .25, .50, 1.0]))
    selected_range = None
    for low, high in zip(edges[:-1], edges[1:]):
        if value == f'{low:.1%} – {high:.1%}':
            selected_range = (low, high)
    if selected_range is None:
        raise ValueError('Khoảng điểm không hợp lệ.')
    low, high = selected_range
    matches = (profiles['score'] >= low) & (profiles['score'] < high)
    if high == 1:
        matches = (profiles['score'] >= low) & (profiles['score'] <= high)
    data = profiles.loc[matches].copy()
    data['SK_ID_CURR'] = data['source_application_id']
    columns = {'score': 'Điểm dự báo', 'alert': 'Cảnh báo', 'review_status': 'Trạng thái rà soát'}
    unit = 'hồ sơ'
    return data, columns, unit


def select_chart_records(values, kind, value, threshold):
    portfolio = values['portfolio']
    profiles = values['profiles']
    ids = profiles['source_application_id'].tolist()
    if kind == 'dpd':
        return _select_dpd(values, value)
    elif kind == 'payment':
        return _select_payment(values, value, portfolio, ids)
    elif kind == 'card':
        return _select_card(values, value, portfolio, ids)
    elif kind in ['month', 'transition']:
        return _select_history(values, kind, value, portfolio, ids)
    elif kind in ['risk_bin', 'risk_segment']:
        return _select_risk(kind, value, profiles)
    elif kind == 'score':
        return _select_score(value, threshold, profiles)
    raise ValueError('Loại phân tích không hợp lệ.')
