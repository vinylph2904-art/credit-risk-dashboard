import json
import os
from pathlib import Path

import mysql.connector
import pandas as pd


class Connector:
    def __init__(self, server=None, port=None, database=None, username=None, password=None):
        config_path = Path(__file__).resolve().parents[1] / 'configs/mysql_connection.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        local_path = config_path.with_name('mysql_connection.local.json')
        local = json.loads(local_path.read_text(encoding='utf-8')) if local_path.exists() else {}
        self.server = server if server is not None else os.environ.get('MYSQL_HOST', config['host'])
        self.port = int(port if port is not None else os.environ.get('MYSQL_PORT', config['port']))
        self.database = database if database is not None else os.environ.get('MYSQL_DATABASE', config['database'])
        self.username = username if username is not None else os.environ.get('MYSQL_USER', config['user'])
        self.password = password if password is not None else os.environ.get('MYSQL_PASSWORD', local.get('password'))
        self.conn = None

    def connect(self):
        if self.password is None:
            raise ValueError('Đặt MYSQL_PASSWORD hoặc cấu hình configs/mysql_connection.local.json trước khi kết nối.')
        self.conn = mysql.connector.connect(
            host=self.server, port=self.port, database=self.database,
            user=self.username, password=self.password,
            connection_timeout=10, charset='utf8mb4', time_zone='+00:00')
        return self.conn

    def disConnect(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def queryDataset(self, sql, params=()):
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            return pd.DataFrame(cursor.fetchall(), columns=cursor.column_names)
        finally:
            cursor.close()

    def queryBatches(self, sql, params=(), batch_size=50_000):
        """Đọc lần lượt từng lô khi kết quả truy vấn có nhiều dòng."""
        cursor = self.conn.cursor(buffered=False)
        try:
            cursor.execute(sql, params)
            columns = cursor.column_names
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield pd.DataFrame(rows, columns=columns)
        finally:
            cursor.close()

    def execute(self, sql, params=()):
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            result = {'lastrowid': cursor.lastrowid, 'rowcount': cursor.rowcount}
            self.conn.commit()
            return result
        except mysql.connector.Error:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def executeMany(self, sql, rows):
        cursor = self.conn.cursor()
        try:
            cursor.executemany(sql, rows)
            self.conn.commit()
            return cursor.rowcount
        except mysql.connector.Error:
            self.conn.rollback()
            raise
        finally:
            cursor.close()
