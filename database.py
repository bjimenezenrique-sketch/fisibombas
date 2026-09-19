import json
from datetime import datetime
import os

DB_URL = os.getenv("DATABASE_URL")

def get_connection():
    if DB_URL:
        import psycopg2
        return psycopg2.connect(DB_URL)
    else:
        import sqlite3
        return sqlite3.connect('aena_bot.db')

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    if DB_URL:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                registered_at TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                date_iso TEXT,
                completed_status TEXT,
                rpe INTEGER,
                pain_notes TEXT,
                general_notes TEXT,
                ai_feedback TEXT,
                ai_adjustment TEXT,
                logged_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                test_name TEXT,
                value REAL,
                logged_at TIMESTAMP,
                UNIQUE(user_id, test_name)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS targets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                test_name TEXT,
                start_value REAL,
                goal_value REAL,
                updated_at TIMESTAMP,
                UNIQUE(user_id, test_name)
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                registered_at TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date_iso TEXT,
                completed_status TEXT,
                rpe INTEGER,
                pain_notes TEXT,
                general_notes TEXT,
                ai_feedback TEXT,
                ai_adjustment TEXT,
                logged_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                test_name TEXT,
                value REAL,
                logged_at TIMESTAMP,
                UNIQUE(user_id, test_name)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                test_name TEXT,
                start_value REAL,
                goal_value REAL,
                updated_at TIMESTAMP,
                UNIQUE(user_id, test_name)
            )
        ''')
    
    conn.commit()
    cursor.close()
    conn.close()

def _ensure_user(cursor, user_id, pg=False):
    if pg:
        cursor.execute(
            'INSERT INTO users (user_id, username, registered_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING',
            (user_id, "user", datetime.now())
        )
    else:
        cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username, registered_at) VALUES (?, ?, ?)',
            (user_id, "user", datetime.now())
        )

def upsert_session(user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback="", ai_adjustment=""):
    """Insert or update a session record for a given date."""
    conn = get_connection()
    cursor = conn.cursor()
    pg = bool(DB_URL)
    
    _ensure_user(cursor, user_id, pg)
    
    if pg:
        # Check if exists
        cursor.execute('SELECT id FROM sessions WHERE user_id=%s AND date_iso=%s', (user_id, date_iso))
        existing = cursor.fetchone()
        if existing:
            cursor.execute('''
                UPDATE sessions SET completed_status=%s, rpe=%s, pain_notes=%s, general_notes=%s,
                ai_feedback=%s, ai_adjustment=%s, logged_at=%s
                WHERE user_id=%s AND date_iso=%s
            ''', (completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now(), user_id, date_iso))
        else:
            cursor.execute('''
                INSERT INTO sessions (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, logged_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now()))
    else:
        cursor.execute('SELECT id FROM sessions WHERE user_id=? AND date_iso=?', (user_id, date_iso))
        existing = cursor.fetchone()
        if existing:
            cursor.execute('''
                UPDATE sessions SET completed_status=?, rpe=?, pain_notes=?, general_notes=?,
                ai_feedback=?, ai_adjustment=?, logged_at=?
                WHERE user_id=? AND date_iso=?
            ''', (completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now(), user_id, date_iso))
        else:
            cursor.execute('''
                INSERT INTO sessions (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, logged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now()))
    
    conn.commit()
    cursor.close()
    conn.close()

# Keep log_session as alias for backward compat
def log_session(user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback="", ai_adjustment=""):
    upsert_session(user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment)

def get_session(user_id, date_iso):
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            SELECT completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment
            FROM sessions WHERE user_id=%s AND date_iso=%s ORDER BY logged_at DESC LIMIT 1
        ''', (user_id, date_iso))
    else:
        cursor.execute('''
            SELECT completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment
            FROM sessions WHERE user_id=? AND date_iso=? ORDER BY logged_at DESC LIMIT 1
        ''', (user_id, date_iso))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {"completed_status": row[0], "rpe": row[1], "pain_notes": row[2],
                "general_notes": row[3], "ai_feedback": row[4], "ai_adjustment": row[5]}
    return None

def get_all_records(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            SELECT date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback
            FROM sessions WHERE user_id=%s ORDER BY date_iso DESC
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback
            FROM sessions WHERE user_id=? ORDER BY date_iso DESC
        ''', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"date": r[0], "status": r[1], "rpe": r[2], "pain": r[3], "notes": r[4], "feedback": r[5]} for r in rows]

def save_mark(user_id, test_name, value):
    """Save or update a performance mark for a given test."""
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            INSERT INTO marks (user_id, test_name, value, logged_at) VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, test_name) DO UPDATE SET value=%s, logged_at=%s
        ''', (user_id, test_name, value, datetime.now(), value, datetime.now()))
    else:
        cursor.execute('''
            INSERT INTO marks (user_id, test_name, value, logged_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, test_name) DO UPDATE SET value=?, logged_at=?
        ''', (user_id, test_name, value, datetime.now(), value, datetime.now()))
    conn.commit()
    cursor.close()
    conn.close()

def get_marks(user_id):
    """Get all performance marks for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('SELECT test_name, value, logged_at FROM marks WHERE user_id=%s', (user_id,))
    else:
        cursor.execute('SELECT test_name, value, logged_at FROM marks WHERE user_id=?', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {r[0]: {"value": r[1], "updated": str(r[2])} for r in rows}

def save_target(user_id, test_name, start_value, goal_value):
    """Save or update custom start/goal for a test."""
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            INSERT INTO targets (user_id, test_name, start_value, goal_value, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, test_name) DO UPDATE SET start_value=%s, goal_value=%s, updated_at=%s
        ''', (user_id, test_name, start_value, goal_value, datetime.now(),
              start_value, goal_value, datetime.now()))
    else:
        cursor.execute('''
            INSERT INTO targets (user_id, test_name, start_value, goal_value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (user_id, test_name) DO UPDATE SET start_value=?, goal_value=?, updated_at=?
        ''', (user_id, test_name, start_value, goal_value, datetime.now(),
              start_value, goal_value, datetime.now()))
    conn.commit()
    cursor.close()
    conn.close()

def get_targets(user_id):
    """Get all custom targets for a user. Returns {test_name: {start, goal}}"""
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('SELECT test_name, start_value, goal_value FROM targets WHERE user_id=%s', (user_id,))
    else:
        cursor.execute('SELECT test_name, start_value, goal_value FROM targets WHERE user_id=?', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {r[0]: {"start": r[1], "goal": r[2]} for r in rows}

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
