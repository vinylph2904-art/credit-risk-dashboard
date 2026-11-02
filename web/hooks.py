"""Request protection, shared template context and error responses."""
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from flask import abort, g, jsonify, render_template, request, session
import mysql.connector
from werkzeug.exceptions import HTTPException
from web.auth import login_page
from web.users import analyst_accounts
from web import runtime
from web import request_helpers as query
from flask import current_app


def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.disConnect()



def check_csrf():
    if request.method == 'GET' and 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(24)
    if request.method == 'POST':
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
        expected = session.get('csrf_token', '')
        if not expected or not hmac.compare_digest(supplied, expected):
            if request.endpoint == 'login':
                return login_page('Phiên đăng nhập đã hết hạn. Vui lòng thử lại.', 400)
            abort(400, 'Phiên thao tác không hợp lệ. Tải lại trang rồi thử lại.')



def common_context():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(24)
    return {'csrf_token': session['csrf_token'],
            'analyst_accounts': analyst_accounts(runtime.get_db()) if getattr(g, 'current_user', None) and g.current_user['role'] == 'risk_manager' else [],
            'model_version': runtime.model.version,
            'model_family': runtime.model.family,
            'model_feature_n': len(runtime.model.feature_order),
            'model_threshold': runtime.model.threshold, 'statuses': runtime.STATUSES,
            'products': runtime.PRODUCTS, 'income_types': runtime.INCOME_TYPES, 'data_checks': runtime.DATA_CHECKS,
            'availability_options': runtime.AVAILABILITY, 'asset_version': runtime.ASSET_VERSION,
            'credit_states': runtime.CREDIT_STATES, 'financial_filters': runtime.FINANCIAL_FILTERS,
            'cohort_url': query.cohort_url,
            'page_url': query.page_url, 'filter_url': query.filter_url,
            'viewed_at': datetime.now(timezone.utc).replace(tzinfo=None)}



def invalid_input(error):
    return render_error(str(error), 400)



def database_error(error):
    if error.errno in [1062, 1451, 1452]:
        return render_error('Dữ liệu trùng hoặc đang có liên kết lịch sử. Kiểm tra lại thao tác.', 409)
    current_app.logger.error('MySQL error number: %s', error.errno)
    return render_error('Chưa kết nối được dữ liệu. Kiểm tra MySQL và cấu hình máy chủ.', 503)



def http_error(error):
    message = error.description
    if error.code == 413:
        message = 'File vượt quá giới hạn 1 MB.'
    return render_error(message, error.code)



def render_error(message, code):
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify(error=message), code
    return render_template('error.html', message=message, code=code, active=''), code



def register_hooks(app):
    @app.url_defaults
    def version_static_assets(endpoint, values):
        if endpoint != 'static' or not values.get('filename'):
            return
        root = runtime.ROOT / 'web/static'
        path = (root / values['filename']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return
        # Read the current content, not a version frozen when the server started.
        values['v'] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    @app.after_request
    def revalidate_static_assets(response):
        if request.endpoint == 'static':
            response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        return response

    app.teardown_appcontext(close_db)
    app.before_request(check_csrf)
    app.context_processor(common_context)
    app.register_error_handler(ValueError, invalid_input)
    app.register_error_handler(mysql.connector.Error, database_error)
    app.register_error_handler(HTTPException, http_error)
