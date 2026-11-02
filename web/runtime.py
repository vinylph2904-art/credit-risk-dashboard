"""Shared model, database access and managed profile operations."""
import hashlib
from pathlib import Path
from flask import Response, abort, g
import plotly
from connectors.Connector import Connector
from models.CreditRiskData import CreditRiskData
from models.CreditRiskModel import CreditRiskModel
from web.charts import DashboardCharts
from web.users import find_user


ROOT = Path(__file__).resolve().parents[1]
model = CreditRiskModel(ROOT).loadModel()
charts = DashboardCharts()
STATUSES = {'new': 'Mới', 'in_review': 'Đang xem xét', 'reviewed': 'Đã rà soát'}
PRODUCTS = {'Cash loans': 'Vay tiền mặt', 'Revolving loans': 'Vay quay vòng'}
INCOME_TYPES = {'Working': 'Đi làm', 'Commercial associate': 'Kinh doanh',
                'Pensioner': 'Hưu trí', 'State servant': 'Khu vực nhà nước',
                'Unemployed': 'Chưa có việc làm', 'Student': 'Sinh viên',
                'Businessman': 'Kinh doanh cá nhân', 'Maternity leave': 'Nghỉ thai sản'}
DATA_CHECKS = {'monitored': 'Thiếu ít nhất một trong 5 trường theo dõi',
               'no_bureau': 'Không có bureau đủ điều kiện',
               'bureau_signal': 'Có ghi nhận quá hạn trong lịch sử bureau',
               'installment_signal': 'Có thanh toán sau hạn trong lịch sử kỳ trả nợ',
               'AMT_INCOME_TOTAL': 'Thiếu thu nhập ghi nhận',
               'AMT_ANNUITY': 'Thiếu annuity ghi nhận',
               'EXT_SOURCE_1': 'Thiếu điểm nguồn ngoài 1',
               'EXT_SOURCE_2': 'Thiếu điểm nguồn ngoài 2',
               'EXT_SOURCE_3': 'Thiếu điểm nguồn ngoài 3'}
COHORT_FIELDS = ['product', 'income', 'amount_min', 'amount_max',
                 'age_min', 'age_max', 'availability']
AVAILABILITY = {'monitored': 'Thiếu ít nhất một trong 5 trường theo dõi',
                'no_bureau': 'Không có bureau đủ điều kiện'}
CREDIT_STATES = {'Active': 'Đang hoạt động', 'Closed': 'Đã đóng',
                 'Sold': 'Đã bán khoản', 'Bad debt': 'Bad debt theo nguồn', 'all': 'Tất cả trạng thái'}
FINANCIAL_FILTERS = {'money': 'Khoản có đủ thông tin tiền', 'overdue_money': 'Có tiền quá hạn bureau',
                     'overdue': 'Có DPD bureau > 0', 'dpd90': 'Có DPD bureau trên 90 ngày',
                     'exceptions': 'Thông tin tiền cần kiểm tra', 'card_over': 'Thẻ sử dụng trên hạn mức',
                     'payment_late': 'Có kỳ đã quan sát trả đủ sau hạn', 'transition': 'Chuyển trạng thái lịch sử đã chọn'}
ASSET_VERSION = max((ROOT / 'web/static' / name).stat().st_mtime_ns
                    for name in ['style.css', 'report.css', 'analytics.css', 'app.js', 'report_layout.js', 'scenarios.js', 'kpi_targets.js', 'dashboard_navigation.js', 'chart_interactions.js', 'login.css', 'login.js', 'motion.css', 'product.css', 'glass.css'])
ASSET_VERSION = max(ASSET_VERSION, (ROOT / 'web/static/workspace.css').stat().st_mtime_ns,
                    (ROOT / 'web/static/neumorphism.css').stat().st_mtime_ns,
                    (ROOT / 'web/static/financial_workspace.css').stat().st_mtime_ns,
                    (ROOT / 'web/static/images/logo_final.webp').stat().st_mtime_ns)
PLOTLY_JS = Path(plotly.__file__).resolve().parent / 'package_data' / 'plotly.min.js'
REPORT_CACHE_DIR = ROOT / 'tmp/dashboard_research_cache'
REPORT_QUERY_VERSION = hashlib.sha256((ROOT / 'models/CreditRiskData.py').read_bytes()).hexdigest()


def get_db():
    if 'db' not in g:
        g.db = Connector()
        g.db.connect()
    return g.db



def records(frame):
    return frame.astype(object).where(frame.notna(), None).to_dict('records')



def positive_id(value):
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise ValueError('Mã hồ sơ phải là số nguyên dương.') from None
    if not 0 < number <= 9223372036854775807:
        raise ValueError('Mã hồ sơ nằm ngoài phạm vi hợp lệ.')
    return number



def text_field(value, label, max_length, required=True):
    value = str(value or '').strip()
    if (required and not value) or len(value) > max_length:
        raise ValueError(f'{label} cần có từ 1 đến {max_length} ký tự.' if required
                         else f'{label} tối đa {max_length} ký tự.')
    return value



def get_data():
    if 'credit_data' not in g:
        g.credit_data = CreditRiskData(get_db(), model.version, model.feature_order)
    return g.credit_data



def get_profiles(include_archived=False):
    data = get_data().getProfiles(include_archived)
    if getattr(g, 'current_user', None) and g.current_user['role'] == 'analyst':
        data = data.loc[data['assigned_user_id'] == g.current_user['id']].copy()
    return data



def get_profile(profile_id):
    # Quyền theo ID được kiểm tra tại middleware trước khi gọi route.
    result = get_data().getProfile(positive_id(profile_id))
    if result.empty:
        abort(404, 'Không tìm thấy hồ sơ này.')
    return records(result)[0]



def get_features(profile_ids):
    # ID đến từ route đã kiểm tra quyền hoặc get_profiles() đã giới hạn người dùng.
    data = get_data().getFeatures(profile_ids)
    if len(data) != len(profile_ids):
        abort(409, 'Có hồ sơ không tồn tại hoặc đã được lưu trữ.')
    return data



def score_profiles(profile_ids):
    if not profile_ids:
        return 0
    data = model.prepareInput(get_features(profile_ids))
    scores = model.predict(data)
    return get_data().saveScores(data, scores, model.threshold)



def csv_response(frame, filename):
    frame = frame.copy()
    # Giữ văn bản bắt đầu bằng ký hiệu công thức là văn bản khi mở bằng Excel.
    for column in frame.select_dtypes(include=['object', 'string']).columns:
        frame[column] = frame[column].map(
            lambda value: "'" + value if isinstance(value, str)
            and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
    return Response(frame.to_csv(index=False).encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={filename}'})



def read_assignment(value):
    if not value:
        return None, ''
    user = find_user(get_db(), user_id=positive_id(value))
    if not user or not user['is_active'] or user['role'] != 'analyst':
        raise ValueError('Chọn chuyên viên tín dụng đang hoạt động để phân công.')
    return int(user['id']), user['username']

