"""Các thao tác quản trị tài khoản, tách khỏi nghiệp vụ tín dụng."""
from flask import abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from web.users import ROLES, USER_FIELDS, audit, find_user, validate_password, validate_username


def configure_user_routes(app, get_db):
    @app.get('/admin/users')
    def users_admin():
        users = get_db().queryDataset(f'SELECT {USER_FIELDS} FROM users ORDER BY id').to_dict('records')
        return render_template('users.html', active='users', users=users)

    @app.post('/admin/users')
    def create_user():
        username = validate_username(request.form.get('username'))
        name = str(request.form.get('full_name', '')).strip()
        role = request.form.get('role')
        password = validate_password(request.form.get('password'))
        if not name or len(name) > 100 or role not in ROLES:
            raise ValueError('Nhập họ tên tối đa 100 ký tự và chọn vai trò hợp lệ.')
        result = get_db().execute('INSERT INTO users (username,password_hash,full_name,role) VALUES (%s,%s,%s,%s)',
                                 (username, generate_password_hash(password), name, role))
        audit(get_db(), int(g.current_user['id']), 'create_user', result['lastrowid'], role)
        flash('Đã tạo tài khoản.', 'success')
        return redirect(url_for('users_admin'))

    @app.post('/admin/users/<int:user_id>/update')
    def update_user(user_id):
        user = find_user(get_db(), user_id=user_id)
        if not user:
            abort(404, 'Không tìm thấy tài khoản.')
        name = str(request.form.get('full_name', '')).strip()
        role = request.form.get('role')
        active = request.form.get('is_active')
        if not name or len(name) > 100 or role not in ROLES or active not in ['0','1']:
            raise ValueError('Thông tin tài khoản không hợp lệ.')
        if user_id == g.current_user['id'] and (role != 'admin' or active != '1'):
            raise ValueError('Không thể tự khóa hoặc đổi vai trò quản trị của chính mình.')
        if user['role'] == 'analyst' and role != 'analyst':
            count = get_db().queryDataset('SELECT COUNT(*) AS n FROM demo_profiles WHERE assigned_user_id=%s', (user_id,))
            if int(count.iloc[0]['n']):
                raise ValueError('Cần phân công lại các hồ sơ của tài khoản trước khi đổi vai trò.')
        changed_access = role != user['role'] or int(active) != user['is_active']
        get_db().execute('UPDATE users SET full_name=%s,role=%s,is_active=%s,session_version=session_version+%s WHERE id=%s',
                         (name, role, int(active), int(changed_access), user_id))
        audit(get_db(), int(g.current_user['id']), 'update_user', user_id, f'role={role}; active={active}')
        flash('Đã cập nhật tài khoản. Thay đổi quyền có hiệu lực ngay.', 'success')
        return redirect(url_for('users_admin'))

    @app.post('/admin/users/<int:user_id>/password')
    def reset_user_password(user_id):
        if not find_user(get_db(), user_id=user_id):
            abort(404, 'Không tìm thấy tài khoản.')
        password = validate_password(request.form.get('password'))
        get_db().execute('UPDATE users SET password_hash=%s,session_version=session_version+1 WHERE id=%s',
                         (generate_password_hash(password), user_id))
        audit(get_db(), int(g.current_user['id']), 'reset_password', user_id)
        if user_id == g.current_user['id']:
            session.clear()
            return redirect(url_for('login'))
        flash('Đã đặt lại mật khẩu và kết thúc các phiên đăng nhập cũ.', 'success')
        return redirect(url_for('users_admin'))

    @app.get('/admin/audit')
    def user_audit_page():
        rows = get_db().queryDataset('''SELECT a.audit_id,u.username AS actor,a.action,
            t.username AS target,a.detail,a.created_at FROM user_audit a
            LEFT JOIN users u ON u.id=a.actor_user_id LEFT JOIN users t ON t.id=a.target_user_id
            ORDER BY a.audit_id DESC LIMIT 200''').to_dict('records')
        return render_template('user_audit.html', active='user_audit', rows=rows)

    @app.get('/account')
    def account_profile():
        return render_template('account_profile.html', active='account')

    @app.route('/account/password', methods=['GET','POST'])
    def change_password():
        if request.method == 'POST':
            user = find_user(get_db(), user_id=int(g.current_user['id']), include_password=True)
            if not check_password_hash(user['password_hash'], request.form.get('current_password','')):
                raise ValueError('Mật khẩu hiện tại chưa đúng.')
            password = validate_password(request.form.get('password'))
            if password != request.form.get('confirm_password'):
                raise ValueError('Mật khẩu xác nhận chưa khớp.')
            get_db().execute('UPDATE users SET password_hash=%s,session_version=session_version+1 WHERE id=%s',
                             (generate_password_hash(password), int(user['id'])))
            audit(get_db(), int(user['id']), 'change_password', int(user['id']))
            session.clear()
            flash('Đã đổi mật khẩu. Vui lòng đăng nhập lại.', 'success')
            return redirect(url_for('login'))
        return render_template('change_password.html', active='account')
