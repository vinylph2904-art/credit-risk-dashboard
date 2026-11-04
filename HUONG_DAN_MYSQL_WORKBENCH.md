# Nạp dữ liệu và chạy bộ nộp bằng MySQL Workbench

## Chuẩn bị

Cài MySQL Server 8.0, MySQL Workbench và Python 3.14. Bản kiểm chứng dùng MySQL
8.0.32, Python 3.14; không tự đổi version thư viện đã pin khi tải model joblib.
Cần khoảng 20–25 GB trống cho SQL giải nén, DB sau khi nhập, dữ liệu nghiên cứu
và môi trường Python. Dung lượng còn tùy cách MySQL cấp phát và thư viện cài đặt.

Để cạnh nhau hai thư mục:

```text
bo_nop/
├── home-credit-risk/       # Code đã giải nén
└── data_bundle/            # Dữ liệu đã giải nén, gửi riêng
    ├── database.sql.gz
    ├── research_data.zip
    ├── manifest.json
    └── demo_accounts.json
```

## 1. Giải nén dữ liệu

Mở PowerShell trong `home-credit-risk/`:

```powershell
py scripts/prepare_submission_data.py --research
```

Lệnh chỉ dùng thư viện chuẩn Python, chưa cần cài requirements. Nó kiểm tra
SHA-256 rồi tạo `data_bundle/database.sql` và giải nén dữ liệu nghiên cứu về
`data/`. Nếu chỉ xem dashboard, bỏ `--research` để không giải nén dữ liệu notebook.
Khi `database.sql` đã tồn tại, script kiểm tra checksum và tái dùng đúng bản;
nếu file khác nội dung, script dừng để tránh ghi đè.

## 2. Nhập bằng MySQL Workbench

1. Mở kết nối đến MySQL Server local bằng tài khoản có quyền tạo schema.
2. Tạo schema mới tên **`home_credit_submission`**, charset `utf8mb4`.
   Dùng tên riêng này để không đụng đến DB hiện có.
3. Chọn **Server → Data Import**.
4. Chọn **Import from Self-Contained File**, trỏ đến `data_bundle/database.sql`.
   Không chọn trực tiếp file `.gz` hoặc `research_data.zip`.
5. Trong **Default Target Schema**, chọn `home_credit_submission`.
6. Chọn nhập cả cấu trúc và dữ liệu (**Dump Structure and Data**), rồi **Start Import**.
7. Chờ thông báo hoàn thành và xem Import Progress có lỗi hay không. Nguồn có
   gần 58 triệu dòng lịch sử, lần nhập đầu có thể lâu; không đóng Workbench giữa chừng.
8. Refresh Schemas. Bản nộp có 18 bảng, bao gồm raw, features, split và bảng ứng dụng.

Không cần chạy lại `sql/00_raw_schema.sql`, `--init-db` hoặc `--init-users` sau khi
đã nhập toàn bộ dump. Dump đã chứa schema, index và dữ liệu demo.

## 3. Cài thư viện và cấu hình

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:MYSQL_HOST = '127.0.0.1'
$env:MYSQL_PORT = '3306'
$env:MYSQL_DATABASE = 'home_credit_submission'
$env:MYSQL_USER = 'root'
```

Đặt `MYSQL_PASSWORD` bằng mật khẩu MySQL của **máy nhận**, không dùng mật khẩu
máy người gửi. Có thể dùng biến môi trường hoặc tạo file riêng
`configs/mysql_connection.local.json` với nội dung `{"password":"mat-khau-mysql-cua-may-nhan"}`.
File local bị loại khỏi Git, không chia sẻ file có mật khẩu thật.

Kiểm chứng số dòng sau nhập (đọc dữ liệu, không sửa):

```powershell
.venv\Scripts\python.exe scripts/verify_submission_database.py
```

## 4. Mở dashboard

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Lệnh hỏi mật khẩu MySQL và chạy local tại **http://127.0.0.1:5000**.
Nếu cổng 5000 đang bận, thêm `-WebPort 5001` và mở địa chỉ với cổng tương ứng.
Nếu máy dùng host, port hoặc
username khác, truyền `-DatabaseHost`, `-DatabasePort`, `-DatabaseUser` tương ứng.

Đăng nhập dashboard bằng tài khoản/mật khẩu trong `data_bundle/demo_accounts.json`.
Đây là mật khẩu demo mới của bộ nộp, khác mật khẩu MySQL và khác bản nguồn.
Giữ cửa sổ chạy web mở; Ctrl+C để dừng.
Lần đầu mở Tổng quan sau khi phục hồi DB có thể mất vài chục giây để truy vấn
dữ liệu và tạo cache báo cáo. Trong lượt kiểm chứng, lần mở đầu khoảng 46 giây;
thời gian thực tế tùy cấu hình máy. Chờ tải xong trước khi bấm tải lại liên tục.

## 5. Xem và chạy code huấn luyện

Mở notebook 01–08, chọn kernel của `.venv`. Nếu cần dùng giao diện Jupyter,
cài JupyterLab riêng trong môi trường này hoặc dùng VS Code với notebook extension.
Chạy lần lượt 01→08 để tái hiện quy trình. Dataset lớn và 63 lượt CV có thể tốn thời gian;
checkpoint sẵn có được tái dùng nếu hợp lệ. Không nhầm việc hiển thị output đã lưu
với cell vừa chạy. Không dùng test lịch sử để chọn lại model hoặc ngưỡng.
Output cũ trong notebook có thể ghi tên schema nghiên cứu `home_credit_ml`;
bản bàn giao hỗ trợ schema khôi phục `home_credit_submission` chứa cùng dữ liệu.

```powershell
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Test JavaScript cần Node.js. Nếu máy chưa có Node, các test tương ứng báo skipped.
Script `audit_ml_system.py` kiểm tra thêm dữ liệu/model/DB khi đã giải nén bộ nghiên cứu.

## Khi gặp lỗi

- `Access denied`: kiểm tra user/password MySQL và quyền trên schema mới.
- Thiếu bảng hoặc số dòng không khớp: xem lỗi Data Import, chưa chạy ứng dụng như đã nạp đủ.
- Thiếu feature/checkpoint: giải nén research data đúng vị trí và xem manifest.
- Không nạp được joblib: dùng phiên bản thư viện đã pin trong requirements.
- Không đăng nhập dashboard: dùng `demo_accounts.json`, không dùng mật khẩu MySQL.
- SQL import bị ngắt: không ghi đè schema đang có dữ liệu quan trọng; tạo schema mới
  rồi nhập lại, cấu hình ứng dụng sang đúng schema đó.

Tham khảo: [MySQL Workbench — SQL Data Export and Import Wizard](https://dev.mysql.com/doc/workbench/en/wb-admin-export-import-management.html).


## Mật khẩu đăng nhập dashboard

Ba tài khoản `admin`, `risk_manager`, `analyst` đều dùng mật khẩu demo **`HomeCredit@123`**.
Nhập nguyên mật khẩu này trên web; không nhập hash trong bảng `users`.
Mật khẩu MySQL vẫn là mật khẩu riêng trên máy nhận.

Nếu đã nhập database của bản cũ: mở SQL tab trong MySQL Workbench, chọn đúng
database web đang dùng rồi chạy file `DAT_LAI_MAT_KHAU_DEMO.sql` trong bộ bàn giao
(hoặc `data_bundle/reset_demo_passwords.sql`). Nếu tải từ GitHub, dùng
[`sql/06_reset_demo_passwords.sql`](sql/06_reset_demo_passwords.sql).
Không cần nhập lại dữ liệu lớn.
Sau đó đăng nhập lại bằng mật khẩu trên. Chỉ dùng mật khẩu này cho bản demo.
