import sqlite3
import os
from datetime import datetime

DATABASE = os.getenv('DB_PATH', 'key_checkout.db')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with our tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Key fobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS key_fobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id TEXT UNIQUE NOT NULL,
            vehicle_name TEXT NOT NULL,
	    category TEXT DEFAULT 'Vehicle',	
            location TEXT DEFAULT 'Station',
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Checkouts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checkouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fob_id INTEGER NOT NULL,
            checked_out_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checked_in_at TIMESTAMP NULL,
            kiosk_id TEXT DEFAULT 'kiosk1',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (fob_id) REFERENCES key_fobs(id)
        )
    ''')
    
    # Admin users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Create reservations table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL,
            user_id INTEGER,
            reserved_for_name TEXT,
            reserved_datetime TEXT NOT NULL,
            display_hours_before INTEGER DEFAULT 24,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Create notes table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL UNIQUE,
            note_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id)
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()
