# Dữ liệu ngoài Git

`manifest.json` ghi đường dẫn, dung lượng và SHA-256 của dữ liệu nguồn/trung gian
trên môi trường nghiên cứu. Manifest không chứa dữ liệu và không tự tải dữ liệu.

- Lấy nguồn Home Credit từ Kaggle theo điều kiện truy cập của nguồn.
- Raw MySQL cần giữ đúng giá trị, NULL, dòng trùng và `_source_row` như thiết kế.
- Bản chia tập trong `splits/` là bản đã chốt; không tự chia lại khi tái hiện.
- Notebook 04 tạo feature; 05 chọn biến; 06–08 huấn luyện, đánh giá và giải thích.
- Để chạy test tích hợp, cần thêm feature và artifact lịch sử mà từng test đọc.

Gói bàn giao riêng có `database.sql.gz` chứa cấu trúc và dữ liệu đã chuẩn bị.
Giải nén bằng `scripts/prepare_submission_data.py`, rồi nạp SQL bằng MySQL Workbench
theo `HUONG_DAN_MYSQL_WORKBENCH.md`. Sau nhập, dùng
`scripts/verify_submission_database.py` để kiểm tra số dòng. Đây là đường khôi phục
snapshot; không phải trình nạp trực tiếp raw từ Kaggle. Không chạy schema trống
rồi coi là đã nạp dữ liệu.

DB dump phải được chuyển riêng; không đưa tài khoản, mật khẩu hash, ghi chú hoặc
lịch sử tác nghiệp thật lên GitHub công khai. Các file lớn được loại khỏi Git.
