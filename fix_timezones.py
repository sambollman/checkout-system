#!/usr/bin/env python3
import sqlite3
from datetime import datetime
import pytz

DATABASE = 'key_checkout.db'
chicago_tz = pytz.timezone('America/Chicago')

conn = sqlite3.connect(DATABASE)
cursor = conn.cursor()

# Get all checkouts
checkouts = cursor.execute('SELECT id, checked_out_at, checked_in_at FROM checkouts').fetchall()

for checkout_id, checked_out_at, checked_in_at in checkouts:
    # Fix checkout time
    try:
        dt = datetime.fromisoformat(checked_out_at)
        if dt.tzinfo is None:
            # Assume it was Central time, make it timezone-aware
            dt = chicago_tz.localize(dt)
            cursor.execute('UPDATE checkouts SET checked_out_at = ? WHERE id = ?',
                          (dt.isoformat(), checkout_id))
    except:
        pass
    
    # Fix checkin time if exists
    if checked_in_at:
        try:
            dt = datetime.fromisoformat(checked_in_at)
            if dt.tzinfo is None:
                dt = chicago_tz.localize(dt)
                cursor.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                              (dt.isoformat(), checkout_id))
        except:
            pass

conn.commit()
conn.close()
print("Database timestamps updated!")
