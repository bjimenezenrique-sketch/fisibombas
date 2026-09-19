import json
from datetime import datetime
import os
import urllib.parse

# Support both PostgreSQL and SQLite
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
        # PostgreSQL syntax
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
    else:
        # SQLite syntax
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
    
    conn.commit()
    cursor.close()
    conn.close()

def log_session(user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback="", ai_adjustment=""):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Ensure user exists (upsert logic differs)
    if DB_URL:
        cursor.execute('''
            INSERT INTO users (user_id, username, registered_at) 
            VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING
        ''', (user_id, "user", datetime.now()))
        
        cursor.execute('''
            INSERT INTO sessions (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, logged_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now()))
    else:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, registered_at) 
            VALUES (?, ?, ?)
        ''', (user_id, "user", datetime.now()))
        
        cursor.execute('''
            INSERT INTO sessions (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now()))
        
    conn.commit()
    cursor.close()
    conn.close()

def get_session(user_id, date_iso):
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            SELECT completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment
            FROM sessions WHERE user_id = %s AND date_iso = %s ORDER BY logged_at DESC LIMIT 1
        ''', (user_id, date_iso))
    else:
        cursor.execute('''
            SELECT completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment
            FROM sessions WHERE user_id = ? AND date_iso = ? ORDER BY logged_at DESC LIMIT 1
        ''', (user_id, date_iso))
        
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if row:
        return {
            "completed_status": row[0],
            "rpe": row[1],
            "pain_notes": row[2],
            "general_notes": row[3],
            "ai_feedback": row[4],
            "ai_adjustment": row[5]
        }
    return None

def get_all_records(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    if DB_URL:
        cursor.execute('''
            SELECT date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback
            FROM sessions WHERE user_id = %s ORDER BY date_iso DESC
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback
            FROM sessions WHERE user_id = ? ORDER BY date_iso DESC
        ''', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    records = []
    for r in rows:
        records.append({
            "date": r[0],
            "status": r[1],
            "rpe": r[2],
            "pain": r[3],
            "notes": r[4],
            "feedback": r[5]
        })
    return records

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
