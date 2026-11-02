"""Truy vấn tài khoản và khởi tạo phân quyền, không sửa dữ liệu mô hình."""
import os
import re
from pathlib import Path

from werkzeug.security import generate_password_hash

ROLES = {'admin': 'Quản trị hệ thống', 'risk_manager': 'Trưởng bộ phận rủi ro',
         'analyst': 'Chuyên viên tín dụng'}
USER_FIELDS = 'id,username,full_name,role,is_active,session_version,created_at'


def find_user(db, user_id=None, username=None, include_password=False):
    fields = USER_FIELDS + (',password_hash' if include_password else '')
    key, value = ('id', user_id) if user_id is not None else ('username', username)
    rows = db.queryDataset(f'SELECT {fields} FROM users WHERE {key}=%s', (value,))
    return None if rows.empty else rows.iloc[0].to_dict()


def analyst_accounts(db):
    return db.queryDataset("SELECT id,username,full_name FROM users WHERE role='analyst' AND is_active=1 ORDER BY full_name,id").to_dict('records')


def validate_username(value):
    value = str(value or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,79}', value):
        raise ValueError('Tên đăng nhập gồm 3–80 ký tự: chữ không dấu, số, dấu chấm, gạch ngang hoặc gạch dưới.')
    return value


def validate_password(value):
    value = str(value or '')
    if not 8 <= len(value) <= 256:
        raise ValueError('Mật khẩu cần có từ 8 đến 256 ký tự.')
    return value


def audit(db, actor_id, action, target_id=None, detail=''):
    db.execute('INSERT INTO user_audit (actor_user_id,action,target_user_id,detail) VALUES (%s,%s,%s,%s)',
               (actor_id, action, target_id, detail[:255]))


def initialize_users(db):
    root = Path(__file__).resolve().parents[1]
    for statement in (root / 'sql/05_users.sql').read_text(encoding='utf-8').split(';'):
        if statement.strip():
            db.execute(statement)
    columns = db.queryDataset("SHOW COLUMNS FROM demo_profiles LIKE 'assigned_user_id'")
    if columns.empty:
        db.execute('ALTER TABLE demo_profiles ADD COLUMN assigned_user_id BIGINT NULL, '
                   'ADD INDEX ix_profile_assigned (assigned_user_id,is_archived), '
                   'ADD CONSTRAINT fk_profile_assigned FOREIGN KEY (assigned_user_id) REFERENCES users(id) ON DELETE RESTRICT')
    # Chỉ tạo tài khoản mẫu trên database chưa có người dùng. Chạy lại không đổi mật khẩu.
    if int(db.queryDataset('SELECT COUNT(*) AS n FROM users').iloc[0]['n']) == 0:
        for username, name, role, variable in [
            ('admin', 'Quản trị hệ thống', 'admin', 'HC_ADMIN_PASSWORD'),
            ('risk_manager', 'Trưởng bộ phận rủi ro', 'risk_manager', 'HC_MANAGER_PASSWORD'),
            ('analyst', 'Chuyên viên tín dụng', 'analyst', 'HC_DASHBOARD_PASSWORD')]:
            password = validate_password(os.environ.get(variable, 'HomeCredit@123'))
            db.execute('INSERT INTO users (username,password_hash,full_name,role) VALUES (%s,%s,%s,%s)',
                       (username, generate_password_hash(password), name, role))
        audit(db, None, 'initialize_users', detail='Tạo ba tài khoản minh họa ban đầu')
