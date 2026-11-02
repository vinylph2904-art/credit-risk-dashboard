"""Scoring, simulations, model evaluation and scoring history."""
import math
from flask import Response, abort, flash, g, jsonify, redirect, render_template, request, send_file
import pandas as pd
from web.analytics import policy_scenario
from web import runtime
from web import request_helpers as query
from web import presentation
from web import portfolio_context as portfolio_views
from web import financial_context as financial_views
from flask import current_app


def simulate_portfolio():
    if any(request.args.get(name) for name in ['status', 'alert', 'unassigned', 'archived']):
        raise ValueError('Mô phỏng danh mục dùng bộ lọc phân khúc, không lọc theo cảnh báo thật.')
    mode = request.args.get('mode', 'threshold')
    if mode not in ['threshold', 'capacity']:
        raise ValueError('Chế độ mô phỏng không hợp lệ.')
    try:
        threshold = float(request.args.get('threshold', runtime.model.threshold))
        capacity = int(request.args.get('capacity', '20')) if mode == 'capacity' else None
    except (ValueError, TypeError):
        raise ValueError('Ngưỡng và năng lực phải là số hợp lệ.') from None
    if request.args.get('data_scope'):
        if request.args['data_scope'] != 'managed':
            raise ValueError('Mô phỏng rà soát chỉ dùng phạm vi hồ sơ đang quản lý.')
        _, _, _, profiles, _, _, _ = financial_views.financial_data()
    else:
        profiles = portfolio_views.portfolio_context()['profiles']
    result = policy_scenario(profiles, runtime.model.threshold, threshold, capacity,
                             request.args.get('scope', 'backlog'))
    response = current_app.make_response(render_template('_policy_scenario_result.html', result=result))
    response.headers['Cache-Control'] = 'no-store'
    return response



def simulate_profile(profile_id):
    profile = runtime.get_profile(profile_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'changes'}:
        raise ValueError('Gửi các giá trị giả định trong trường changes.')
    source = runtime.get_data().getSourceFeatures(profile['source_application_id'])
    result = runtime.model.simulate(source, payload['changes'])
    response = current_app.make_response(render_template('_profile_scenario_result.html', result=result))
    response.headers['Cache-Control'] = 'no-store'
    return response



def score_application(profile_id):
    runtime.get_profile(profile_id)
    runtime.score_profiles([profile_id])
    flash('Đã chấm điểm và lưu một lần đánh giá mới.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=profile_id))



def score_pending():
    profiles = portfolio_views.portfolio_context()['profiles']
    ids = profiles.loc[profiles['score'].isna(), 'profile_id'].head(200).tolist()
    n = runtime.score_profiles(ids)
    flash(f'Đã chấm {n} hồ sơ chưa có điểm của phiên bản hiện tại.', 'success')
    return redirect(query.cohort_url('risk_dashboard'))



def history():
    profile_id = request.args.get('profile_id', '')
    q = request.args.get('q', '').strip()[:100]
    version = request.args.get('version', '')
    alert = request.args.get('alert', '')
    days = request.args.get('days', '')
    conditions, params = [], []
    if g.current_user['role'] == 'analyst':
        conditions.append('p.assigned_user_id=%s')
        params.append(int(g.current_user['id']))
    if profile_id:
        profile_id = runtime.positive_id(profile_id)
        conditions.append('e.profile_id=%s')
        params.append(profile_id)
    if q:
        pattern = '%' + q.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        conditions.append("(p.case_label LIKE %s ESCAPE '!' OR CAST(p.source_application_id AS CHAR) LIKE %s ESCAPE '!')")
        params.extend([pattern, pattern])
    if version:
        conditions.append('e.model_version=%s')
        params.append(version)
    if alert:
        if alert not in ['0', '1']:
            raise ValueError('Bộ lọc cảnh báo không hợp lệ.')
        conditions.append('e.alert=%s')
        params.append(int(alert))
    if days:
        if days not in ['7', '30']:
            raise ValueError('Khoảng thời gian không hợp lệ.')
        conditions.append('e.scored_at >= UTC_TIMESTAMP() - INTERVAL %s DAY')
        params.append(int(days))
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    source = ' FROM scoring_events e JOIN demo_profiles p USING(profile_id) JOIN application_features f ON f.SK_ID_CURR=p.source_application_id'
    page = runtime.positive_id(request.args.get('page', '1'))
    count = runtime.get_db().queryDataset('SELECT COUNT(*) AS n' + source + where, tuple(params)).iloc[0]['n']
    page = min(page, max(1, math.ceil(count/20)))
    events = runtime.get_db().queryDataset('SELECT e.*, p.case_label, p.source_application_id, p.review_status, p.assignee, f.AMT_CREDIT' + source + where
        + ' ORDER BY e.event_id DESC LIMIT %s OFFSET %s', tuple(params + [20, (page-1)*20]))
    versions = runtime.get_db().queryDataset('SELECT model_version FROM model_versions ORDER BY registered_at DESC')['model_version'].tolist()
    return render_template('history.html', active='history', events=runtime.records(events),
        total=int(count), page=page, pages=max(1, math.ceil(count/20)), profile_id=profile_id,
        q=q, version=version, alert=alert, days=days, versions=versions)



def export_history():
    condition = ' WHERE p.assigned_user_id=%s' if g.current_user['role'] == 'analyst' else ''
    params = (int(g.current_user['id']),) if condition else ()
    events = runtime.get_db().queryDataset('''SELECT e.event_id,p.source_application_id,e.model_version,
        e.score,e.threshold,e.alert,e.input_sha256,e.scored_at
        FROM scoring_events e JOIN demo_profiles p USING(profile_id)''' + condition + ' ORDER BY e.event_id', params)
    return runtime.csv_response(events, 'scoring_history_utc.csv')



def model_info():
    from web.evaluation import historical_charts
    evaluation = runtime.model.metadata.get('evaluation', {})
    folder = evaluation.get('folder', 'reports/modeling')
    dataset = evaluation.get('dataset', 'test')
    metrics = pd.read_csv(runtime.ROOT / folder / evaluation.get('metrics', '04_test_metrics.csv'))
    main = runtime.records(metrics.loc[metrics['policy'] == evaluation.get('policy', 'chosen_5_to_1')])[0]
    importance = pd.read_csv(runtime.ROOT / folder / evaluation.get('importance', '04_base_model_importance.csv')).head(10)
    return render_template('model.html', active='model', metrics=main, policy=runtime.model.metadata,
                           evaluation_dataset=dataset,
                           evaluation_label=evaluation.get('label', 'Historical test evaluation'),
                           model_display_name=runtime.model.metadata.get('display_name', 'Logistic Regression + sigmoid'),
                           plotly_enabled=True, model_analytics=True, importance=runtime.records(importance),
                           evaluation=historical_charts(str(runtime.ROOT), runtime.model.threshold, folder, dataset,
                               evaluation.get('predictions'), evaluation.get('metrics'),
                               evaluation.get('policy'), evaluation.get('threshold_candidates')))



def model_evaluation_image():
    evaluation = runtime.model.metadata.get('evaluation', {})
    return send_file(runtime.ROOT / evaluation.get('folder', 'reports/modeling') /
                     evaluation.get('image', '04_test_evaluation.png'))



def event_input(event_id):
    row = runtime.get_db().queryDataset('SELECT input_snapshot FROM scoring_events WHERE event_id=%s', (event_id,))
    if row.empty:
        abort(404, 'Không tìm thấy lần chấm điểm.')
    return Response(row.iloc[0]['input_snapshot'], mimetype='application/json')



def api_score(profile_id):
    profile = runtime.get_profile(profile_id)
    if request.method == 'POST':
        runtime.score_profiles([profile_id])
        profile = runtime.get_profile(profile_id)
    return jsonify(profile_id=profile_id, source_application_id=profile['source_application_id'],
        scored=profile['event_id'] is not None, event_id=profile['event_id'],
        score=profile['score'], threshold=profile['threshold'],
        alert=bool(profile['alert']) if profile['alert'] is not None else None,
        model_version=runtime.model.version, scored_at=presentation.localtime_format(profile['scored_at']))



def register_routes(app):
    app.add_url_rule('/api/scenarios/portfolio', view_func=simulate_portfolio)
    app.add_url_rule('/api/scenarios/profiles/<int:profile_id>', view_func=simulate_profile, methods=['POST'])
    app.add_url_rule('/applications/<int:profile_id>/score', view_func=score_application, methods=['POST'])
    app.add_url_rule('/score-pending', view_func=score_pending, methods=['POST'])
    app.add_url_rule('/history', view_func=history)
    app.add_url_rule('/history/export', view_func=export_history)
    app.add_url_rule('/model', view_func=model_info)
    app.add_url_rule('/model/evaluation.png', view_func=model_evaluation_image)
    app.add_url_rule('/events/<int:event_id>/input', view_func=event_input)
    app.add_url_rule('/api/profiles/<int:profile_id>/score', view_func=api_score, methods=['GET', 'POST'])
