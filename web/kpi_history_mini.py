"""Categorical mini charts using the same cleaned rows as history KPIs."""
from web.kpi_dimensions import mini_points
from web.financial import segment_labels

AGE_LABELS = ['Dưới 30', '30–39', '40–49', '50–59', 'Từ 60']


def _profile_groups(profiles, dimension):
    bands = segment_labels(profiles, dimension)
    return [(str(label), set(rows['source_application_id']), None)
            for label, rows in profiles.groupby(bands, observed=True, sort=True)]


def _bureau_groups(data):
    types = data['CREDIT_TYPE'].fillna('Chưa có thông tin').replace({
        'Consumer credit': 'Vay tiêu dùng', 'Credit card': 'Thẻ tín dụng',
        'Mortgage': 'Vay thế chấp', 'Car loan': 'Vay mua xe',
        'Microloan': 'Khoản vay nhỏ', 'Other': 'Loại khác'})
    return [(str(label), set(), rows) for label, rows in data.groupby(types, sort=True)]


def _bureau_value(rows, key):
    money = rows.loc[rows['money_valid']]
    known = rows.loc[rows['dpd_valid']]
    if key in ['debt', 'overdue']:
        return money[key].sum(), len(money)
    if key == 'money_share':
        debt = money['debt'].sum()
        return (money['overdue'].sum() / debt if debt > 0 else None), len(money)
    return known['is_overdue'].mean(), len(known)


def _monthly_profile_count(monthly, ids):
    data = monthly['data']
    return data.loc[data['SK_ID_CURR'].isin(ids), 'SK_ID_CURR'].nunique()


def _payment_tab_value(values, monthly, key, ids):
    if key == 'history_profiles':
        count = _monthly_profile_count(monthly, ids)
        return count, count
    if key in ['completed_periods', 'on_time']:
        periods = values['payment_report']['data']
        completed = periods.loc[periods['SK_ID_CURR'].isin(ids) & periods['status'].isin(
            ['Trả đủ đúng hạn', 'Trả đủ sau hạn'])]
        count = len(completed)
        if key == 'completed_periods':
            return count, count
        return (completed['status'] == 'Trả đủ đúng hạn').mean(), count
    cards = values['card_report']['data']
    valid = cards.loc[cards['SK_ID_CURR'].isin(ids), 'utilization'].dropna()
    return valid.median(), len(valid)


def _chart_kind(key):
    if key in ['debt', 'history_profiles']:
        return 'donut'
    if key in ['overdue', 'completed_periods']:
        return 'bar'
    if key in ['loan_share', 'on_time']:
        return 'stacked'
    return 'horizontal'


def history_mini_charts(values, monthly=None):
    """Return chart points and attach their existing metadata to the page context."""
    profiles = values['profiles']
    dimensions = {'debt': 'credit_type', 'overdue': 'credit_type', 'money_share': 'age_band',
                  'loan_share': 'age_band', 'history_profiles': 'product',
                  'completed_periods': 'age_band', 'on_time': 'age_band', 'utilization': 'income'}
    keys = ['debt', 'overdue', 'money_share', 'loan_share'] if monthly is None else [
        'history_profiles', 'completed_periods', 'on_time', 'utilization']
    captions = {'credit_type': 'Theo loại tín dụng', 'age_band': 'Theo nhóm tuổi',
                'product': 'Theo loại vay', 'income': 'Theo nguồn thu'}
    output, meta = {}, {}

    for key in keys:
        dimension = dimensions[key]
        if monthly is None:
            data = values['finance']['data']
            if dimension == 'credit_type':
                groups = _bureau_groups(data)
            else:
                groups = _profile_groups(profiles, dimension)
        else:
            groups = _profile_groups(profiles, dimension)
        if dimension == 'age_band':
            groups.sort(key=lambda row: AGE_LABELS.index(row[0]) if row[0] in AGE_LABELS else len(AGE_LABELS))
        points = []
        for label, ids, direct_rows in groups:
            if monthly is None:
                rows = direct_rows if direct_rows is not None else data.loc[data['SK_ID_CURR'].isin(ids)]
                value, n = _bureau_value(rows, key)
            else:
                value, n = _payment_tab_value(values, monthly, key, ids)
            points.append({'label': label, 'value': value, 'n': n})
        chart = _chart_kind(key)
        result = mini_points(points, captions[dimension], chart, bounded=key in ['loan_share', 'on_time'])
        if key == 'history_profiles' and not result['points']:
            # Managed demo can contain just one sufficiently populated product.
            # Use an explicit alternate dimension instead of a one-bar comparison.
            ages = segment_labels(profiles, 'age_band')
            points = []
            for label in AGE_LABELS:
                ids = set(profiles.loc[ages == label, 'source_application_id'])
                n = _monthly_profile_count(monthly, ids)
                points.append({'label': label, 'value': n, 'n': n})
            result = mini_points(points, captions['age_band'], chart)
        output[key] = result['points']
        meta[key] = result
    values['kpi_mini_meta'] = meta
    return output
