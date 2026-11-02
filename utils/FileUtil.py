"""Đọc JSON dùng lại trong notebook và metadata inference."""
import json
from pathlib import Path


class FileUtil:
    @staticmethod
    def readJson(filename):
        with Path(filename).open(encoding='utf-8') as stream:
            return json.load(stream)
