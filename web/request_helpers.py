"""Read filters and build URLs without changing request scope."""
import math
from flask import request, url_for
from web import runtime


def page_url(page):
    params = request.args.to_dict()
    params['page'] = page
    return url_for(request.endpoint, **params)



def filter_url(name, value):
    # Bật/tắt một bộ lọc nhanh, giữ các điều kiện còn lại và về trang đầu.
    params = request.args.to_dict()
    if params.get(name) == value:
        params.pop(name)
    else:
        params[name] = value
    params.pop('page', None)
    return url_for(request.endpoint, **params)



def cohort_url(endpoint, **changes):
    fields = runtime.COHORT_FIELDS + ['currency', 'credit_status', 'financial_filter',
                              'source', 'months', 'from_state', 'to_state', 'breakdown',
                              'drill_kind', 'drill_value', 'segment', 'segment_metric', 'score_min', 'score_max',
                              'segment_order', 'segment_sort', 'segment_direction']
    params = {name: request.args[name] for name in fields if request.args.get(name)}
    if endpoint in ['dashboard', 'risk_dashboard', 'financial_records', 'financial_source']:
        for name in ['finance_group', 'ratio', 'history_metric']:
            if request.args.get(name):
                params[name] = request.args[name]
    params.update(changes)
    return url_for(endpoint, **params)



def read_cohort_filters():
    filters = {name: request.args.get(name, '').strip() for name in runtime.COHORT_FIELDS}
    for name, choices in [('product', runtime.PRODUCTS), ('income', runtime.INCOME_TYPES),
                          ('availability', runtime.AVAILABILITY)]:
        if filters[name] and filters[name] not in choices:
            raise ValueError('Điều kiện phân khúc không hợp lệ.')
    for label, low, high in [('Số tiền', 'amount_min', 'amount_max'), ('Tuổi', 'age_min', 'age_max')]:
        for name in [low, high]:
            try:
                value = float(filters[name]) if filters[name] else None
            except ValueError:
                raise ValueError(f'{label} cần là số hợp lệ.') from None
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f'{label} cần là số hữu hạn, không âm.')
            filters[name] = value
        if filters[low] is not None and filters[high] is not None and filters[low] > filters[high]:
            raise ValueError(f'{label} từ không được lớn hơn {label.lower()} đến.')
    return filters

