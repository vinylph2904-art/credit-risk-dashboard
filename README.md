# Credit Risk Analytics Dashboard

Ứng dụng phân tích danh mục vay và hỗ trợ rà soát hồ sơ trên bộ dữ liệu Home Credit
Default Risk. Người dùng có thể xem tình hình tài chính, chấm điểm từng hồ sơ và
theo dõi kết quả rà soát ngay trên dashboard.

Phần web được viết bằng Flask, dữ liệu lưu trong MySQL và điểm rủi ro được tính
bằng CatBoost. Repo cũng có tám notebook trình bày các bước từ tìm hiểu dữ liệu
đến huấn luyện, đánh giá và giải thích mô hình.

**Mô hình đã được đóng gói sẵn, không cần huấn luyện lại để chạy web.** File
`.joblib` đi kèm metadata, thứ tự đặc trưng và ngưỡng cảnh báo. Bạn chỉ cần cài
thư viện và khôi phục database theo hướng dẫn bên dưới.

## Chức năng

- Xem tổng quan tài chính, cơ cấu danh mục, dư nợ quá hạn và lịch sử thanh toán.
- Chấm điểm hồ sơ, xem đóng góp của các đặc trưng qua SHAP và thử thay đổi đầu vào.
- Theo dõi lịch sử chấm điểm, ghi chú thẩm định và trạng thái rà soát.
- Quản lý truy cập theo ba vai trò: quản trị viên, trưởng bộ phận và chuyên viên.
- Xuất dữ liệu hồ sơ và xem thông tin, kết quả đánh giá mô hình.

Trong chi tiết hồ sơ, mở **Mô phỏng thu nhập, khoản vay và niên kim** để sửa cùng
lúc cả ba giá trị rồi bấm **Chấm thử**. Trường không muốn đổi giữ giá trị hiện tại;
cả ba giá trị phải lớn hơn 0. Hệ thống tính lại các tỷ số liên quan, hiển thị điểm
trước/sau và cảnh báo. **Đặt lại** khôi phục các giá trị ban đầu; mô phỏng không lưu
thay đổi vào hồ sơ.

## Mô hình và kết quả

| Thành phần | Thiết lập |
|---|---|
| Mô hình đang dùng | CatBoost, depth 6, 500 vòng |
| Số đặc trưng | 182 |
| Ngưỡng cảnh báo | 0,145394 |
| Phân tập nội bộ | Train 60% / validation 20% / test 20%, seed 42 |
| So sánh thực nghiệm | 21 cấu hình thuộc sáu họ mô hình, ba CV fold trên train |
| AP trên test lịch sử | 0,280743 |
| ROC-AUC trên test lịch sử | 0,781073 |

Mô hình cuối được huấn luyện trên train. Ngưỡng cảnh báo được chọn trên validation
theo giả định chi phí `5FN + FP`. Các chỉ số trên được tính trên tập test lịch sử
của dự án.

Điểm số giúp ưu tiên hồ sơ cần rà soát theo nhãn `TARGET` của dữ liệu nguồn. Điểm
này chưa được xác nhận là PD 12 tháng và không tự quyết định duyệt hay từ chối vay.

## Cấu trúc repo

| Thư mục | Nội dung |
|---|---|
| `web/` | Giao diện, đăng nhập, phân quyền và các chức năng quản lý hồ sơ |
| `models/`, `connectors/`, `utils/` | Xử lý dữ liệu, huấn luyện, kết nối MySQL và chấm điểm |
| `notebooks/` | Tám bước nghiên cứu, theo thứ tự 01–08 |
| `artifacts/` | Mô hình đã huấn luyện và metadata; bản đang dùng có 182 đặc trưng |
| `runtime_assets/` | Dữ liệu đánh giá phục vụ giao diện |
| `reports/` | Bảng kết quả và biểu đồ thực nghiệm, không gồm báo cáo học phần |
| `data/metadata/`, `data/splits/` | Từ điển dữ liệu và danh sách phân tập đã chốt |
| `sql/`, `scripts/`, `tests/` | Cấu trúc database, script chuẩn bị và các bộ kiểm tra |

## Chạy local trên Windows

Ứng dụng chạy với MySQL trên máy, không cần database online hoặc Docker. Bản này
đã được kiểm tra bằng Python 3.14, MySQL 8.0.32 và các phiên bản thư viện ghi trong
requirements. Các bước chi tiết nằm trong
[hướng dẫn MySQL Workbench](HUONG_DAN_MYSQL_WORKBENCH.md).

1. Tải code và gói dữ liệu được chia sẻ riêng. Đặt `data_bundle/` cạnh thư mục repo.
2. Mở PowerShell trong thư mục repo và giải nén file SQL:

```powershell
py scripts/prepare_submission_data.py
```

3. Trong Workbench, tạo schema `home_credit_submission`, chọn **Server → Data Import
   → Import from Self-Contained File**, rồi nhập `data_bundle/database.sql` vào schema đó.
4. Tạo môi trường Python, cài thư viện rồi chạy web:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-web.txt
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Khi script hỏi, nhập mật khẩu MySQL của máy bạn. Sau đó mở
**http://127.0.0.1:5000** và dùng tài khoản trong `data_bundle/demo_accounts.json`
để đăng nhập dashboard. Nếu MySQL dùng user hoặc port khác mặc định, truyền các
tham số tương ứng cho `start.ps1` như trong hướng dẫn.

Sau khi nhập đủ database, bạn có thể mở web ngay mà không chạy notebook hoặc
các lệnh `--init-db`, `--init-users`. Lần đầu mở Tổng quan có thể mất vài chục
giây để truy vấn dữ liệu và tạo cache báo cáo.

## Dữ liệu và MySQL

Database và dữ liệu nghiên cứu được gửi riêng vì dung lượng lớn. Repo không chứa
dữ liệu raw, mật khẩu hay bản xuất database. Danh sách file và mã SHA-256 để kiểm
tra nằm trong `data/manifest.json`; xem thêm [hướng dẫn dữ liệu](data/README.md).

Database dùng cho web cần có dữ liệu nghiên cứu, đặc trưng, phân tập và các bảng
tác nghiệp. File tạo schema chỉ tạo cấu trúc bảng, nên vẫn phải nhập dữ liệu từ
bản xuất SQL. Khi khôi phục, giữ nguyên tên cột, NULL, khóa và danh sách phân tập.

## Kiểm tra và tái hiện

Để chạy tests, cài thêm thư viện kiểm tra và giải nén gói dữ liệu nghiên cứu:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe scripts/prepare_submission_data.py --research
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Các test JavaScript cần Node.js; nếu máy chưa có, những test đó sẽ báo skipped.
Trong lượt kiểm tra bản đóng gói, 191 tests đã đạt. Database đã được khôi phục đủ
18 bảng; các chức năng đăng nhập, mở trang chính, xuất đặc trưng, chấm điểm, lưu
lịch sử và đọc lại điểm đều đã chạy trên bản database khôi phục.

Nếu muốn xem quy trình nghiên cứu, mở notebook theo thứ tự 01→08 và chọn kernel
của môi trường Python vừa tạo. Notebook có thể dùng lại checkpoint hợp lệ thay
vì huấn luyện lại. Lượt đóng gói chưa kiểm tra việc cài thư viện trên máy sạch
hoặc chạy lại toàn bộ chuỗi huấn luyện từ đầu.

## Nguồn

[Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/data).
Các notebook trình bày phương pháp và kết quả. Tài liệu đối chiếu nguồn cùng báo
cáo học phần được lưu riêng.
