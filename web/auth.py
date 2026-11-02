"""Đăng nhập database và kiểm tra quyền cho mọi trang/API."""
from datetime import timedelta
import secrets
from urllib.parse import unquote, urlsplit

from flask import abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from web.users import ROLES, find_user, audit

COMMON = {'dashboard','risk_dashboard','model_info','model_evaluation_image',
          'applications','application_suggestions','application_detail','export_features','simulate_profile',
          'update_application','score_application','batch_applications','score_pending',
          'add_note','update_note','delete_note','export_applications','history',
          'export_history','event_input','api_score','logout','change_password','account_profile'}
MANAGER = {'financial_records','financial_source','credit_diagnostics','payment_analysis',
           'risk_diagnostics','dashboard_details','api_dashboard','simulate_portfolio',
           'add_application','archive_application','delete_application','import_applications',
           'application_template'}
ADMIN = {'users_admin','create_user','update_user','reset_user_password','user_audit_page','logout','change_password','account_profile'}


def home_endpoint():
    return 'users_admin' if (getattr(g, 'current_user', None) or {}).get('role') == 'admin' else 'dashboard'


def require_profile_access(db, profile_id):
    rows = db.queryDataset('SELECT assigned_user_id FROM demo_profiles WHERE profile_id=%s', (profile_id,))
    if rows.empty:
        abort(404, 'Không tìm thấy hồ sơ.')
    if g.current_user['role'] != 'risk_manager' and rows.iloc[0]['assigned_user_id'] != g.current_user['id']:
        abort(403, 'Bạn chỉ được truy cập hồ sơ được phân công.')


def enforce_permission(db):
    endpoint = request.endpoint
    role = g.current_user['role']
    allowed = ADMIN if role == 'admin' else COMMON | (MANAGER if role == 'risk_manager' else set())
    if endpoint not in allowed:
        abort(403, 'Tài khoản không có quyền sử dụng chức năng này.')
    values = request.view_args or {}
    if 'profile_id' in values:
        require_profile_access(db, values['profile_id'])
    if 'event_id' in values or 'note_id' in values:
        if 'event_id' in values:
            rows = db.queryDataset('SELECT profile_id FROM scoring_events WHERE event_id=%s', (values['event_id'],))
        else:
            rows = db.queryDataset('SELECT e.profile_id,n.author FROM review_notes n JOIN scoring_events e USING(event_id) WHERE n.note_id=%s', (values['note_id'],))
        if rows.empty:
            abort(404, 'Không tìm thấy dữ liệu tác nghiệp.')
        require_profile_access(db, int(rows.iloc[0]['profile_id']))
        if role == 'analyst' and 'note_id' in values and rows.iloc[0]['author'] != g.current_user['username']:
            abort(403, 'Bạn chỉ được sửa hoặc xóa ghi chú do mình tạo.')
    if endpoint == 'batch_applications':
        if request.form.get('action') == 'assign' and role != 'risk_manager':
            abort(403, 'Chỉ trưởng bộ phận được phân công hồ sơ.')
        for value in request.form.getlist('profile_ids'):
            if not value.isdigit():
                abort(400, 'Mã hồ sơ không hợp lệ.')
            require_profile_access(db, int(value))


def safe_next_url(value):
    value = str(value or '')
    decoded = unquote(value)
    if (not decoded.startswith('/') or decoded.startswith('//') or '\\' in decoded
            or len(value) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in decoded)):
        return url_for('dashboard')
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc or parts.path in ['/login', '/logout']:
        return url_for('dashboard')
    return value


def login_page(error=None, status=200):
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(24)
    return render_template('login.html', login_error=error,
        login_username=request.form.get('username', '')[:80],
        next_url=safe_next_url(request.form.get('next') or request.args.get('next'))), status


def configure_auth(app, get_db):
    app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    dummy_hash = generate_password_hash(secrets.token_hex(24))

    @app.before_request
    def require_login():
        g.current_user = None
        if request.endpoint in [None, 'static', 'brand_logo']:
            return None
        user_id = session.get('user_id')
        user = find_user(get_db(), user_id=user_id) if user_id else None
        if user and user['is_active'] and user['role'] in ROLES and session.get('session_version') == user['session_version']:
            g.current_user = user
        elif user_id:
            session.clear()
        if request.endpoint == 'login':
            return None
        if g.current_user:
            if request.endpoint == 'dashboard' and user['role'] == 'admin':
                return redirect(url_for('users_admin'))
            if request.endpoint == 'plotly_javascript':
                return None
            enforce_permission(get_db())
            return None
        target = safe_next_url(request.full_path.rstrip('?'))
        location = url_for('login', next=target)
        if request.path.startswith('/api/') or request.method != 'GET':
            return jsonify(error='Vui lòng đăng nhập để tiếp tục.', login_url=location), 401
        return redirect(location)

    @app.after_request
    def private_pages(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
            response.vary.add('Cookie')
        return response

    @app.context_processor
    def login_context():
        user = getattr(g, 'current_user', None)
        return {'signed_in_user': user['username'] if user else None,
                'user_display_name': user['full_name'] if user else '',
                'current_user': user, 'roles': ROLES,
                'is_manager': bool(user and user['role'] == 'risk_manager'),
                'is_admin': bool(user and user['role'] == 'admin'),
                'home_endpoint': home_endpoint()}

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        target = safe_next_url(request.form.get('next') or request.args.get('next'))
        if g.current_user:
            return redirect(url_for(home_endpoint()))
        if request.method == 'POST':
            entered_username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not entered_username or len(entered_username) > 80 or not password or len(password) > 256:
                return login_page('Vui lòng nhập tên đăng nhập và mật khẩu hợp lệ.', 400)
            user = find_user(get_db(), username=entered_username, include_password=True)
            valid_password = check_password_hash(user['password_hash'] if user else dummy_hash, password)
            if not (user and valid_password and user['is_active'] and user['role'] in ROLES):
                return login_page('Tên đăng nhập hoặc mật khẩu chưa đúng.', 401)
            session.clear()
            session.permanent = True
            session['user_id'] = int(user['id'])
            session['session_version'] = int(user['session_version'])
            session['auth_user'] = user['username']
            session['csrf_token'] = secrets.token_hex(24)
            g.current_user = user
            audit(get_db(), int(user['id']), 'login')
            if user['role'] == 'admin':
                return redirect(url_for('users_admin'))
            return redirect(target)
        return login_page()

    @app.post('/logout')
    def logout():
        audit(get_db(), int(g.current_user['id']), 'logout')
        session.clear()
        return redirect(url_for('login'))
