"""Financial reporting aggregates and figures; never fit or write scoring data."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from textwrap import wrap

from web.charts import DashboardCharts
from web.chart_palette import (
    BLUE, BLUE_DEEP, RED, LIGHT, PALE, FAINT, UNKNOWN, CATEGORICAL, DATA_ROSE, COMPARISON_GRAY, categorical_colors, value_blue_colors, value_red_colors,
)

INK = '#33475d'
PAYMENT_LABELS = {0: 'Không ghi nhận khó khăn', 1: 'Có khó khăn thanh toán'}
RATIOS = {
    'credit_income': ('RATIO_CREDIT_INCOME_RECORDED', 'Hệ số đòn bẩy khoản vay'),
    'annuity_income': ('RATIO_ANNUITY_INCOME_RECORDED', 'Tỷ lệ niên kim trên thu nhập'),
    'credit_goods': ('RATIO_CREDIT_GOODS_RECORDED', 'Tỷ lệ tài trợ hàng hóa'),
}
DIMENSIONS = {
    'credit_band': 'Giá trị khoản vay', 'income': 'Nguồn thu nhập',
    'product': 'Loại khoản vay', 'occupation': 'Nghề nghiệp',
    'income_band': 'Khoảng thu nhập', 'age_band': 'Nhóm tuổi',
    'education': 'Học vấn', 'family': 'Tình trạng hôn nhân',
    'housing': 'Nhà ở', 'car': 'Sở hữu xe', 'realty': 'Sở hữu nhà',
}
HISTORY_SOURCES = {
    'installments': ('Kỳ trả góp', 'HAS_USABLE_INSTALLMENTS', 'INS_OBS_VERSIONED_PERIOD_N', 'INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE'),
    'bureau_balance': ('Bureau theo tháng', 'HAS_USABLE_BUREAU_BALANCE', 'BB_KNOWN_DPD_MONTH_N', 'BB_DPD_MONTH_SHARE'),
    'pos': ('POS', 'HAS_USABLE_POS', 'POS_KNOWN_DPD_MONTH_N', 'POS_DPD_MONTH_SHARE'),
    'card': ('Thẻ tín dụng', 'HAS_USABLE_CARD', 'CC_KNOWN_DPD_MONTH_N', 'CC_DPD_MONTH_SHARE'),
}
BANDS = {
    'credit_band': ('AMT_CREDIT', [0, 250000, 500000, 1000000, np.inf],
        ['Dưới 250.000', '250.000–<500.000', '500.000–<1.000.000', 'Từ 1.000.000']),
    'income_band': ('AMT_INCOME_TOTAL', [0, 100000, 200000, 300000, np.inf],
        ['Dưới 100.000', '100.000–<200.000', '200.000–<300.000', 'Từ 300.000']),
    'age_band': ('AGE_YEARS', [0, 30, 40, 50, 60, np.inf],
        ['Dưới 30', '30–39', '40–49', '50–59', 'Từ 60']),
}


def valid_values(data, column, positive=False):
    values = pd.to_numeric(data[column], errors='coerce')
    valid = np.isfinite(values) & (values > 0 if positive else values >= 0)
    return values.where(valid)


def financial_summary(data):
    credit = valid_values(data, 'AMT_CREDIT')
    result = {'n': len(data), 'credit_n': int(credit.notna().sum()),
              'credit': float(credit.sum()) if credit.notna().any() else None,
              'median_credit': float(credit.median()) if credit.notna().any() else None}
    for name, numerator, denominator in [
        ('credit_income', 'AMT_CREDIT', 'AMT_INCOME_TOTAL'),
        ('annuity_income', 'AMT_ANNUITY', 'AMT_INCOME_TOTAL'),
        ('credit_goods', 'AMT_CREDIT', 'AMT_GOODS_PRICE')]:
        ratio = valid_values(data, numerator) / valid_values(data, denominator, positive=True)
        ratio = ratio.where(np.isfinite(ratio))
        result[name] = float(ratio.median()) if ratio.notna().any() else None
        result[name + '_n'] = int(ratio.notna().sum())
    if 'TARGET' in data:
        known = data['TARGET'].isin([0, 1])
        positive = data['TARGET'] == 1
        money_known = known & credit.notna()
        total = credit.loc[money_known].sum()
        result.update(label_n=int(known.sum()), positive_n=int((known & positive).sum()),
            label_credit_n=int(money_known.sum()),
            rate=float(positive.loc[known].mean()) if known.any() else None,
            positive_credit=float(credit.loc[money_known & positive].sum()) if money_known.any() else None,
            credit_share=float(credit.loc[money_known & positive].sum() / total) if total > 0 else None)
    return result


def segment_labels(data, dimension):
    columns = {'product': 'NAME_CONTRACT_TYPE', 'income': 'NAME_INCOME_TYPE',
        'occupation': 'OCCUPATION_TYPE', 'education': 'NAME_EDUCATION_TYPE',
        'family': 'NAME_FAMILY_STATUS', 'housing': 'NAME_HOUSING_TYPE',
        'car': 'FLAG_OWN_CAR', 'realty': 'FLAG_OWN_REALTY'}
    if dimension in columns:
        labels = data[columns[dimension]].astype('string').replace({
            '__MISSING__': 'Chưa có thông tin', 'Y': 'Có', 'N': 'Không',
            'Cash loans': 'Vay tiền mặt', 'Revolving loans': 'Vay quay vòng',
            'Working': 'Đi làm', 'Commercial associate': 'Kinh doanh',
            'Pensioner': 'Hưu trí', 'State servant': 'Khu vực nhà nước',
            'Unemployed': 'Chưa có việc làm', 'Student': 'Sinh viên',
            'Businessman': 'Kinh doanh cá nhân', 'Maternity leave': 'Nghỉ thai sản',
        })
        return labels.fillna('Chưa có thông tin')
    if dimension not in BANDS:
        raise ValueError('Chiều phân tích tài chính không hợp lệ.')
    column, edges, labels = BANDS[dimension]
    return pd.cut(valid_values(data, column), edges, labels=labels, right=False).astype('string').fillna('Chưa có thông tin')


def financial_groups(data, dimension):
    labels = segment_labels(data, dimension)
    groups = []
    for label, rows in data.groupby(labels, observed=True, sort=False):
        summary = financial_summary(rows)
        summary['label'] = str(label)
        groups.append(summary)
    if dimension in BANDS:
        order = {label: index for index, label in enumerate(BANDS[dimension][2])}
        groups.sort(key=lambda row: order.get(row['label'], len(order)))
    else:
        groups.sort(key=lambda row: (row['credit'] is None, -(row['credit'] or 0), row['label']))
    return groups


def bureau_summary(data):
    result = {name: int(data[name].sum()) for name in ['loan_n', 'money_n', 'dpd_n', 'overdue_n']}
    for name in ['debt', 'overdue', 'outside_overdue']:
        values = pd.to_numeric(data[name], errors='coerce')
        result[name] = float(values.sum()) if values.notna().any() else None
    result['share'] = result['overdue'] / result['debt'] if result['debt'] and result['overdue'] is not None else None
    result['rate'] = result['overdue_n'] / result['dpd_n'] if result['dpd_n'] else None
    return result


def make_figure(figure, chart_id, empty=False, interaction=None):
    if chart_id.startswith('finance-overview-'):
        for trace in figure.data:
            if trace.type == 'bar':
                if chart_id == 'finance-overview-asset-ownership':
                    trace.marker.color = {'Có': DATA_ROSE, 'Không': COMPARISON_GRAY, 'Chưa xác định': FAINT}[trace.name]
                    if trace.name == 'Chưa xác định':
                        trace.marker.pattern.shape = '/'
                elif chart_id != 'finance-overview-credit-composition':
                    color_values = trace.x if trace.orientation == 'h' else trace.y
                    trace.marker.color = (value_red_colors(color_values)
                            if chart_id == 'finance-overview-history-summary' else value_blue_colors(color_values))
                if chart_id in ['finance-overview-loan-distribution', 'finance-overview-ratio-distribution']:
                    trace.texttemplate = '%{x:,.0f}' if trace.orientation == 'h' else '%{y:,.0f}'
                    trace.textposition = 'outside'
                    trace.textfont = {'size': 12, 'color': '#3b2932'}
                    trace.cliponaxis = False
                    values = trace.x if trace.orientation == 'h' else trace.y
                    maximum = max(values, default=0)
                    if maximum > 0:
                        if trace.orientation == 'h':
                            figure.update_xaxes(range=[0, maximum * 1.2])
                        else:
                            figure.update_yaxes(range=[0, maximum * 1.2])
    figure.update_layout(colorway=CATEGORICAL,
        bargap=.6 if chart_id == 'finance-overview-credit-composition' else .24, separators=',.')
    return DashboardCharts()._html(figure, chart_id, interaction,
        empty_message='Chưa có dữ liệu hợp lệ trong phạm vi này' if empty else None)


def bar_figure(groups, field, chart_id, axis, percent=False, links=None):
    rows = [row for row in groups if row.get(field) is not None][:8]
    figure = go.Figure(go.Bar(y=[r['label'] for r in rows], x=[r[field] for r in rows],
        orientation='h', marker_color=value_blue_colors([r[field] for r in rows]),
        hovertemplate=('%{y}<br>%{x:.2%}' if percent else '%{y}<br>%{x:,.2f}') + '<extra></extra>'))
    figure.update_yaxes(autorange='reversed', tickmode='array',
        tickvals=[r['label'] for r in rows], ticktext=['<br>'.join(wrap(r['label'], 22)) for r in rows])
    figure.update_xaxes(title=axis, tickformat='.0%' if percent else '~s', rangemode='tozero')
    interaction = {'type': 'filter', 'key': 'y', 'urls': links} if links else None
    return make_figure(figure, chart_id, not rows, interaction)


def credit_figure(groups, chart_id, labeled, links=None):
    rows = [row for row in groups if row['credit'] is not None][:8]
    figure = go.Figure()
    if labeled:
        for label, color, field in [(PAYMENT_LABELS[0], PALE, 'other'), (PAYMENT_LABELS[1], RED, 'positive')]:
            values = [(row['positive_credit'] or 0) if field == 'positive'
                      else row['credit'] - (row['positive_credit'] or 0) for row in rows]
            figure.add_bar(y=[row['label'] for row in rows], x=values, orientation='h',
                name=label, marker_color=color, hovertemplate='%{y}<br>%{x:,.0f}<extra>%{fullData.name}</extra>')
    else:
        figure.add_bar(y=[r['label'] for r in rows], x=[r['credit'] for r in rows],
            orientation='h', marker_color=categorical_colors(len(rows)), hovertemplate='%{y}<br>%{x:,.0f}<extra></extra>')
    figure.update_layout(barmode='stack', showlegend=labeled)
    figure.update_yaxes(autorange='reversed', tickmode='array',
        tickvals=[r['label'] for r in rows], ticktext=['<br>'.join(wrap(r['label'], 22)) for r in rows])
    figure.update_xaxes(title='Giá trị khoản vay · đơn vị nguồn', tickformat='~s')
    interaction = {'type': 'filter', 'key': 'y', 'urls': links} if links else None
    return make_figure(figure, chart_id, not rows, interaction)


def ratio_distribution(data, ratio_name, chart_id='finance-ratio-distribution'):
    column, label = RATIOS[ratio_name]
    values = valid_values(data, column).dropna()
    figure = go.Figure()
    percent = ratio_name != 'credit_income'
    if len(values):
        cap = float(values.quantile(.99))
        cap = cap if cap > 0 else max(float(values.max()), 1.)
        edges = np.linspace(0, cap, 10)
        counts, _ = np.histogram(values.loc[values < cap], edges)
        labels = ([f'{low*100:.1f}–<{high*100:.1f}%' for low, high in zip(edges[:-1], edges[1:])]
                  if percent else [f'{low:.2f}–<{high:.2f}' for low, high in zip(edges[:-1], edges[1:])])
        labels.append(f'≥ {cap*100:.1f}%' if percent else f'≥ {cap:.2f}')
        counts = counts.tolist() + [int((values >= cap).sum())]
        figure.add_bar(x=labels, y=counts, marker_color=value_blue_colors(counts),
            hovertemplate=('%{x}<br>' if percent else '%{x} lần<br>') + '%{y:,} hồ sơ<extra></extra>')
    figure.update_xaxes(title='Tỷ lệ ghi nhận (%)' if percent else 'Hệ số (lần)', tickangle=-30,
        tickmode='array', tickvals=labels[::3] if len(values) else [])
    figure.update_yaxes(title='Số hồ sơ', rangemode='tozero')
    return make_figure(figure, chart_id, values.empty)


def ratio_box(data, dimension, labels, ratio_name):
    column, title = RATIOS[ratio_name]
    values = valid_values(data, column)
    names, quartiles, counts = [], [], []
    segments = segment_labels(data, dimension)
    for label in labels[:8]:
        known = values.loc[segments == label].dropna()
        if len(known):
            names.append(label)
            quartiles.append(known.quantile([.1, .25, .5, .75, .9]).tolist())
            counts.append(len(known))
    figure = go.Figure()
    if quartiles:
        q = np.array(quartiles)
        figure.add_trace(go.Scatter(y=names, x=q[:, 2], mode='markers',
            marker={'color': BLUE, 'size': 9},
            error_x={'type': 'data', 'symmetric': False,
                'array': q[:, 3] - q[:, 2], 'arrayminus': q[:, 2] - q[:, 1],
                'color': LIGHT, 'thickness': 4, 'width': 0},
            hoverinfo='skip', name='Trung vị · khoảng 25–75%'))
        # One tooltip per group instead of staggered native box labels.
        unit = ' lần' if ratio_name == 'credit_income' else '%'
        scale = 1 if ratio_name == 'credit_income' else 100
        tooltip_rows, hover_x, hover_y = [], [], []
        for name, quantiles, count in zip(names, quartiles, counts):
            rows = [[label, f'{value * scale:,.2f}{unit}'.replace(',', '_').replace('.', ',').replace('_', '.')]
                    for label, value in zip(['P10', 'Q1 (25%)', 'Trung vị', 'Q3 (75%)', 'P90'], quantiles)]
            for value in quantiles:
                hover_x.append(value)
                hover_y.append(name)
                tooltip_rows.append([name, [*rows, ['Hồ sơ hợp lệ', f'{count:,}'.replace(',', '.')]]])
        figure.add_trace(go.Scatter(x=hover_x, y=hover_y, mode='markers',
            marker={'size': 18, 'color': 'rgba(0,0,0,0)'}, customdata=tooltip_rows,
            meta={'compactTooltip': True}, hoverinfo='none', showlegend=False))
    figure.update_layout(showlegend=False)
    figure.update_yaxes(autorange='reversed', tickmode='array', tickvals=names,
        ticktext=['<br>'.join(wrap(name, 22)) for name in names])
    figure.update_xaxes(title='Các phân vị ghi nhận · ' + ('lần' if ratio_name == 'credit_income' else '%'),
        tickformat='.2f' if ratio_name == 'credit_income' else '.0%', rangemode='tozero')
    return make_figure(figure, 'finance-ratio-comparison', not quartiles)


def history_figure(data, chart_id='finance-history-signals'):
    sources = [
        ('Bureau theo tháng', 'HAS_USABLE_BUREAU_BALANCE', 'BB_KNOWN_DPD_MONTH_N', 'BB_DPD_MONTH_SHARE'),
        ('POS', 'HAS_USABLE_POS', 'POS_KNOWN_DPD_MONTH_N', 'POS_DPD_MONTH_SHARE'),
        ('Thẻ tín dụng', 'HAS_USABLE_CARD', 'CC_KNOWN_DPD_MONTH_N', 'CC_DPD_MONTH_SHARE'),
        ('Kỳ trả góp', 'HAS_USABLE_INSTALLMENTS', 'INS_OBS_VERSIONED_PERIOD_N', 'INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE')]
    labels, rates, counts = [], [], []
    for label, flag, count, share in sources:
        known = (data[flag] == 1) & (data[count] > 0) & data[share].notna()
        labels.append(label)
        rates.append(float((data.loc[known, share] > 0).mean()) if known.any() else None)
        counts.append(int(known.sum()))
    figure = go.Figure(go.Bar(y=labels, x=rates, orientation='h', customdata=counts,
        marker_color=value_blue_colors(rates),
        hovertemplate='%{y}<br>%{x:.1%} hồ sơ có dấu hiệu<br>%{customdata:,} hồ sơ xác định được<extra></extra>'))
    figure.update_yaxes(autorange='reversed', tickmode='array', tickvals=labels,
        ticktext=['Bureau', 'POS', 'Thẻ tín dụng', 'Trả góp'])
    figure.update_xaxes(title='Tỷ lệ hồ sơ có dấu hiệu', tickformat='.0%', rangemode='tozero')
    return make_figure(figure, chart_id, not any(counts))


def overview_figures(data, scope, ratio_name):
    """Whole-cohort composition/distributions belong only on the overview."""
    figure = go.Figure()
    if scope == 'research':
        credit = valid_values(data, 'AMT_CREDIT')
        known = data['TARGET'].isin([0, 1]) & credit.notna()
        values = [float(credit.loc[known & data['TARGET'].eq(label)].sum()) for label in [0, 1]]
        counts = [int((known & data['TARGET'].eq(label)).sum()) for label in [0, 1]]
        labels = [PAYMENT_LABELS[0], PAYMENT_LABELS[1]]
        colors = [COMPARISON_GRAY, RED]
        title = 'Cơ cấu giá trị khoản vay theo kết quả lịch sử'
    else:
        groups = financial_groups(data, 'product')
        values = [row['credit'] or 0 for row in groups]
        counts = [row['credit_n'] for row in groups]
        labels = [row['label'] for row in groups]
        colors = value_blue_colors(values)
        title = 'Cơ cấu giá trị khoản vay theo sản phẩm'
    total = sum(values)
    if total:
        figure.add_trace(go.Pie(labels=labels, values=values, hole=.6, sort=False,
            marker_colors=colors, texttemplate='%{percent:.0%}',
            textposition='inside', insidetextorientation='horizontal', textfont={'size': 12,
                'color': ['#ffffff' if color in [BLUE, BLUE_DEEP] else '#3b2932' for color in colors]},
            automargin=False,
            customdata=[[count, sum(counts)] for count in counts],
            hovertemplate='%{label}<br>%{percent} · %{value:,.0f}'
                '<br>%{customdata[0]:,} / %{customdata[1]:,} hồ sơ đủ dữ liệu tiền và nhóm<extra></extra>'))
    figure.update_layout(showlegend=True)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    panels = [{'title': title, 'html': make_figure(figure, 'finance-overview-credit-composition', not sum(values))}]
    loan_groups = financial_groups(data, 'credit_band')
    panels.append({'title': 'Quy mô khoản vay trong toàn phạm vi',
        'html': bar_figure(loan_groups, 'n', 'finance-overview-loan-distribution', 'Số hồ sơ')})
    income = financial_groups(data, 'income_band')
    figure = go.Figure(go.Bar(x=[row['label'] for row in income], y=[row['n'] for row in income],
        marker_color=value_blue_colors([row['n'] for row in income]), hovertemplate='%{x}<br>%{y:,} hồ sơ<extra></extra>'))
    figure.update_xaxes(title='Thu nhập ghi nhận · đơn vị nguồn', tickangle=-15)
    figure.update_yaxes(title='Số hồ sơ', rangemode='tozero')
    panels.append({'title': 'Phân bố thu nhập ghi nhận',
        'html': make_figure(figure, 'finance-overview-income-distribution', not income)})
    panels.append({'title': 'Tỷ lệ hồ sơ có dấu hiệu thanh toán trễ trong lịch sử',
        'html': history_figure(data, 'finance-overview-history-summary')})
    panels.append({'title': 'Phân bố ' + RATIOS[ratio_name][1].lower(),
        'html': ratio_distribution(data, ratio_name, 'finance-overview-ratio-distribution')})
    figure = go.Figure()
    for value, label, color in [('Y', 'Có', LIGHT), ('N', 'Không', FAINT), (None, 'Chưa xác định', UNKNOWN)]:
        counts = []
        for column in ['FLAG_OWN_REALTY', 'FLAG_OWN_CAR']:
            flags = data[column]
            counts.append(int((~flags.isin(['Y', 'N'])).sum()) if value is None else int((flags == value).sum()))
        figure.add_bar(y=['Nhà ở', 'Xe'], x=[count / len(data) if len(data) else None for count in counts],
            orientation='h', name=label, marker_color=color, customdata=counts,
            hovertemplate='%{y}<br>%{x:.1%} · %{customdata:,} hồ sơ<extra>%{fullData.name}</extra>')
    figure.update_layout(barmode='stack', showlegend=True)
    figure.update_xaxes(title='Cơ cấu trong toàn phạm vi', tickformat='.0%', range=[0, 1])
    panels.append({'title': 'Cơ cấu sở hữu nhà và xe',
        'html': make_figure(figure, 'finance-overview-asset-ownership', data.empty)})
    return panels


def history_by_segment(data, dimension, names, source, links):
    label, flag, count, share = HISTORY_SOURCES[source]
    amount = pd.to_numeric(data[share], errors='coerce')
    observations = pd.to_numeric(data[count], errors='coerce')
    known = (data[flag] == 1) & np.isfinite(observations) & (observations > 0) & np.isfinite(amount) & (amount >= 0) & (amount <= 1)
    states = pd.Series('Chưa xác định', index=data.index)
    states.loc[known & (amount == 0)] = 'Chưa ghi nhận dấu hiệu'
    states.loc[known & (amount > 0)] = 'Ghi nhận dấu hiệu'
    labels = segment_labels(data, dimension)
    figure = go.Figure()
    for state, color in [('Ghi nhận dấu hiệu', RED), ('Chưa ghi nhận dấu hiệu', PALE), ('Chưa xác định', UNKNOWN)]:
        counts = [int(((labels == name) & (states == state)).sum()) for name in names]
        totals = [int((labels == name).sum()) for name in names]
        figure.add_bar(y=names, x=[n / total if total else None for n, total in zip(counts, totals)],
            orientation='h', name=state.replace(' dấu hiệu', ''), marker_color=color, customdata=counts,
            hovertemplate='%{y}<br>%{x:.1%} · %{customdata:,} hồ sơ<extra>%{fullData.name}</extra>')
    figure.update_layout(barmode='stack', showlegend=True)
    figure.update_yaxes(autorange='reversed', tickmode='array', tickvals=names,
        ticktext=['<br>'.join(wrap(name, 22)) for name in names])
    figure.update_xaxes(title=label + ' · cơ cấu trạng thái quan sát', tickformat='.0%', range=[0, 1])
    return make_figure(figure, 'finance-segment-history', not names,
        {'type': 'filter', 'key': 'y', 'urls': links})


def portfolio_figures(data, groups, scope, dimension, ratio_name, links, reference, history_source):
    """Segment comparisons/diagnostics; no whole-cohort histogram or summary."""
    labeled = scope == 'research'
    visible = [row for row in groups if row['n'] >= 5][:8]
    if not visible:
        visible = groups[:8]
    titles = [row['label'] for row in visible]
    panels = []
    panels.append({'title': 'Giá trị khoản vay theo phân khúc',
        'html': credit_figure(visible, 'finance-credit-segments', labeled, links)})
    panels.append({'title': 'Tỷ lệ khó khăn thanh toán theo phân khúc' if labeled else 'Đòn bẩy khoản vay theo phân khúc',
        'html': bar_figure(visible, 'rate' if labeled else 'credit_income', 'finance-segment-rate',
            'Tỷ lệ khó khăn thanh toán' if labeled else 'Trung vị · lần', labeled, links)})
    figure = go.Figure(go.Scatter(x=[r.get('rate') if labeled else r['credit_income'] for r in visible],
            y=[r.get('positive_credit') if labeled else r['credit'] for r in visible],
            text=titles, mode='markers+text', textposition='top center',
            customdata=[r['n'] for r in visible],
            marker={'size': [r['n'] for r in visible], 'sizemode': 'area',
                'sizeref': 2 * max([r['n'] for r in visible], default=1) / 38**2,
                'color': (value_red_colors([r.get('rate') for r in visible]) if labeled
                    else value_blue_colors([r['credit_income'] for r in visible])), 'sizemin': 6},
            hovertemplate='<b>%{text}</b><br>' +
                ('Khó khăn thanh toán: %{x:.1%}<br>Giá trị vay gặp khó khăn: %{y:,.0f}' if labeled else
                 'Đòn bẩy khoản vay: %{x:.2f} lần<br>Tổng giá trị khoản vay: %{y:,.0f}') +
                '<br>%{customdata:,} hồ sơ<extra></extra>'))
    figure.update_xaxes(title='Tỷ lệ khó khăn thanh toán' if labeled else 'Đòn bẩy khoản vay điển hình (lần)',
            tickformat='.0%' if labeled else '.1f', rangemode='tozero')
    figure.update_yaxes(title='Giá trị vay gặp khó khăn' if labeled else 'Tổng giá trị khoản vay', tickformat='~s', rangemode='tozero')
    panels.append({'title': 'Phân khúc theo quy mô khoản vay và khó khăn thanh toán' if labeled
                   else 'Phân khúc theo quy mô khoản vay và tỷ lệ vay / thu nhập',
            'html': make_figure(figure, 'finance-concentration', not visible,
                {'type': 'filter', 'key': 'text', 'urls': links})})
    panels.append({'title': RATIOS[ratio_name][1] + ' theo ' + DIMENSIONS[dimension].lower(),
        'html': ratio_box(data, dimension, titles, ratio_name)})
    z, raw = [], []
    for row in visible:
        values, actual = [], []
        for key in RATIOS:
            value, base = row[key], reference[key]
            values.append((value / base - 1) * 100 if value is not None and base is not None and base > 0 else None)
            if value is None:
                actual.append('Chưa xác định')
            else:
                actual.append((f'{value:.3f} lần' if key == 'credit_income' else f'{value*100:.2f}%').replace('.', ','))
        z.append(values)
        raw.append(actual)
    tooltips = []
    for name, values, actual in zip(titles, z, raw):
        tooltips.append([[name, [['Chỉ tiêu', label], ['Trung vị', value],
            ['So với tham chiếu', f'{delta:+.1f}%'.replace('.', ',') if delta is not None else 'Chưa xác định']]]
            for label, value, delta in zip(['Đòn bẩy khoản vay', 'Niên kim / thu nhập', 'Tài trợ hàng hóa'], actual, values)])
    figure = go.Figure(go.Heatmap(z=z, y=titles,
        x=['Đòn bẩy<br>khoản vay', 'Tỷ lệ niên kim<br>trên thu nhập', 'Tỷ lệ tài trợ<br>hàng hóa'], customdata=tooltips,
        colorscale=[[0, '#e9a5b3'], [.5, '#fff5f8'], [1, BLUE_DEEP]], zmid=0,
        text=[['—' if value is None else f'{value:+.1f}%'.replace('.', ',') for value in row] for row in z],
        texttemplate='%{text}', textfont={'size': 12},
        colorbar={'title': {'text': '% chênh'}, 'thickness': 9, 'len': .7},
        meta={'compactTooltip': True}, hoverinfo='none'))
    figure.update_yaxes(autorange='reversed', tickmode='array', tickvals=titles,
        ticktext=['<br>'.join(wrap(name, 22)) for name in titles])
    panels.append({'title': 'Chênh lệch tỷ số tài chính so với mức tham chiếu',
        'html': make_figure(figure, 'finance-segment-ratio-heatmap', not titles,
            {'type': 'filter', 'key': 'y', 'urls': links})})
    panels.append({'title': ('Lịch sử trả góp' if history_source == 'installments'
                             else HISTORY_SOURCES[history_source][0]) + ' theo phân khúc',
        'html': history_by_segment(data, dimension, titles, history_source, links)})
    return panels
