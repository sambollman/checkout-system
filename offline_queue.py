import sqlite3
import os
from datetime import datetime

OFFLINE_DB = os.getenv('OFFLINE_DB_PATH', 'offline_queue.db')

def init_offline_db():
    """Create offline queue database"""
    conn = sqlite3.connect(OFFLINE_DB)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS queued_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT NOT NULL,
            user_card_id TEXT,
            user_first_name TEXT,
            user_last_name TEXT,
            fob_id TEXT NOT NULL,
            fob_name TEXT,
            timestamp TEXT NOT NULL,
            kiosk_id TEXT NOT NULL,
            synced INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def queue_transaction(trans_type, user_info, fob_info, kiosk_id):
    """Add transaction to offline queue
    
    Args:
        trans_type: 'checkout' or 'checkin'
        user_info: dict with card_id, first_name, last_name (or None for checkin)
        fob_info: dict with fob_id, vehicle_name
        kiosk_id: kiosk identifier
    """
    conn = sqlite3.connect(OFFLINE_DB)
    
    user_card_id = user_info['card_id'] if user_info else None
    user_first = user_info.get('first_name') if user_info else None
    user_last = user_info.get('last_name') if user_info else None
    
    conn.execute('''
        INSERT INTO queued_transactions 
        (transaction_type, user_card_id, user_first_name, user_last_name, fob_id, fob_name, timestamp, kiosk_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (trans_type, user_card_id, user_first, user_last, fob_info['fob_id'], 
          fob_info.get('vehicle_name'), datetime.now().isoformat(), kiosk_id))
    
    conn.commit()
    count = conn.execute('SELECT COUNT(*) FROM queued_transactions WHERE synced = 0').fetchone()[0]
    conn.close()
    
    return count

def get_pending_transactions():
    """Get all unsynced transactions"""
    conn = sqlite3.connect(OFFLINE_DB)
    conn.row_factory = sqlite3.Row
    transactions = conn.execute(
        'SELECT * FROM queued_transactions WHERE synced = 0 ORDER BY id ASC'
    ).fetchall()
    conn.close()
    return transactions

def mark_synced(transaction_id):
    """Mark transaction as synced"""
    conn = sqlite3.connect(OFFLINE_DB)
    conn.execute('UPDATE queued_transactions SET synced = 1 WHERE id = ?', (transaction_id,))
    conn.commit()
    conn.close()

def get_queue_count():
    """Get count of pending transactions"""
    conn = sqlite3.connect(OFFLINE_DB)
    count = conn.execute('SELECT COUNT(*) FROM queued_transactions WHERE synced = 0').fetchone()[0]
    conn.close()
    return count

# Initialize on import
init_offline_db()
