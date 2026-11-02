"""Database tài khoản độc lập để kiểm tra quyền, không kết nối MySQL thật."""
import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash


class AuthDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript('''
            CREATE TABLE users (id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,
                full_name TEXT,role TEXT,is_active INTEGER DEFAULT 1,session_version INTEGER DEFAULT 1,
                created_at TEXT DEFAULT '2026-10-26 00:00:00');
            CREATE TABLE demo_profiles (profile_id INTEGER PRIMARY KEY,assigned_user_id INTEGER,assignee TEXT,is_archived INTEGER DEFAULT 0);
            CREATE TABLE scoring_events (event_id INTEGER PRIMARY KEY,profile_id INTEGER,input_snapshot TEXT);
            CREATE TABLE review_notes (note_id INTEGER PRIMARY KEY,event_id INTEGER,author TEXT,content TEXT);
            CREATE TABLE user_audit (audit_id INTEGER PRIMARY KEY,actor_user_id INTEGER,action TEXT,target_user_id INTEGER,detail TEXT);
            INSERT INTO demo_profiles VALUES (10,2,'analyst_test',0),(11,4,'other_analyst',0),(12,NULL,'legacy-name',0);
            INSERT INTO scoring_events VALUES (100,10,'{}'),(101,11,'{}');
            INSERT INTO review_notes VALUES (1000,100,'analyst_test','mine'),(1001,100,'risk_manager','manager note'),(1002,101,'other_analyst','other');
        ''')
        password_hash = generate_password_hash('test-password!', method='pbkdf2:sha256:1000')
        for user_id, username, role in [(1,'risk_manager','risk_manager'),(2,'analyst_test','analyst'),(3,'admin','admin'),(4,'other_analyst','analyst')]:
            self.conn.execute('INSERT INTO users (id,username,password_hash,full_name,role) VALUES (?,?,?,?,?)',
                              (user_id,username,password_hash,username,role))
        self.conn.commit()

    def queryDataset(self, sql, params=()):
        cursor = self.conn.execute(sql.replace('%s','?'), tuple(params))
        return pd.DataFrame(cursor.fetchall(),columns=[col[0] for col in cursor.description])

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql.replace('%s','?'), tuple(params))
        self.conn.commit()
        return {'lastrowid':cursor.lastrowid,'rowcount':cursor.rowcount}

    def executeMany(self, sql, rows):
        cursor = self.conn.executemany(sql.replace('%s','?'),rows)
        self.conn.commit()
        return cursor.rowcount
