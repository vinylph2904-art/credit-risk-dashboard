"""Cache Parquet cho dữ liệu nghiên cứu bất biến theo data_version.

Không lưu tài khoản, phân công, ghi chú hoặc kết quả scoring đang thay đổi.
"""
import hashlib
from pathlib import Path
from uuid import uuid4

import pandas as pd


def read_research_cache(folder, key, load_data):
    folder = Path(folder)
    filename = hashlib.sha256(key.encode('utf-8')).hexdigest() + '.parquet'
    path = folder / filename
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        # Cache thiếu hoặc hỏng: đọc lại dữ liệu gốc, không dùng kết quả cũ.
        pass

    data = load_data()
    temporary = folder / (filename + '.' + uuid4().hex + '.tmp')
    try:
        folder.mkdir(parents=True, exist_ok=True)
        data.to_parquet(temporary, index=False)
        temporary.replace(path)
    except (OSError, ValueError):
        # Lỗi ghi cache không ngăn người dùng đọc báo cáo từ database.
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return data
