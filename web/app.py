"""Flask entry point: configure the application and register its modules."""
import argparse
import os
from pathlib import Path
import secrets
import sys

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import runtime
from web.auth import configure_auth
from web.user_routes import configure_user_routes
from web.users import initialize_users
from web.presentation import register_template_filters
from web.hooks import register_hooks
from web import dashboard_routes, application_routes, scoring_routes

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
                  TEMPLATES_AUTO_RELOAD=True,
                  MAX_CONTENT_LENGTH=1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax')
configure_auth(app, lambda: runtime.get_db())
configure_user_routes(app, lambda: runtime.get_db())
register_hooks(app)
register_template_filters(app)
dashboard_routes.register_routes(app)
application_routes.register_routes(app)
scoring_routes.register_routes(app)


def initialize_database(seed_n):
    db = runtime.get_db()
    for statement in (runtime.ROOT / 'sql/03_web_schema.sql').read_text(encoding='utf-8').split(';'):
        if statement.strip():
            db.execute(statement)
    initialize_users(db)
    existing = db.queryDataset('SELECT * FROM model_versions WHERE model_version=%s', (runtime.model.version,))
    if existing.empty:
        db.execute('''INSERT INTO model_versions
            (model_version,case_id,model_path,model_sha256,policy_sha256,feature_n,threshold)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (runtime.model.version, runtime.model.metadata['case_id'], runtime.model.metadata['model_path'], runtime.model.metadata['legacy_registration']['model_sha256'],
             runtime.model.metadata['legacy_registration']['policy_sha256'], len(runtime.model.feature_order), runtime.model.threshold))
    else:
        stored = existing.iloc[0]
        if (stored['case_id'] != runtime.model.metadata['case_id']
                or stored['threshold'] != runtime.model.threshold
                or stored['feature_n'] != len(runtime.model.feature_order)):
            raise ValueError('Phiên bản trong MySQL khác mô hình đang dùng.')
    if seed_n:
        db.execute('''INSERT IGNORE INTO demo_profiles (source_application_id,case_label)
            SELECT SK_ID_CURR,CONCAT('HC-',SK_ID_CURR) FROM application_split
            WHERE dataset_role=%s ORDER BY SK_ID_CURR LIMIT %s''', ('application_test', seed_n))
    print('Khởi tạo xong. Model:', runtime.model.version, '| Hồ sơ demo:', len(runtime.get_profiles()))



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Web minh họa thẩm định tín dụng')
    parser.add_argument('--init-db', action='store_true', help='Tạo bảng và đăng ký model')
    parser.add_argument('--init-users', action='store_true', help='Tạo bảng users và liên kết phân công hồ sơ')
    parser.add_argument('--seed-demo', type=int, default=200, help='Số hồ sơ nguồn tạo demo khi init')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    if not 0 <= args.seed_demo <= 1000:
        parser.error('--seed-demo cần nằm trong khoảng 0 đến 1000')
    if args.init_users:
        with app.app_context():
            initialize_users(runtime.get_db())
        print('Đã khởi tạo tài khoản và phân quyền.')
    elif args.init_db:
        with app.app_context():
            initialize_database(args.seed_demo)
    else:
        app.run(host='127.0.0.1', port=args.port, debug=False)
