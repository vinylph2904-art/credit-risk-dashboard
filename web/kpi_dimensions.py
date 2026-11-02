"""Small, explicitly labelled categorical comparisons for KPI cards."""
import math


def _donut_points(rows, caption):
    chart = 'donut'
    usable = [r for r in rows if r['value'] is not None and math.isfinite(float(r['value']))
              and r['value'] >= 0 and r['n'] > 0]
    total = sum(r['value'] for r in usable)
    if total <= 0 or len(usable) < 2:
        return {'points': [], 'caption': caption, 'chart': chart, 'bounded': True, 'truncated': False}
    visible = sorted([r for r in usable if r['n'] >= 5], key=lambda r: (-r['value'], r['label']))[:4]
    remaining = [r for r in usable if r not in visible]
    if remaining:
        visible.append({'label': 'Nhóm còn lại', 'value': sum(r['value'] for r in remaining),
                        'n': sum(r['n'] for r in remaining)})
    if len(visible) < 2:
        visible = []
    points, offset = [], 0
    colors = ['#2f7be5', '#2db9d2', '#a8d6cc', '#245fa8', '#cbd5e1']
    for i, row in enumerate(visible):
        share = row['value'] / total
        points.append({**row, 'share': share, 'offset': offset, 'color': colors[i]})
        offset += share * 100
    return {'points': points, 'caption': caption, 'chart': chart, 'bounded': True, 'truncated': bool(remaining)}


def mini_points(rows, caption, chart='bar', bounded=False):
    if chart == 'donut':
        return _donut_points(rows, caption)
    valid = [r for r in rows if r['n'] >= 5 and r['value'] is not None
             and math.isfinite(float(r['value'])) and r['value'] >= 0]
    truncated = len(valid) > 5
    if truncated:
        valid = sorted(valid, key=lambda r: (-r['value'], r['label']))[:5]
    if len(valid) < 2:
        valid = []
    maximum = 1 if bounded else max((r['value'] for r in valid), default=0)
    points = [{**r, 'x': 5 + i * 19,
               'height': float(r['value']) / maximum * 34 if maximum else 0}
              for i, r in enumerate(valid)]
    return {'points': points, 'caption': caption + (' · Top 5' if truncated else ''),
            'chart': chart, 'bounded': bounded, 'truncated': truncated}


def _choose_financial_groups(data, key, eligible, selected_dimension):
    from web.financial import financial_groups

    preferred = {'credit': 'product', 'rate': 'income_band', 'credit_share': 'income',
                 'credit_income': 'age_band', 'annuity_income': 'product',
                 'median_credit': 'income_band', 'credit_goods': 'product'}
    captions = {'product': 'Theo loại vay', 'income': 'Theo nguồn thu',
                'income_band': 'Theo mức thu nhập', 'age_band': 'Theo nhóm tuổi'}
    dimension = preferred[key]
    if dimension == selected_dimension:
        dimension = next(d for d in ['age_band', 'product', 'income_band', 'income']
                         if d != selected_dimension)
    candidates = [dimension] + [d for d in ['age_band', 'income_band', 'product', 'income']
                                if d != dimension and d != selected_dimension]
    groups = []
    for candidate in candidates:
        candidate_groups = financial_groups(data, candidate)
        supported = [g for g in candidate_groups if g.get(eligible, 0) >= 5 and g.get(key) is not None]
        groups = candidate_groups
        dimension = candidate
        if len(supported) >= 2:
            break
    return groups, dimension, captions


def financial_mini(data, key, eligible, selected_dimension=None):
    groups, dimension, captions = _choose_financial_groups(data, key, eligible, selected_dimension)
    rows = []
    # Contribution to total difficult-payment credit, not the within-group rate.
    denominator = sum((r.get('positive_credit') or 0) for r in groups) if key == 'credit_share' else None
    for group in groups:
        value = group.get(key)
        if key == 'credit_share':
            positive_credit = group.get('positive_credit')
            value = positive_credit / denominator if denominator and positive_credit is not None else None
        rows.append({'label': group['label'], 'value': value, 'n': group.get(eligible, 0)})
    caption = captions[dimension]
    if key == 'credit_share':
        caption = 'Đóng góp · ' + caption.removeprefix('Theo ')
    chart = 'horizontal'
    if key in ['credit', 'credit_share']:
        chart = 'donut'
    elif key == 'rate':
        chart = 'stacked'
    result = mini_points(rows, caption, chart=chart,
        bounded=key in ['rate', 'credit_share'])
    result['dimension'] = dimension
    result['note'] = ('Mỗi nhóm đóng góp vào tổng giá trị khoản vay của nhóm TARGET=1 trong phạm vi đang xem. '
                      'Không phải tỷ trọng TARGET=1 bên trong từng nhóm.' if key == 'credit_share' else
                      'Cùng công thức với KPI, tính riêng cho từng nhóm trong phạm vi đang xem.')
    return result
