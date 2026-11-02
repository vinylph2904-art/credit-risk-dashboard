"""Dashboard pages, financial drill-through and chart APIs."""
import math
from flask import abort, jsonify, redirect, render_template, request, send_file, session, url_for
from models.CreditRiskStatistic import CreditRiskStatistic
from models.CreditRiskPortfolio import CreditRiskPortfolio
from web.drilldown import select_chart_records
from web.analytics import SEGMENTS
from web import runtime
from web import request_helpers as query
from web import portfolio_context as portfolio_views
from web import financial_context as financial_views
from web.kpi_history_mini import history_mini_charts


def financial_records():
    canonical = financial_views.redirect_old_financial_scope()
    if canonical is not None:
        return canonical
    scope, version, reference, data, filters, dimension, selected = financial_views.financial_data()
    page = runtime.positive_id(request.args.get('page', '1'))
    pages = max(1, math.ceil(len(data) / 25))
    page = min(page, pages)
    data = data.sort_values(['AMT_CREDIT', 'source_application_id'], ascending=[False, True])
    rows = runtime.records(data.iloc[(page - 1) * 25:page * 25])
    return render_template('financial_records.html', active='risk_dashboard', financial_view=True,
        source_rows=rows, data_scope=scope, total=len(data), page=page, pages=pages,
        selected_group=selected, data_version=version)



def financial_source(source_id):
    # Research drill-through is read-only; it never creates a managed case.
    scope, version, reference, data, filters, dimension, selected = financial_views.financial_data()
    selected_row = data.loc[data['source_application_id'] == source_id]
    if selected_row.empty:
        abort(404)
    row = runtime.records(selected_row)[0]
    if scope == 'managed':
        return redirect(url_for('application_detail', profile_id=row['profile_id']))
    portfolio = CreditRiskPortfolio(runtime.get_db())
    bureau = portfolio.readBureau([source_id])
    valid_time = ((bureau['DAYS_CREDIT'] <= 0) & (bureau['DAYS_CREDIT_UPDATE'] <= 0)
                  & (bureau['DAYS_CREDIT_UPDATE'] >= bureau['DAYS_CREDIT']))
    payments = portfolio.paymentReport(portfolio.readPayments([source_id]))
    periods = payments['data']
    completed_delay = periods['delay_days'].dropna()
    return render_template('financial_source.html', active='assessment', financial_view=True,
        source_row=row, data_scope=scope, data_version=version,
        source_bureau=runtime.records(bureau.loc[valid_time]), source_payments=payments,
        source_on_time=payments['on_time_n'] / payments['periods_n'] if payments['periods_n'] else None,
        source_mean_delay=float(completed_delay.mean()) if len(completed_delay) else None)



def dashboard():
    canonical = financial_views.redirect_old_financial_scope()
    if canonical is not None:
        return canonical
    if not request.args.get('financial_filter') and not request.args.get('drill_kind'):
        return render_template('financial_dashboard.html', active='dashboard', plotly_enabled=True,
            financial_view=True, **financial_views.financial_context(overview=True))
    return render_template('risk_overview.html', active='dashboard', plotly_enabled=True,
                           **portfolio_views.risk_analytics_context())


def credit_diagnostics():
    values = portfolio_views.portfolio_context(include_history=True)
    values['kpi_minis'] = history_mini_charts(values)
    values['loan_rows'] = runtime.records(values['finance']['data'].sort_values('overdue', ascending=False).head(100))
    values['exceptions'] = runtime.records(values['finance']['data'].loc[values['finance']['data']['needs_check']])
    values['dpd_chart'] = runtime.charts.counts(
        [row for row in values['finance']['buckets'] if row['label'] != 'Chưa xác định'],
        'Số khoản bureau', 'dpd-chart')
    work = values['work_summary']
    work_rows = [
        {'label': 'Mới', 'n': work['new_n'], 'url': query.cohort_url('applications', status='new')},
        {'label': 'Đang xem xét', 'n': work['reviewing_n'],
         'url': query.cohort_url('applications', status='in_review')},
        {'label': 'Đã rà soát', 'n': work['reviewed_n'],
         'url': query.cohort_url('applications', status='reviewed')},
    ]
    values['work_chart'] = runtime.charts.workStatus(work_rows, 'work-chart')
    comparison_groups = values['finance_groups']
    comparison_finance = values['finance']
    values['comparison_before_selection'] = False
    # Giữ các nhóm đối chiếu trên chart gốc; KPI/bảng vẫn dùng nhóm vừa chọn.
    if request.args.get(values['breakdown']) and not values['financial_filter'] and not request.args.get('drill_kind'):
        filters = dict(values['cohort_filters'])
        filters[values['breakdown']] = ''
        reference_profiles = CreditRiskStatistic.applyCohortFilters(runtime.get_profiles(), filters)
        reference_bureau = values['portfolio'].readBureau(reference_profiles['source_application_id'].tolist())
        column = 'NAME_INCOME_TYPE' if values['breakdown'] == 'income' else 'NAME_CONTRACT_TYPE'
        comparison_finance = values['portfolio'].bureauReport(reference_bureau, reference_profiles,
            values['financial_currency'], values['credit_status'], column)
        comparison_groups = runtime.records(comparison_finance['groups'])
        labels = runtime.INCOME_TYPES if values['breakdown'] == 'income' else runtime.PRODUCTS
        for row in comparison_groups:
            row['label'] = labels.get(row['segment'], row['segment'] or 'Chưa rõ')
            row['filter_url'] = query.filter_url(values['breakdown'], row['segment']) if row['segment'] in labels else None
        values['comparison_before_selection'] = True
    values['segment_chart'] = runtime.charts.segmentComparison(comparison_groups, comparison_finance['debt'],
                                                       comparison_finance['overdue'], 'segment-chart')
    return render_template('portfolio_overview.html', active='diagnostics', plotly_enabled=True, **values)



def brand_logo():
    return send_file(runtime.ROOT / 'web/static/images/logo_final.webp', mimetype='image/webp', max_age=86400)



def plotly_javascript():
    return send_file(runtime.PLOTLY_JS, mimetype='text/javascript', conditional=True, max_age=86400)



def payment_analysis():
    values = portfolio_views.portfolio_context(include_history=True)
    ids = values['profiles']['source_application_id'].tolist()
    monthly = values['portfolio'].monthlyReport(
        values['portfolio'].readMonthly(ids, values['history_source'], values['months']), values['history_source'])
    values['monthly_report'] = monthly
    values['kpi_minis'] = history_mini_charts(values, monthly)
    values['monthly_rows'] = runtime.records(monthly['monthly'])
    # Chỉ so hai tháng tương đối liền nhau, không coi là MoM theo tháng lịch.
    values['latest_month'] = None
    values['previous_month'] = None
    values['month_difference'] = None
    if values['monthly_rows']:
        latest = max(values['monthly_rows'], key=lambda row: row['MONTHS_BALANCE'])
        values['latest_month'] = latest
        for row in values['monthly_rows']:
            if row['MONTHS_BALANCE'] == latest['MONTHS_BALANCE'] - 1:
                values['previous_month'] = row
                if latest['share'] is not None and row['share'] is not None:
                    values['month_difference'] = latest['share'] - row['share']
                break
    owners = values['profiles'][['source_application_id', 'profile_id', 'case_label']]
    periods = values['payment_report']['data'].merge(owners, left_on='SK_ID_CURR', right_on='source_application_id', how='left', validate='many_to_one')
    cards = values['card_report']['data'].merge(owners, left_on='SK_ID_CURR', right_on='source_application_id', how='left', validate='many_to_one')
    values['payment_rows'] = runtime.records(periods.sort_values('delay_days', ascending=False).head(100))
    values['card_rows'] = runtime.records(cards.sort_values('utilization', ascending=False).head(100))
    values['history_chart'] = runtime.charts.monthly(monthly['monthly'], 'history-chart')
    values['payment_chart'] = runtime.charts.paymentOutcomes(values['payment_report']['distribution'], 'payment-chart')
    values['card_chart'] = runtime.charts.utilizationBins(values['card_report']['distribution'], 'card-chart')
    # Phân khúc theo chính nguồn lịch sử đang xem; đếm rõ đơn vị khoản–tháng.
    group_column = 'NAME_INCOME_TYPE' if values['breakdown'] == 'income' else 'NAME_CONTRACT_TYPE'
    labels = runtime.INCOME_TYPES if values['breakdown'] == 'income' else runtime.PRODUCTS
    owners = values['profiles'][['source_application_id', group_column]]
    history = monthly['data'].merge(owners, left_on='SK_ID_CURR', right_on='source_application_id', how='left', validate='many_to_one')
    groups = history.groupby(group_column, dropna=False).agg(
        profiles_n=('SK_ID_CURR', 'nunique'), loans_n=('loan_id', 'nunique'),
        known_n=('known', 'sum'), overdue_n=('is_overdue', 'sum')).reset_index()
    groups['share'] = groups['overdue_n'] / groups['known_n'].where(groups['known_n'] > 0)
    values['history_groups'] = runtime.records(groups.sort_values('share', ascending=False, na_position='last'))
    for row in values['history_groups']:
        row['label'] = labels.get(row[group_column], row[group_column] or 'Chưa rõ')
        row['url'] = query.cohort_url('applications', **{values['breakdown']: row[group_column]}) if row[group_column] in labels else None
    if values['history_source'] == 'bureau':
        for row in monthly['transitions']:
            for cell in row['cells']:
                cell['url'] = query.cohort_url('applications', financial_filter='transition',
                                         from_state=row['from_state'], to_state=cell['to_state'])
        values['transition_chart'] = runtime.charts.transitions(monthly, 'transition-chart')
    return render_template('payments.html', active='payment_analysis', plotly_enabled=True, **values)



def risk_dashboard():
    canonical = financial_views.redirect_old_financial_scope()
    if canonical is not None:
        return canonical
    if not request.args.get('financial_filter') and not request.args.get('drill_kind'):
        return render_template('financial_dashboard.html', active='risk_dashboard', plotly_enabled=True,
            financial_view=True, **financial_views.financial_context())
    return render_template('portfolio_risk.html', active='risk_dashboard', plotly_enabled=True,
                           **portfolio_views.risk_analytics_context())



def risk_diagnostics():
    values = portfolio_views.portfolio_context()
    predictions = portfolio_views.prediction_context(values['profiles'])
    predictions.pop('filters', None)
    values.update(predictions)
    alerts = values['profiles'].loc[values['profiles']['alert'] == 1]
    valid_alerts = alerts.loc[alerts['bureau_money_n'].fillna(0) > 0]
    values['alert_debt'] = float(valid_alerts['bureau_debt'].sum()) if len(valid_alerts) else None
    values['alert_debt_profiles_n'] = len(valid_alerts)
    ids = values['profiles']['source_application_id'].tolist()
    cards = values['portfolio'].cardReport(values['portfolio'].readCard(ids))
    scatter = values['profiles'][['profile_id', 'case_label', 'source_application_id', 'score', 'alert']].copy()
    scatter = scatter.join(cards['profile_util'].rename('utilization'), on='source_application_id')
    scatter = scatter.dropna(subset=['score', 'utilization'])
    scatter['detail_url'] = scatter['profile_id'].map(
        lambda profile_id: query.cohort_url('application_detail', profile_id=int(profile_id)))
    values['scatter_rows'] = runtime.records(scatter)
    values['score_chart'] = runtime.charts.scores(values['distribution'], runtime.model.threshold, 'score-chart')
    values['scatter_chart'] = runtime.charts.utilizationScore(scatter, runtime.model.threshold, 'utilization-chart')
    for row in values['income_groups']:
        row['label'] = runtime.INCOME_TYPES.get(row['NAME_INCOME_TYPE'], row['NAME_INCOME_TYPE'])
        row['filter_url'] = query.filter_url('income', row['NAME_INCOME_TYPE']) if row['NAME_INCOME_TYPE'] in runtime.INCOME_TYPES else None
    values['risk_segment_chart'] = runtime.charts.riskSegments(values['income_groups'], values['baseline']['alert_share'], 'risk-segment-chart')
    return render_template('risk.html', active='diagnostics', plotly_enabled=True, **values)



def dashboard_details():
    values = portfolio_views.portfolio_context()
    kind = request.args.get('kind', '')
    value = request.args.get('value', '')
    data, columns, unit = select_chart_records(values, kind, value, runtime.model.threshold)
    owners = values['profiles'][['source_application_id', 'profile_id', 'case_label']]
    # Chỉ ghép nhãn sau khi đã chọn đúng quan sát, không nhân bản các khoản/kỳ.
    data = data.drop(columns=['profile_id', 'case_label'], errors='ignore')
    data = data.merge(owners, left_on='SK_ID_CURR', right_on='source_application_id', how='left', validate='many_to_one')
    total = len(data)
    profile_n = int(data['SK_ID_CURR'].nunique())
    page = runtime.positive_id(request.args.get('detail_page', '1'))
    pages = max(1, math.ceil(total / 30))
    page = min(page, pages)
    data = data.sort_values(['SK_ID_CURR'], kind='stable').iloc[(page - 1) * 30:page * 30]
    title = value.replace(':', ' → ') if kind == 'transition' else value
    if kind == 'risk_bin':
        low, high = map(float, value.split(':'))
        title = f'Điểm rủi ro {low:.2%} – {high:.2%}'
    elif kind == 'risk_segment':
        key, label = value.split(':', 1)
        title = f'{SEGMENTS[key]} · {label}'
    return render_template('_chart_details.html', rows=runtime.records(data), columns=columns,
        title=title,
        kind=kind, value=value, unit=unit, total=total, profile_n=profile_n, page=page, pages=pages,
        list_url=query.cohort_url('applications', drill_kind=kind, drill_value=value))



def api_dashboard():
    finance_values = portfolio_views.portfolio_context()
    values = portfolio_views.prediction_context(finance_values['profiles'])
    finance = finance_values['finance']
    values['finance'] = {key: finance[key] for key in ['raw_n', 'loans_n', 'money_n', 'excluded_n',
        'exception_n', 'dpd_n', 'overdue_n', 'debt', 'overdue', 'money_share', 'loan_share']}
    values['credit_currency'] = finance_values['financial_currency']
    values['work_summary'] = finance_values['work_summary']
    values.update(alert_workflow=values['workflow'], credit_amounts=values['amounts'],
                  data_readiness=values['readiness'], minimum_group_n=5,
                  model_version=runtime.model.version, threshold=runtime.model.threshold,
                  csrf_token=session['csrf_token'],
                  scope='Hồ sơ hoạt động sau lọc; mốc so sánh là toàn bộ hồ sơ hoạt động trước lọc, cùng phiên bản.')
    return jsonify(values)



def register_routes(app):
    app.add_url_rule('/analysis/records', view_func=financial_records)
    app.add_url_rule('/analysis/applications/<int:source_id>', view_func=financial_source)
    app.add_url_rule('/', view_func=dashboard)
    app.add_url_rule('/diagnostics', view_func=credit_diagnostics)
    app.add_url_rule('/brand/logo_final.webp', view_func=brand_logo, methods=['GET'])
    app.add_url_rule('/vendor/plotly.min.js', view_func=plotly_javascript)
    app.add_url_rule('/payments', view_func=payment_analysis)
    app.add_url_rule('/risk', view_func=risk_dashboard)
    app.add_url_rule('/risk/diagnostics', view_func=risk_diagnostics)
    app.add_url_rule('/api/dashboard/details', view_func=dashboard_details)
    app.add_url_rule('/api/dashboard', view_func=api_dashboard)
