from flask import Flask, render_template, request, redirect, url_for, session, make_response, send_file
from flask_socketio import SocketIO, emit
from database import get_db
from datetime import datetime
import pytz
import hashlib
import os
from functools import wraps

# Kiosk authentication (HTTP Basic Auth)
KIOSK_USER = os.getenv('KIOSK_USER', 'kiosk')
KIOSK_PASS = os.getenv('KIOSK_PASS', 'change-this-in-production')

def require_kiosk_auth(f):
    """Decorator to require HTTP Basic Auth for kiosk endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != KIOSK_USER or auth.password != KIOSK_PASS:
            return {'error': 'Unauthorized'}, 401
        return f(*args, **kwargs)
    return decorated_function



app = Flask(__name__)
app.secret_key = 'change-this-to-something-secret'  # Change this!

socketio = SocketIO(app, cors_allowed_origins="*")

ADMIN_PASSWORD = 'admin123'  # Change this to a real password!

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def compact_database():
    """Compact the SQLite database to reclaim space"""
    conn = get_db()
    conn.execute('VACUUM')
    conn.close()
    print("Database compacted successfully")


@app.route('/')
def index():
    """Main page showing all key fobs and their status"""
    conn = get_db()
    
    # Get all active key fobs with their current checkout status
    query = '''
        SELECT 
            kf.id,
            kf.fob_id,
            kf.vehicle_name,
            kf.category,
            kf.location,
            u.first_name,
            u.last_name,
            c.checked_out_at,
            c.id as checkout_id
        FROM key_fobs kf
        LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
        LEFT JOIN users u ON c.user_id = u.id
        WHERE kf.is_active = 1
        ORDER BY kf.category, kf.vehicle_name
    '''
    
    all_keys = conn.execute(query).fetchall()
    # Get notes
    notes_query = 'SELECT * FROM notes'
    notes = conn.execute(notes_query).fetchall()
    
    # Create note map
    note_map = {}
    for note in notes:
        note_map[note['fob_id']] = note


    # Get active reservations
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz)
    
    reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.id as fob_table_id
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        WHERE datetime(r.reserved_datetime) > datetime(?)
          AND datetime(r.reserved_datetime, '-' || r.display_hours_before || ' hours') <= datetime(?)
    '''
    reservations = conn.execute(reservations_query, (now.isoformat(), now.isoformat())).fetchall()
    
    # Format reservation datetimes
    formatted_reservations = []
    for res in reservations:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')  # "Fri, Feb 21 at 2:00 PM"
            except:
                pass
        formatted_reservations.append(res_dict)

    # Create a dict of fob_id -> reservation
    reservation_map = {}
    for res in reservations:
        reservation_map[res['fob_table_id']] = res
    print(f"DEBUG: Found {len(reservations)} reservations")
    print(f"DEBUG: reservation_map keys: {reservation_map.keys()}")
    conn.close()
    
    # Format timestamps and group by category
    chicago_tz = pytz.timezone('America/Chicago')
    formatted_keys = []
    
    for key in all_keys:
        key_dict = dict(key)
        if key_dict['checked_out_at']:
            # Parse the timestamp and convert to Chicago time
            dt = datetime.fromisoformat(key_dict['checked_out_at'])
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_chicago = dt.astimezone(chicago_tz)
            # Format: Feb 15, 2026 14:33
            key_dict['checked_out_at'] = dt_chicago.strftime('%b %d, %Y %H:%M')
            # Add note info
        if key_dict['id'] in note_map:
            note = note_map[key_dict['id']]
            key_dict['note'] = dict(note)
        else:
            key_dict['note'] = None

        # Add reservation info
        if key_dict['id'] in reservation_map:
            res = reservation_map[key_dict['id']]
            key_dict['reservation'] = dict(res)
        else:
            key_dict['reservation'] = None

        formatted_keys.append(key_dict)
    
     # Group by category with natural sorting
    import re
    
    def natural_sort_key(item):
        """Sort key that handles numbers naturally"""
        return [int(text) if text.isdigit() else text.lower() 
                for text in re.split('([0-9]+)', item['vehicle_name'])]
    
    vehicles = sorted([k for k in formatted_keys if k['category'] == 'Vehicle'], 
                     key=natural_sort_key)
    equipment = sorted([k for k in formatted_keys if k['category'] == 'Equipment'], 
                      key=natural_sort_key)
    
    return render_template('index.html', vehicles=vehicles, equipment=equipment)

@app.route('/api/status')
@require_kiosk_auth
def api_status():
    """API endpoint to get current key status as JSON"""
    conn = get_db()
    
    # Get all active key fobs with their current checkout status
    query = '''
        SELECT 
            kf.id,
            kf.fob_id,
            kf.vehicle_name,
            kf.category,
            kf.location,
            u.first_name,
            u.last_name,
            c.checked_out_at,
            c.id as checkout_id
        FROM key_fobs kf
        LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
        LEFT JOIN users u ON c.user_id = u.id
        WHERE kf.is_active = 1
        ORDER BY kf.category, kf.vehicle_name
    '''
    
    all_keys = conn.execute(query).fetchall()
    
    # Get notes
    notes_query = 'SELECT * FROM notes'
    notes = conn.execute(notes_query).fetchall()
    
    # Create note map
    note_map = {}
    for note in notes:
        note_map[note['fob_id']] = note


    # Get active reservations
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz)
    
    reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.id as fob_table_id
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        WHERE datetime(r.reserved_datetime) > datetime(?)
          AND datetime(r.reserved_datetime, '-' || r.display_hours_before || ' hours') <= datetime(?)
    '''
    reservations = conn.execute(reservations_query, (now.isoformat(), now.isoformat())).fetchall()
    
    # Format reservation datetimes
    formatted_reservations = []
    for res in reservations:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')  # "Fri, Feb 21 at 2:00 PM"
            except:
                pass
        formatted_reservations.append(res_dict)

    # Create a dict of fob_id -> reservation
    reservation_map = {}
    for res in reservations:
        reservation_map[res['fob_table_id']] = res

    conn.close()
    
    # Format timestamps
    chicago_tz = pytz.timezone('America/Chicago')
    formatted_keys = []
    
    for key in all_keys:
        key_dict = dict(key)
        if key_dict['checked_out_at']:
            dt = datetime.fromisoformat(key_dict['checked_out_at'])
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_chicago = dt.astimezone(chicago_tz)
            key_dict['checked_out_at'] = dt_chicago.strftime('%b %d, %Y %H:%M')
        # Add reservation info
        if key_dict['id'] in reservation_map:
            res = reservation_map[key_dict['id']]
            key_dict['reservation'] = dict(res)
            print(f"DEBUG: Added reservation to {key_dict['vehicle_name']} (id={key_dict['id']})")
        else:
            key_dict['reservation'] = None
        # Add note info
        if key_dict['id'] in note_map:
            note = note_map[key_dict['id']]
            key_dict['note'] = dict(note)
        else:
            key_dict['note'] = None
        formatted_keys.append(key_dict)
    
    # Natural sort and group by category
    import re
    
    def natural_sort_key(item):
        return [int(text) if text.isdigit() else text.lower() 
                for text in re.split('([0-9]+)', item['vehicle_name'])]
    
    vehicles = sorted([k for k in formatted_keys if k['category'] == 'Vehicle'], 
                     key=natural_sort_key)
    equipment = sorted([k for k in formatted_keys if k['category'] == 'Equipment'], 
                      key=natural_sort_key)
    
    return {'vehicles': vehicles, 'equipment': equipment}

@app.route('/api/notify', methods=['POST'])
@require_kiosk_auth
def api_notify():
    """Receive notification from kiosk that status changed"""
    # Broadcast update to all connected clients
    socketio.emit('status_update', api_status())
    return {'status': 'ok'}

# DEVELOPMENT ONLY - REMOVE in production (OKTA handles login)
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error='Invalid password')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """Logout admin"""
    session.pop('admin', None)
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    """Admin dashboard"""
    print("DEBUG: ADMIN DASHBOARD CALLED")
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    
    # Get all users
    users_raw = conn.execute('SELECT * FROM users ORDER BY last_name ASC, first_name ASC').fetchall()
    
    # Format user registration timestamps
    chicago_tz = pytz.timezone('America/Chicago')
    users = []
    for user in users_raw:
        user_dict = dict(user)
        if user_dict['registered_at']:
            try:
                dt = datetime.fromisoformat(user_dict['registered_at'])
                # Old timestamps without timezone are in UTC, new ones have timezone
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt).astimezone(chicago_tz)
                else:
                    dt = dt.astimezone(chicago_tz)
                user_dict['registered_at'] = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            except:
                pass
        users.append(user_dict)
    
    # Get all key fobs
    fobs_raw = conn.execute('SELECT * FROM key_fobs').fetchall()
    # Get notes for fobs
    notes = conn.execute('SELECT * FROM notes').fetchall()
    note_map = {}
    for note in notes:
        note_map[note['fob_id']] = note
    # Natural sort by vehicle_name
    import re
    def natural_sort_key(item):
        return [int(text) if text.isdigit() else text.lower() 
                for text in re.split('([0-9]+)', item['vehicle_name'])]
    
    fobs_raw = sorted(fobs_raw, key=natural_sort_key)
    
    # Format fob registration timestamps
    fobs = []
    for fob in fobs_raw:
        fob_dict = dict(fob)
        # Add note if exists
        if fob_dict['id'] in note_map:
            fob_dict['note'] = dict(note_map[fob_dict['id']])
        else:
            fob_dict['note'] = None
        if fob_dict['registered_at']:
            try:
                dt = datetime.fromisoformat(fob_dict['registered_at'])
                # Old timestamps without timezone are in UTC, new ones have timezone
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt).astimezone(chicago_tz)
                else:
                    dt = dt.astimezone(chicago_tz)
                fob_dict['registered_at'] = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            except:
                pass
        fobs.append(fob_dict)
    
    # Get recent checkout history with filters
    hist_start_date = request.args.get('hist_start_date')
    hist_end_date = request.args.get('hist_end_date')
    hist_fob_id = request.args.get('hist_fob_id')
    hist_user_id = request.args.get('hist_user_id')
    hist_limit = request.args.get('hist_limit', '50')
    
    history_query = '''
        SELECT 
            u.first_name || " " || u.last_name as user_name,
            kf.vehicle_name,
            c.checked_out_at,
            c.checked_in_at,
            c.kiosk_id
        FROM checkouts c
        JOIN users u ON c.user_id = u.id
        JOIN key_fobs kf ON c.fob_id = kf.id
        WHERE 1=1
    '''
    
    params = []
    
    if hist_start_date:
        history_query += ' AND date(substr(c.checked_out_at, 1, 10)) >= date(?)'
        params.append(hist_start_date)
    
    if hist_end_date:
        history_query += ' AND date(substr(c.checked_out_at, 1, 10)) <= date(?)'
        params.append(hist_end_date)
    
    if hist_fob_id:
        history_query += ' AND kf.id = ?'
        params.append(int(hist_fob_id))
    
    if hist_user_id:
        history_query += ' AND u.id = ?'
        params.append(int(hist_user_id))
    
    history_query += ' ORDER BY c.checked_out_at DESC'
    
    if hist_limit and hist_limit != 'all':
        history_query += f' LIMIT {int(hist_limit)}'
    
    history_raw = conn.execute(history_query, params).fetchall()
    
    # Format timestamps - they're already in Central time with offset
    history = []
    for entry in history_raw:
        entry_dict = dict(entry)
        
        # Just parse and format - don't convert timezone
        if entry_dict['checked_out_at']:
            try:
                dt_str = entry_dict['checked_out_at']
                # Remove timezone info for parsing, then format
                dt = datetime.fromisoformat(dt_str.split('+')[0].split('-06:00')[0])
                entry_dict['checked_out_at'] = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            except:
                pass
        
        if entry_dict['checked_in_at']:
            try:
                dt_str = entry_dict['checked_in_at']
                # Remove timezone info for parsing, then format
                dt = datetime.fromisoformat(dt_str.split('+')[0].split('-06:00')[0])
                entry_dict['checked_in_at'] = dt.strftime('%Y-%m-%d %I:%M:%S %p')
            except:
                pass
        
        history.append(entry_dict)

    # Get active reservations
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz)
    
    reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.vehicle_name
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        ORDER BY r.reserved_datetime ASC
    '''
    reservations_raw = conn.execute(reservations_query).fetchall()
    
    # Filter and format reservation datetimes
    reservations = []
    for res in reservations_raw:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                # Only include future reservations
                if dt > now:
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')
                    reservations.append(res_dict)
            except:
                pass

    # Get past reservations with filters
    past_start_date = request.args.get('past_start_date')
    past_end_date = request.args.get('past_end_date')
    past_fob_id = request.args.get('past_fob_id')
    past_user_id = request.args.get('past_user_id')
    past_limit = request.args.get('past_limit', '25')
    
    print("DEBUG: About to get past reservations")
    past_reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.vehicle_name
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        ORDER BY r.reserved_datetime DESC
    '''
    past_reservations_raw = conn.execute(past_reservations_query).fetchall()
    
    # Filter and format past reservation datetimes
    past_reservations = []
    print(f"DEBUG: Now is {now}")
    for res in past_reservations_raw:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                print(f"DEBUG: Reservation time: {dt}, Is past? {dt <= now}")
                
                # Only include past reservations
                if dt <= now:
                    # Apply date filters
                    if past_start_date and dt.date() < datetime.strptime(past_start_date, '%Y-%m-%d').date():
                        continue
                    if past_end_date and dt.date() > datetime.strptime(past_end_date, '%Y-%m-%d').date():
                        continue
                    
                    # Apply fob filter
                    if past_fob_id and res_dict['fob_id'] != int(past_fob_id):
                        continue
                    
                    # Apply user filter
                    if past_user_id and res_dict['user_id'] != int(past_user_id):
                        continue
                    
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')
                    past_reservations.append(res_dict)
            except:
                pass
    
    # Apply limit
    if past_limit and past_limit != 'all':
        past_reservations = past_reservations[:int(past_limit)]


    
    # Filter and format past reservation datetimes
    past_reservations = []
    print(f"DEBUG: Now is {now}")
    for res in past_reservations_raw:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                print(f"DEBUG: Reservation time: {dt}, Is past? {dt <= now}")
                # Only include past reservations
                if dt <= now:
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')
                    past_reservations.append(res_dict)
            except:
                pass
    
    return render_template('admin.html', users=users, fobs=fobs, history=history, 
                          reservations=reservations, past_reservations=past_reservations)

    
    conn.close()
    
    return render_template('admin.html', users=users, fobs=fobs, history=history, reservations=reservations)

@app.route('/admin/user/deactivate/<int:user_id>')
def deactivate_user(user_id):
    """Deactivate a user"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE users SET is_active = 0 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/activate/<int:user_id>')
def activate_user(user_id):
    """Activate a user"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE users SET is_active = 1 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/fob/deactivate/<int:fob_id>')
def deactivate_fob(fob_id):
    """Deactivate a key fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE key_fobs SET is_active = 0 WHERE id = ?', (fob_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/fob/activate/<int:fob_id>')
def activate_fob(fob_id):
    """Activate a key fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE key_fobs SET is_active = 1 WHERE id = ?', (fob_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/export/history')
def export_history():
    """Export checkout history as CSV with optional filters"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    # Get filter parameters
    start_date = request.args.get('hist_start_date') or request.args.get('start_date')
    end_date = request.args.get('hist_end_date') or request.args.get('end_date')
    fob_id = request.args.get('hist_fob_id') or request.args.get('fob_id')
    user_id = request.args.get('hist_user_id') or request.args.get('user_id')
    
    conn = get_db()
    
    # Build query with filters
    query = '''
        SELECT 
            u.first_name || " " || u.last_name as user_name,
            u.card_id,
            kf.vehicle_name,
            kf.fob_id,
            c.checked_out_at,
            c.checked_in_at,
            c.kiosk_id
        FROM checkouts c
        JOIN users u ON c.user_id = u.id
        JOIN key_fobs kf ON c.fob_id = kf.id
        WHERE 1=1
    '''
    
    params = []
    
    chicago_tz = pytz.timezone('America/Chicago')
    
    if start_date:
        # Parse date as Central time (start of day)
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        start_dt = chicago_tz.localize(start_dt)
        query += ' AND datetime(c.checked_out_at) >= datetime(?)'
        params.append(start_dt.isoformat())
    
    if end_date:
        # Parse date as Central time (end of day)
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        end_dt = chicago_tz.localize(end_dt.replace(hour=23, minute=59, second=59))
        query += ' AND datetime(c.checked_out_at) <= datetime(?)'
        params.append(end_dt.isoformat())
    
    if fob_id:
        query += ' AND kf.id = ?'
        params.append(int(fob_id))
    
    if user_id:
        query += ' AND u.id = ?'
        params.append(int(user_id))
    
    
    query += ' ORDER BY c.checked_out_at DESC'
    
    print(f"DEBUG EXPORT: start_date={start_date}, end_date={end_date}")
    print(f"DEBUG EXPORT: Query params: {params}")
    print(f"DEBUG EXPORT: Query: {query}")

    history = conn.execute(query, params).fetchall()
    conn.close()
    
    # Build CSV
    csv_lines = []
    csv_lines.append("User Name,Card ID,Vehicle,Fob ID,Checked Out,Checked In,Duration (minutes),Kiosk")
    
    
    chicago_tz = pytz.timezone('America/Chicago')
    
    for entry in history:
        # Parse and convert checkout time to Central
        try:
            out_dt = datetime.fromisoformat(entry['checked_out_at'])
            if out_dt.tzinfo is None:
                out_dt = pytz.UTC.localize(out_dt)
            out_dt = out_dt.astimezone(chicago_tz)
            checked_out = out_dt.strftime('%Y-%m-%d %I:%M:%S %p')
        except:
            checked_out = entry['checked_out_at']
        
        # Parse and convert checkin time to Central
        if entry['checked_in_at']:
            try:
                in_dt = datetime.fromisoformat(entry['checked_in_at'])
                if in_dt.tzinfo is None:
                    in_dt = pytz.UTC.localize(in_dt)
                in_dt = in_dt.astimezone(chicago_tz)
                checked_in = in_dt.strftime('%Y-%m-%d %I:%M:%S %p')
                
                # Calculate duration
                duration_seconds = (in_dt - out_dt).total_seconds()
                duration = str(int(duration_seconds / 60))
            except:
                checked_in = 'Error'
                duration = 'N/A'
        else:
            checked_in = 'Still out'
            duration = ''
        
        csv_lines.append(f'"{entry["user_name"]}","{entry["card_id"]}","{entry["vehicle_name"]}","{entry["fob_id"]}","{checked_out}","{checked_in}","{duration}","{entry["kiosk_id"]}"')
    
    csv_content = '\n'.join(csv_lines)
    
    # Create response with CSV
    response = make_response(csv_content)
    response.headers['Content-Type'] = 'text/csv'
    
    # Add filter info to filename
    filename_parts = ['checkout_history']
    if start_date or end_date:
        filename_parts.append(f'{start_date or "start"}_to_{end_date or "end"}')
    filename_parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    response.headers['Content-Disposition'] = f'attachment; filename={"-".join(filename_parts)}.csv'
    
    return response

@app.route('/admin/user/add', methods=['POST'])
def add_user():
    """Add a new user"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    card_id = request.form.get('card_id')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (card_id, first_name, last_name) VALUES (?, ?, ?)',
                    (card_id, first_name, last_name))
        conn.commit()
    except:
        pass  # Card ID already exists, ignore
    conn.close()
    
    return redirect(url_for('admin_dashboard') + '#users')

@app.route('/admin/fob/add', methods=['POST'])
def add_fob():
    """Add a new key fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    fob_id = request.form.get('fob_id')
    vehicle_name = request.form.get('vehicle_name')
    category = request.form.get('category')
    location = request.form.get('location')
    
    conn = get_db()
    try:
        conn.execute('INSERT INTO key_fobs (fob_id, vehicle_name, category, location) VALUES (?, ?, ?, ?)',
                    (fob_id, vehicle_name, category, location))
        conn.commit()
    except:
        pass  # Fob ID already exists, ignore
    conn.close()
    
    return redirect(url_for('admin_dashboard') + '#fobs')

@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    """Edit a user"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        
        conn.execute('UPDATE users SET first_name = ?, last_name = ? WHERE id = ?',
                    (first_name, last_name, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#users')
    
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return render_template('edit_user.html', user=user)

@app.route('/admin/fob/edit/<int:fob_id>', methods=['GET', 'POST'])
def edit_fob(fob_id):
    """Edit a key fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    
    if request.method == 'POST':
        vehicle_name = request.form.get('vehicle_name')
        category = request.form.get('category')
        location = request.form.get('location')
        
        conn.execute('UPDATE key_fobs SET vehicle_name = ?, category = ?, location = ? WHERE id = ?',
                    (vehicle_name, category, location, fob_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    conn.close()
    return render_template('edit_fob.html', fob=fob)

@app.route('/admin/user/replace/<int:user_id>', methods=['GET', 'POST'])
def replace_user(user_id):
    """Replace a user's keycard"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if request.method == 'POST':
        new_card_id = request.form.get('new_card_id')
        
        # Update the card_id
        conn.execute('UPDATE users SET card_id = ? WHERE id = ?',
                    (new_card_id, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#users')
    
    conn.close()
    return render_template('replace_user.html', user=user)

@app.route('/admin/fob/replace/<int:fob_id>', methods=['GET', 'POST'])
def replace_fob(fob_id):
    """Replace a key fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if request.method == 'POST':
        new_fob_id = request.form.get('new_fob_id')
        
        # Update the fob_id
        conn.execute('UPDATE key_fobs SET fob_id = ? WHERE id = ?',
                    (new_fob_id, fob_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    conn.close()
    return render_template('replace_fob.html', fob=fob)

@app.route('/admin/fob/reserve/<int:fob_id>', methods=['GET', 'POST'])
def reserve_fob(fob_id):
    """Create a reservation for a fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if request.method == 'POST':
        user_id = request.form.get('user_id') or None
        reserved_for_name = request.form.get('reserved_for_name')
        reserved_datetime = request.form.get('reserved_datetime')
        display_hours_before = int(request.form.get('display_hours_before', 24))
        reason = request.form.get('reason')
        created_by = session.get('username', 'admin')
        
        # Convert datetime to Central time
        chicago_tz = pytz.timezone('America/Chicago')
        dt = datetime.strptime(reserved_datetime, '%Y-%m-%dT%H:%M')
        dt = chicago_tz.localize(dt)
        
        conn.execute('''
            INSERT INTO reservations (fob_id, user_id, reserved_for_name, reserved_datetime, display_hours_before, reason, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (fob_id, user_id, reserved_for_name, dt.isoformat(), display_hours_before, reason, created_by))
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', api_status())
        return redirect(url_for('admin_dashboard') + '#reservations')
    
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('reserve_fob.html', fob=fob, users=users)

@app.route('/admin/reservation/delete/<int:reservation_id>')
def delete_reservation(reservation_id):
    """Delete a reservation"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
    conn.commit()
    conn.close()
    
    # Broadcast udpate
    socketio.emit('status_update', api_status())
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/fob/barcode/<int:fob_id>')
def generate_barcode(fob_id):
    """Generate barcode for a fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    import barcode
    from barcode.writer import ImageWriter
    from io import BytesIO
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    conn.close()
    
    if not fob:
        return "Fob not found", 404
    
    # Generate barcode
    code128 = barcode.get_barcode_class('code128')
    barcode_image = code128(fob['fob_id'], writer=ImageWriter())
    
    # Save to BytesIO
    buffer = BytesIO()
    barcode_image.write(buffer, options={'write_text': True, 'module_height': 15, 'module_width': 0.3, 'font_size': 14, 'text_distance': 5})
    buffer.seek(0)
    
    # Return as downloadable PNG
    return send_file(
        buffer,
        mimetype='image/png',
        as_attachment=True,
        download_name=f'{fob["vehicle_name"]}_barcode.png'
    )

@app.route('/admin/fob/note/add/<int:fob_id>', methods=['GET', 'POST'])
def add_note(fob_id):
    """Add note to fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if request.method == 'POST':
        note_text = request.form.get('note_text')
        created_by = session.get('username', 'admin')
        
        chicago_tz = pytz.timezone('America/Chicago')
        
        # Delete existing note (one at a time)
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        
        # Insert new note
        conn.execute('''
            INSERT INTO notes (fob_id, note_text, created_at, created_by)
            VALUES (?, ?, ?, ?)
        ''', (fob_id, note_text, datetime.now(chicago_tz).isoformat(), created_by))
        
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    conn.close()
    return render_template('add_note.html', fob=fob)

@app.route('/admin/fob/note/delete/<int:fob_id>')
def delete_note(fob_id):
    """Delete note from fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_dashboard') + '#fobs')

# Schedule database compacting weekly
from threading import Thread
import time

def compact_db_weekly():
    """Background task to compact database weekly"""
    while True:
        time.sleep(604800)  # Sleep for 7 days (in seconds)
        try:
            compact_database()
        except Exception as e:
            print(f"Error compacting database: {e}")

# Start background compacting thread
compact_thread = Thread(target=compact_db_weekly, daemon=True)
compact_thread.start()

@app.route('/api/offline_sync/checkout', methods=['POST'])
@require_kiosk_auth
def offline_sync_checkout():
    """Accept offline checkout from kiosk"""
    data = request.json
    chicago_tz = pytz.timezone('America/Chicago')
    
    conn = get_db()
    
    # Find or create user
    user = conn.execute('SELECT * FROM users WHERE card_id = ?', (data['user_card_id'],)).fetchone()
    
    if not user and data.get('user_first_name') and data.get('user_last_name'):
        # Create user if doesn't exist
        conn.execute('''
            INSERT INTO users (card_id, first_name, last_name)
            VALUES (?, ?, ?)
        ''', (data['user_card_id'], data['user_first_name'], data['user_last_name']))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE card_id = ?', (data['user_card_id'],)).fetchone()
    
    # Find fob
    fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ?', (data['fob_id'],)).fetchone()
    
    if user and fob:
        # Insert checkout with original timestamp
        conn.execute('''
            INSERT INTO checkouts (user_id, fob_id, checked_out_at, kiosk_id)
            VALUES (?, ?, ?, ?)
        ''', (user['id'], fob['id'], data['timestamp'], data['kiosk_id']))
        conn.commit()
    
    conn.close()
    socketio.emit('status_update', api_status())
    return {'success': True}

@app.route('/api/offline_sync/checkin', methods=['POST'])
@require_kiosk_auth
def offline_sync_checkin():
    """Accept offline checkin from kiosk"""
    data = request.json
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ?', (data['fob_id'],)).fetchone()
    
    if fob:
        # Find active checkout and mark checked in
        conn.execute('''
            UPDATE checkouts 
            SET checked_in_at = ?
            WHERE fob_id = ? AND checked_in_at IS NULL
            ORDER BY checked_out_at DESC
            LIMIT 1
        ''', (data['timestamp'], fob['id']))
        conn.commit()
    
    conn.close()
    socketio.emit('status_update', api_status())
    return {'success': True}

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
