import sqlite3
import json
from datetime import datetime
import os

DB_PATH = 'aena_bot.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for users (if we want to restrict or customize)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            registered_at TIMESTAMP
        )
    ''')
    
    # Table for training sessions
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
    conn.close()

def log_session(user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback="", ai_adjustment=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, date_iso, completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment, datetime.now()))
    conn.commit()
    conn.close()

def get_session(user_id, date_iso):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT completed_status, rpe, pain_notes, general_notes, ai_feedback, ai_adjustment
        FROM sessions WHERE user_id = ? AND date_iso = ? ORDER BY logged_at DESC LIMIT 1
    ''', (user_id, date_iso))
    row = cursor.fetchone()
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

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
