"""Read-only presentation aggregates; no model fitting or scoring policy changes."""
import numpy as np
import pandas as pd


SEGMENTS = {
    'product': 'Loại khoản vay', 'occupation': 'Nghề nghiệp',
    'income_band': 'Khoảng thu nhập', 'credit_band': 'Giá trị khoản vay',
    'age_band': 'Nhóm tuổi', 'education': 'Học vấn', 'housing': 'Nhà ở', 'income': 'Nguồn thu nhập',
}

SEGMENT_ORDERS = {
    'alerted_credit': 'Tổng giá trị khoản vay của các hồ sơ có cảnh báo', 'credit': 'Tổng giá trị tín dụng',
    'alert_share': 'Tỷ lệ cảnh báo', 'mean_score': 'Điểm trung bình',
    'alerted_amount_share': 'Tỷ trọng giá trị khoản vay của các hồ sơ có cảnh báo trong nhóm', 'n': 'Số hồ sơ đã chấm',
    'alerted_contribution': 'Đóng góp vào tổng tiền cảnh báo',
}


def ordered_segments(rows, field, descending=True):
    if field not in SEGMENT_ORDERS:
        raise ValueError('Cách sắp xếp phân khúc không hợp lệ.')
    def order(row):
        value = row.get(field)
        missing = value is None or not np.isfinite(value)
        return (missing, 0 if missing else -value if descending else value, -row['n'], row['label'])
    return sorted(rows, key=order)


def pending_priority(profiles, limit=10):
    data = profiles.loc[profiles['score'].notna() & profiles['alert'].eq(1)
                        & profiles['review_status'].isin(['new', 'in_review'])]
    return data.sort_values(['score', 'source_application_id'], ascending=[False, True]).head(limit)


def policy_scenario(profiles, baseline_threshold, scenario_threshold, capacity=None, scope='backlog'):
    """So sánh trên cùng cohort đã chấm; mọi thay đổi chỉ tồn tại trong kết quả."""
    if not np.isfinite(scenario_threshold) or not 0 <= scenario_threshold <= 1:
        raise ValueError('Ngưỡng mô phỏng phải nằm trong khoảng 0–100%.')
    if scope not in ['backlog', 'portfolio']:
        raise ValueError('Phạm vi năng lực không hợp lệ.')
    if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0):
        raise ValueError('Năng lực phải là số nguyên không âm.')
    scored = profiles.loc[profiles['score'].notna()].copy()
    credit = pd.to_numeric(scored['AMT_CREDIT'], errors='coerce')
    valid_money = np.isfinite(credit) & (credit >= 0)
    total_credit = float(credit.loc[valid_money].sum()) if valid_money.any() else None
    pending = scored['review_status'].isin(['new', 'in_review'])
    results = {}
    for name, threshold in [('baseline', baseline_threshold), ('scenario', scenario_threshold)]:
        alert = scored['score'] >= threshold
        alert_credit_n = int((alert & valid_money).sum())
        alert_credit = (float(credit.loc[alert & valid_money].sum())
                        if alert_credit_n or not alert.any() else None)
        summary = {'threshold': threshold, 'scored_n': len(scored), 'alert_n': int(alert.sum()),
            'alert_rate': float(alert.mean()) if len(scored) else None,
            'alert_credit': alert_credit,
            'alert_credit_share': alert_credit / total_credit if total_credit and alert_credit is not None else None,
            'pending_n': int((alert & pending).sum()),
            'excluded_money_n': int((alert & ~valid_money).sum())}
        if capacity is not None:
            pool = scored.loc[alert & pending] if scope == 'backlog' else scored
            pool = pool.sort_values(['score', 'source_application_id'], ascending=[False, True], kind='stable')
            selected = pool.head(capacity)
            selected_credit = pd.to_numeric(selected['AMT_CREDIT'], errors='coerce')
            money_ok = np.isfinite(selected_credit) & (selected_credit >= 0)
            cutoff = float(selected['score'].iloc[-1]) if len(selected) else None
            tied = pool['score'] == cutoff if cutoff is not None else pd.Series(False, index=pool.index)
            chosen_ties = int((selected['score'] == cutoff).sum()) if cutoff is not None else 0
            summary['capacity'] = {'eligible_n': len(pool), 'selected_n': len(selected),
                'remaining_n': len(pool) - len(selected), 'unused_n': max(0, capacity - len(pool)),
                'credit': float(selected_credit.loc[money_ok].sum()) if money_ok.any() or selected.empty else None,
                'excluded_money_n': int((~money_ok).sum()), 'cutoff': cutoff,
                'ties_n': int(tied.sum()), 'unselected_ties_n': int(tied.sum()) - chosen_ties,
                'profiles': [{'profile_id': int(row.profile_id), 'id': int(row.source_application_id),
                    'score': float(row.score), 'status': row.review_status,
                    'credit': float(row.AMT_CREDIT) if pd.notna(row.AMT_CREDIT) and np.isfinite(row.AMT_CREDIT) and row.AMT_CREDIT >= 0 else None}
                    for row in selected.head(10).itertuples()]}
        results[name] = summary
    results.update(scope=scope, requested_capacity=capacity, total_credit=total_credit,
                   excluded_money_n=int((~valid_money).sum()))
    return results


def segment_values(profiles, key):
    columns = {'product': 'NAME_CONTRACT_TYPE', 'occupation': 'OCCUPATION_TYPE',
               'education': 'NAME_EDUCATION_TYPE', 'housing': 'NAME_HOUSING_TYPE', 'income': 'NAME_INCOME_TYPE'}
    if key in columns:
        values = profiles[columns[key]].astype('string')
        values = values.replace({'__MISSING__': 'Chưa có thông tin'}).fillna('Chưa có thông tin')
        if key == 'product':
            values = values.replace({'Cash loans': 'Vay tiền mặt', 'Revolving loans': 'Vay quay vòng'})
        return values
    bins = {
        'income_band': ('AMT_INCOME_TOTAL', [0, 100000, 200000, 300000, np.inf],
                        ['Dưới 100.000', '100.000–<200.000', '200.000–<300.000', 'Từ 300.000']),
        'credit_band': ('AMT_CREDIT', [0, 250000, 500000, 1000000, np.inf],
                        ['Dưới 250.000', '250.000–<500.000', '500.000–<1.000.000', 'Từ 1.000.000']),
        'age_band': ('AGE_YEARS', [0, 30, 40, 50, 60, np.inf],
                     ['Dưới 30', '30–39', '40–49', '50–59', 'Từ 60']),
    }
    if key not in bins:
        raise ValueError('Chiều phân khúc rủi ro không hợp lệ.')
    column, edges, labels = bins[key]
    numeric = pd.to_numeric(profiles[column], errors='coerce')
    numeric = numeric.where(np.isfinite(numeric) & numeric.ge(0))
    return pd.cut(numeric, edges, labels=labels, right=False).astype('string').fillna('Chưa có thông tin')


def segment_report(profiles, key):
    data = profiles.loc[profiles['score'].notna()].copy()
    data['segment_label'] = segment_values(data, key)
    amount = pd.to_numeric(data['AMT_CREDIT'], errors='coerce')
    data['valid_credit'] = amount.where(np.isfinite(amount) & amount.ge(0))
    data['alerted_credit'] = data['valid_credit'].where(data['alert'].eq(1), 0)
    rows = []
    for label, group in data.groupby('segment_label', observed=True):
        valid = group['valid_credit'].notna()
        alert_valid = valid & group['alert'].eq(1)
        rows.append({'label': str(label), 'n': len(group),
                     'alert_n': int(group['alert'].sum()),
                     'alert_share': float(group['alert'].mean()),
                     'mean_score': float(group['score'].mean()),
                     'credit': float(group.loc[valid, 'valid_credit'].sum()) if valid.any() else None,
                     'alerted_credit': float(group.loc[alert_valid, 'valid_credit'].sum()) if valid.any() else None,
                     'credit_n': int(valid.sum()), 'excluded_credit_n': int((~valid).sum())})
    total_alerted = sum(row['alerted_credit'] or 0 for row in rows)
    for row in rows:
        row['alerted_amount_share'] = row['alerted_credit'] / row['credit'] if row['credit'] else None
        row['alerted_contribution'] = row['alerted_credit'] / total_alerted if total_alerted and row['alerted_credit'] is not None else None
    return ordered_segments(rows, 'alert_share')


def risk_bins(scores, threshold):
    # Keep the threshold on an exact bin boundary so alert counts reconcile.
    edges = sorted(set([*np.linspace(0, 1, 21).tolist(), float(threshold)]))
    values = pd.to_numeric(scores, errors='coerce').dropna().to_numpy(dtype=float)
    counts, _ = np.histogram(values, edges)
    return [{'low': low, 'high': high, 'n': int(n),
             'share': int(n) / len(values) if len(values) else 0,
             'alert': low >= threshold, 'key': f'{low:.17g}:{high:.17g}'}
            for low, high, n in zip(edges[:-1], edges[1:], counts)]


def filter_score_range(profiles, low_text, high_text):
    try:
        low, high = float(low_text), float(high_text)
    except (TypeError, ValueError):
        raise ValueError('Khoảng điểm không hợp lệ.') from None
    if not (np.isfinite(low) and np.isfinite(high) and 0 <= low < high <= 1):
        raise ValueError('Khoảng điểm phải nằm trong 0–1.')
    matches = profiles['score'].ge(low) & (profiles['score'].le(high) if high == 1 else profiles['score'].lt(high))
    return profiles.loc[matches].copy()


def base_model_contributions(model, features):
    """Contributions to the base model margin, before sigmoid calibration."""
    calibrated = getattr(model.model, 'calibrated_classifiers_', [])
    if model.metadata.get('model_family') == 'CAT':
        from catboost import Pool
        estimator = calibrated[0].estimator if calibrated else model.model
        prepared = model.prepareInput(features)
        values = estimator.get_feature_importance(
            Pool(prepared, cat_features=model.categorical), type='ShapValues')[0, :-1]
        order = np.argsort(np.abs(values))[::-1][:10]
        return [{'feature': model.feature_order[i], 'value': float(values[i])} for i in order]
    if len(calibrated) != 1:
        return []
    estimator = calibrated[0].estimator
    if not hasattr(estimator, 'named_steps') or not hasattr(estimator[-1], 'coef_'):
        return []
    prepared = model.prepareInput(features)
    transformed = estimator[:-1].transform(prepared)
    if hasattr(transformed, 'toarray'):
        transformed = transformed.toarray()
    terms = np.asarray(transformed)[0] * estimator[-1].coef_[0]
    names = estimator[:-1].get_feature_names_out()
    order = np.argsort(np.abs(terms))[::-1][:10]
    return [{'feature': str(names[i]), 'value': float(terms[i])} for i in order]
