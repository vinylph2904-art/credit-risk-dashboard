"""Managed profile list, imports, assignments and notes."""
import math
from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
import pandas as pd
from models.CreditRiskStatistic import CreditRiskStatistic
from models.CreditRiskPortfolio import CreditRiskPortfolio
from web.users import find_user
from web.analytics import base_model_contributions
from web.file_transfer import read_profile_file, excel_response, pdf_response
from web import runtime
from web import request_helpers as query
from web import portfolio_context as portfolio_views


def apply_queue_score_filter(data):
    low_text, high_text = request.args.get('score_min', ''), request.args.get('score_max', '')
    if not low_text and not high_text:
        return data
    try:
        low = float(low_text) if low_text else 0.0
        high = float(high_text) if high_text else 1.0
    except ValueError:
        raise ValueError('Điểm lọc phải là số trong 0–1.') from None
    if not (math.isfinite(low) and math.isfinite(high) and 0 <= low <= high <= 1):
        raise ValueError('Khoảng điểm lọc phải nằm trong 0–1, từ không lớn hơn đến.')
    return data.loc[data['score'].between(low, high)].copy()



def applications():
    archived = request.args.get('archived') == '1'
    values = portfolio_views.portfolio_context(include_archived=archived)
    filters = values['cohort_filters']
    data = values['profiles']
    q = request.args.get('q', '').strip()
    product, income = filters['product'], filters['income']
    status = request.args.get('status', '')
    alert = request.args.get('alert', '')
    unassigned = request.args.get('unassigned') == '1'
    data_check = request.args.get('data_check', '')
    sort = request.args.get('sort', 'score')
    assignee = request.args.get('assignee', '').strip()
    if assignee:
        data = data.loc[data['assignee'] == assignee].copy()
    queue_base = CreditRiskStatistic.filterApplications(data, q=q, status='',
        alert='', unassigned=False, data_check=data_check,
        statuses=runtime.STATUSES, data_checks=runtime.DATA_CHECKS)
    queue_base = apply_queue_score_filter(queue_base)
    queue_options = [
        ('all', 'Tất cả', {}, len(queue_base)),
        ('unscored', 'Chưa chấm', {'alert': 'unscored'}, int(queue_base['score'].isna().sum())),
        ('alert', 'Có cảnh báo', {'alert': '1'}, int(queue_base['alert'].eq(1).sum())),
        ('pending', 'Chưa hoàn tất', {'status': 'pending'}, int(queue_base['review_status'].ne('reviewed').sum())),
        ('unassigned', 'Chưa phân công', {'unassigned': '1'}, int(queue_base['assignee'].fillna('').str.strip().eq('').sum())),
    ]
    queue_tabs = []
    current_queue = {key: request.args[key] for key in ('alert', 'status', 'unassigned') if request.args.get(key)}
    for key, label, selection, count in queue_options:
        params = {key: value for key, value in request.args.items()
                  if key not in ('page', 'alert', 'status', 'unassigned')}
        queue_tabs.append({'key': key, 'label': label, 'count': count,
                           'active': current_queue == selection,
                           'url': url_for('applications', **dict(params, **selection))})
    data = CreditRiskStatistic.filterApplications(data, q=q, status=status,
        alert=alert, unassigned=unassigned, data_check=data_check,
        statuses=runtime.STATUSES, data_checks=runtime.DATA_CHECKS)
    data = apply_queue_score_filter(data)
    view = request.args.get('view', '')
    if view not in ['', 'assessment']:
        raise ValueError('Chế độ xem hồ sơ không hợp lệ.')
    summary = CreditRiskStatistic(data, runtime.model.threshold).summary()
    summary['reviewed_n'] = int((data['review_status'] == 'reviewed').sum())
    if sort not in ['score', 'amount']:
        raise ValueError('Cách sắp xếp không hợp lệ.')
    sort_column = 'AMT_CREDIT' if sort == 'amount' else 'score'
    data = data.sort_values([sort_column, 'source_application_id'], ascending=[False, True], na_position='last')
    page = runtime.positive_id(request.args.get('page', '1'))
    page_size = runtime.positive_id(request.args.get('page_size', '15'))
    if page_size not in [15, 30, 50, 100]:
        raise ValueError('Số hồ sơ mỗi trang không hợp lệ.')
    total = len(data)
    page = min(page, max(1, math.ceil(total/page_size)))
    return render_template('applications.html', active='assessment', view=view,
        profiles=runtime.records(data.iloc[(page-1)*page_size:page*page_size]), total=total, page=page,
        queue_tabs=queue_tabs, scope_total=len(runtime.get_profiles(archived)),
        pages=max(1, math.ceil(total/page_size)), q=q, product=product, status=status,
        alert=alert, archived=archived, unassigned=unassigned, page_size=page_size,
        income=income, data_check=data_check, sort=sort,
        cohort_filters=filters, work_summary=values['work_summary'], workload=values['workload'],
        assignee=assignee, assignees=sorted(values['profiles']['assignee'].loc[values['profiles']['assignee'].str.strip() != ''].unique()),
        financial_currency=values['financial_currency'], currency_options=values['currency_options'],
        credit_status=values['credit_status'], financial_filter=values['financial_filter'],
        start_n=(page-1)*page_size+1 if total else 0, end_n=min(page*page_size,total), summary=summary,
        score_min=request.args.get('score_min', ''), score_max=request.args.get('score_max', ''))


def application_suggestions():
    """Return a small, permission-scoped set of matching managed profiles."""
    term = request.args.get('q', '').strip()[:100]
    if not term:
        return jsonify(results=[])
    archived = request.args.get('archived') == '1'
    data = runtime.get_profiles(include_archived=archived)
    matches_id = data['source_application_id'].astype(str).str.contains(term, regex=False)
    matches_label = data['case_label'].fillna('').str.contains(term, case=False, regex=False)
    matches = data.loc[matches_id | matches_label].copy()
    if matches.empty:
        return jsonify(results=[])
    # Prefer names that begin with the query, then keep a stable source ID order.
    label_prefix = matches['case_label'].fillna('').str.casefold().str.startswith(term.casefold())
    matches['_label_prefix'] = label_prefix
    matches = matches.sort_values(['_label_prefix', 'source_application_id'], ascending=[False, True]).head(8)
    return jsonify(results=[{
        'profile_id': int(row.profile_id),
        'source_application_id': int(row.source_application_id),
        'case_label': str(row.case_label) if pd.notna(row.case_label) and str(row.case_label).strip() else f'HC-{row.source_application_id}',
        'review_status': runtime.STATUSES.get(row.review_status, row.review_status),
        'url': url_for('application_detail', profile_id=int(row.profile_id)),
    } for row in matches.itertuples()])



def batch_applications():
    ids = [runtime.positive_id(value) for value in request.form.getlist('profile_ids')]
    if not ids or len(ids) > 100 or len(ids) != len(set(ids)):
        raise ValueError('Chọn từ 1 đến 100 hồ sơ khác nhau.')
    action = request.form.get('action')
    if action == 'score':
        count = runtime.score_profiles(ids)
        flash(f'Đã chấm điểm {count} hồ sơ được chọn.', 'success')
    elif action == 'assign':
        assigned_id, assignee = runtime.read_assignment(request.form.get('assigned_user_id'))
        placeholders = ','.join(['%s'] * len(ids))
        available = runtime.get_db().queryDataset(f'SELECT profile_id FROM demo_profiles WHERE is_archived=0 AND profile_id IN ({placeholders})', tuple(ids))
        if len(available) != len(ids):
            abort(409, 'Có hồ sơ không tồn tại hoặc đã lưu trữ.')
        runtime.get_db().executeMany('UPDATE demo_profiles SET assigned_user_id=%s,assignee=%s WHERE profile_id=%s', [(assigned_id, assignee, value) for value in ids])
        flash(f'Đã phân công {len(ids)} hồ sơ.', 'success')
    else:
        raise ValueError('Chọn thao tác hợp lệ cho nhóm hồ sơ.')
    return redirect(query.cohort_url('applications'))



def add_application():
    source_id = runtime.positive_id(request.form.get('source_application_id'))
    source = runtime.get_db().queryDataset('SELECT dataset_role FROM application_split WHERE SK_ID_CURR=%s', (source_id,))
    if source.empty or source.iloc[0]['dataset_role'] != 'application_test':
        raise ValueError('Chọn mã nguồn có sẵn trong application_test để tạo hồ sơ.')
    label = runtime.text_field(request.form.get('case_label') or f'HC-{source_id}', 'Tên hồ sơ', 100)
    assigned_id, assignee = runtime.read_assignment(request.form.get('assigned_user_id'))
    result = runtime.get_db().execute('INSERT INTO demo_profiles (source_application_id,case_label,assignee,assigned_user_id) VALUES (%s,%s,%s,%s)',
                              (source_id, label, assignee, assigned_id))
    flash('Đã thêm hồ sơ.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=result['lastrowid']))



def application_detail(profile_id):
    profile = runtime.get_profile(profile_id)
    # Hồ sơ lưu trữ vẫn xem được đầu vào và lịch sử.
    raw = runtime.get_data().getSourceFeatures(profile['source_application_id'])
    data = raw.loc[:, runtime.model.feature_order]
    feature = runtime.records(raw)[0]
    latest = profile if profile['event_id'] is not None else None
    events = runtime.get_data().getEvents(profile_id)
    notes = runtime.get_data().getNotes(profile_id)
    dictionary = pd.read_csv(runtime.ROOT / 'data/metadata/feature_dictionary.csv').set_index('feature')
    feature_rows = [{'name': name, 'value': feature[name], 'meaning': dictionary.loc[name, 'meaning']}
                    for name in runtime.model.feature_order]
    portfolio = CreditRiskPortfolio(runtime.get_db())
    bureau = portfolio.readBureau([profile['source_application_id']])
    currency = request.args.get('currency', 'currency 1')
    credit_status = request.args.get('credit_status', 'Active')
    if currency not in ['currency 1', 'currency 2', 'currency 3', 'currency 4'] or credit_status not in runtime.CREDIT_STATES:
        raise ValueError('Điều kiện khoản bureau không hợp lệ.')
    finance = portfolio.bureauReport(bureau, pd.DataFrame([profile]), currency, credit_status)
    return render_template('detail.html', active='assessment', profile=profile,
        feature=feature, feature_rows=feature_rows, missing_n=int(data.isna().sum().sum()),
        suggestions=CreditRiskStatistic.recommendations(feature, latest),
        events=runtime.records(events), notes=runtime.records(notes), finance=finance,
        contributions=base_model_contributions(runtime.model, data),
        financial_currency=currency, credit_status=credit_status, bureau_rows=runtime.records(finance['data']))



def export_features(profile_id):
    profile = runtime.get_profile(profile_id)
    data = runtime.get_data().getSourceFeatures(profile['source_application_id']).loc[:, runtime.model.feature_order]
    return runtime.csv_response(data, f"features_{profile['source_application_id']}.csv")



def update_application(profile_id):
    profile = runtime.get_profile(profile_id)
    label = runtime.text_field(request.form.get('case_label', profile['case_label']), 'Tên hồ sơ', 100)
    if g.current_user['role'] == 'risk_manager':
        assigned_id, assignee = runtime.read_assignment(request.form.get('assigned_user_id'))
    else:
        if 'assigned_user_id' in request.form or 'assignee' in request.form:
            abort(403, 'Chỉ trưởng bộ phận được thay đổi phân công.')
        assigned_id, assignee = profile['assigned_user_id'], profile['assignee']
    status = request.form.get('review_status', '')
    if status not in runtime.STATUSES:
        raise ValueError('Trạng thái rà soát không hợp lệ.')
    runtime.get_db().execute('UPDATE demo_profiles SET case_label=%s,assignee=%s,assigned_user_id=%s,review_status=%s WHERE profile_id=%s',
                     (label, assignee, assigned_id, status, profile_id))
    flash('Đã cập nhật thông tin quản lý.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=profile_id))



def archive_application(profile_id):
    profile = runtime.get_profile(profile_id)
    runtime.get_db().execute('UPDATE demo_profiles SET is_archived=%s WHERE profile_id=%s',
                     (1-int(profile['is_archived']), profile_id))
    flash('Đã cập nhật trạng thái lưu trữ.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=profile_id))



def delete_application(profile_id):
    runtime.get_profile(profile_id)
    count = runtime.get_db().queryDataset('SELECT COUNT(*) AS n FROM scoring_events WHERE profile_id=%s', (profile_id,)).iloc[0]['n']
    if count:
        abort(409, 'Hồ sơ đã có lịch sử chấm. Dùng chức năng lưu trữ để giữ dấu vết.')
    runtime.get_db().execute('DELETE FROM demo_profiles WHERE profile_id=%s', (profile_id,))
    flash('Đã xóa hồ sơ chưa có lịch sử.', 'success')
    return redirect(query.cohort_url('applications'))



def note_profile(note_id):
    result = runtime.get_data().getNoteProfile(note_id)
    if result.empty:
        abort(404, 'Không tìm thấy ghi chú.')
    return int(result.iloc[0]['profile_id'])



def add_note(event_id):
    event = runtime.get_db().queryDataset('SELECT profile_id FROM scoring_events WHERE event_id=%s', (event_id,))
    if event.empty:
        abort(404, 'Không tìm thấy lần chấm điểm.')
    author = g.current_user['username']
    content = runtime.text_field(request.form.get('content'), 'Nội dung', 2000)
    runtime.get_db().execute('INSERT INTO review_notes (event_id,author,content) VALUES (%s,%s,%s)', (event_id, author, content))
    flash('Đã lưu ghi chú thẩm định.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=int(event.iloc[0]['profile_id'])))



def update_note(note_id):
    profile_id = note_profile(note_id)
    content = runtime.text_field(request.form.get('content'), 'Nội dung', 2000)
    runtime.get_db().execute('UPDATE review_notes SET content=%s WHERE note_id=%s', (content, note_id))
    flash('Đã sửa ghi chú.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=profile_id))



def delete_note(note_id):
    profile_id = note_profile(note_id)
    runtime.get_db().execute('DELETE FROM review_notes WHERE note_id=%s', (note_id,))
    flash('Đã xóa ghi chú.', 'success')
    return redirect(query.cohort_url('application_detail', profile_id=profile_id))



def import_applications():
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        raise ValueError('Chọn file CSV hoặc Excel .xlsx theo mẫu.')
    frame = read_profile_file(upload)
    columns = ['source_application_id', 'case_label', 'assignee', 'review_status']
    if list(frame.columns) != columns or not 0 < len(frame) <= 1000:
        raise ValueError('File nhập phải đúng bốn cột của mẫu và có từ 1 đến 1.000 dòng.')
    rows = []
    for row in frame.itertuples(index=False):
        source_id = runtime.positive_id(row.source_application_id)
        label = runtime.text_field(row.case_label or f'HC-{source_id}', 'Tên hồ sơ', 100)
        assigned_user = find_user(runtime.get_db(), username=row.assignee) if row.assignee else None
        assigned_id, assignee = runtime.read_assignment(str(assigned_user['id']) if assigned_user else '')
        if row.assignee and not assigned_user:
            raise ValueError('Người phụ trách trong file phải là tên đăng nhập chuyên viên đang hoạt động.')
        if row.review_status not in runtime.STATUSES:
            raise ValueError('File chứa trạng thái không hợp lệ.')
        rows.append((source_id, label, assignee, row.review_status, assigned_id))
    ids = [row[0] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('File có mã nguồn trùng lặp.')
    placeholders = ','.join(['%s'] * len(ids))
    valid = runtime.get_db().queryDataset(f'SELECT SK_ID_CURR FROM application_split WHERE dataset_role=%s AND SK_ID_CURR IN ({placeholders})',
                                 tuple(['application_test'] + ids))
    if set(valid['SK_ID_CURR']) != set(ids):
        raise ValueError('Mọi mã nguồn phải thuộc application_test và có sẵn trong MySQL.')
    existing = runtime.get_db().queryDataset(f'SELECT source_application_id FROM demo_profiles WHERE source_application_id IN ({placeholders})', tuple(ids))
    if not existing.empty:
        abort(409, 'File chứa hồ sơ đã có trong danh sách. Chưa nhập dòng nào.')
    runtime.get_db().executeMany('INSERT INTO demo_profiles (source_application_id,case_label,assignee,review_status,assigned_user_id) VALUES (%s,%s,%s,%s,%s)', rows)
    flash(f'Đã nhập {len(rows)} hồ sơ.', 'success')
    return redirect(query.cohort_url('applications'))



def export_applications():
    file_format = request.args.get('format', 'csv')
    if file_format not in ['csv', 'xlsx', 'pdf']:
        raise ValueError('Chọn định dạng CSV, Excel .xlsx hoặc PDF.')
    if request.args.get('scope') == 'all':
        data = runtime.get_profiles(include_archived=True)
    else:
        data = portfolio_views.portfolio_context(include_archived=request.args.get('archived') == '1')['profiles']
        data = CreditRiskStatistic.filterApplications(data,
            q=request.args.get('q', '').strip(), status=request.args.get('status', ''),
            alert=request.args.get('alert', ''), unassigned=request.args.get('unassigned') == '1',
            data_check=request.args.get('data_check', ''), statuses=runtime.STATUSES, data_checks=runtime.DATA_CHECKS)
        assignee = request.args.get('assignee', '').strip()
        if assignee:
            data = data.loc[data['assignee'] == assignee]
        data = apply_queue_score_filter(data)
    sort_column = 'AMT_CREDIT' if request.args.get('sort') == 'amount' else 'score'
    data = data.sort_values([sort_column, 'source_application_id'], ascending=[False, True], na_position='last')
    frame = data[['source_application_id', 'case_label', 'assignee', 'review_status',
                  'is_archived', 'score', 'threshold', 'alert', 'AMT_CREDIT', 'scored_at']]
    if file_format == 'xlsx':
        return excel_response(frame, 'profiles.xlsx')
    if file_format == 'pdf':
        return pdf_response(frame, 'profiles.pdf')
    return runtime.csv_response(frame, 'profiles.csv')



def application_template():
    file_format = request.args.get('format', 'csv')
    if file_format not in ['csv', 'xlsx']:
        raise ValueError('Mẫu nhập hỗ trợ CSV hoặc Excel .xlsx.')
    data = runtime.get_db().queryDataset('''SELECT s.SK_ID_CURR AS source_application_id
        FROM application_split s LEFT JOIN demo_profiles p ON p.source_application_id=s.SK_ID_CURR
        WHERE s.dataset_role=%s AND p.profile_id IS NULL ORDER BY s.SK_ID_CURR LIMIT 3''', ('application_test',))
    data['case_label'] = ''
    data['assignee'] = ''
    data['review_status'] = 'new'
    if file_format == 'xlsx':
        return excel_response(data, 'profile_template.xlsx')
    return runtime.csv_response(data, 'profile_template.csv')



def register_routes(app):
    app.add_url_rule('/applications', view_func=applications)
    app.add_url_rule('/api/applications/suggestions', view_func=application_suggestions)
    app.add_url_rule('/applications/batch', view_func=batch_applications, methods=['POST'])
    app.add_url_rule('/applications', view_func=add_application, methods=['POST'])
    app.add_url_rule('/applications/<int:profile_id>', view_func=application_detail)
    app.add_url_rule('/applications/<int:profile_id>/features.csv', view_func=export_features)
    app.add_url_rule('/applications/<int:profile_id>/update', view_func=update_application, methods=['POST'])
    app.add_url_rule('/applications/<int:profile_id>/archive', view_func=archive_application, methods=['POST'])
    app.add_url_rule('/applications/<int:profile_id>/delete', view_func=delete_application, methods=['POST'])
    app.add_url_rule('/events/<int:event_id>/notes', view_func=add_note, methods=['POST'])
    app.add_url_rule('/notes/<int:note_id>/update', view_func=update_note, methods=['POST'])
    app.add_url_rule('/notes/<int:note_id>/delete', view_func=delete_note, methods=['POST'])
    app.add_url_rule('/applications/import', view_func=import_applications, methods=['POST'])
    app.add_url_rule('/applications/export', view_func=export_applications)
    app.add_url_rule('/applications/template', view_func=application_template)
