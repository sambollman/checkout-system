from flask import Flask, render_template, request, redirect, url_for, session, make_response, send_file
from flask_socketio import SocketIO, emit
from database import get_db, run_migrations
from datetime import datetime, timedelta
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

# Okta proxy authentication (production)
OKTA_HEADER = os.getenv('OKTA_HEADER', '')  # Set to 'X-Auth-Proxy-Username' in production

# Admin users authorized to access admin panel
# I took this out, going to use admin database

def get_authenticated_user():
    """Get authenticated user from proxy header (if configured)"""
    if OKTA_HEADER:
        return request.headers.get(OKTA_HEADER)
    return None

def is_admin_user(username):
    """Check if user is authorized for admin access"""
    conn = get_db()
    admin = conn.execute('SELECT * FROM admin_users WHERE LOWER(username) = LOWER(?)', (username,)).fetchone()
    conn.close()
    return admin is not None


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')
socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')  # Empty = disable password login

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
            kf.is_available,
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

    # Get active reservations (moved up to get chicago_tz)
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz)
    
    # Get notes and delete expired ones
    all_notes = conn.execute("SELECT * FROM notes").fetchall()
    notes = []
    expired_note_ids = []
    
    for note in all_notes:
        if note['expires_at']:
            try:
                expires = datetime.fromisoformat(note['expires_at'])
                if expires > now:
                    notes.append(note)
                else:
                    expired_note_ids.append(note['id'])
            except:
                notes.append(note)
        else:
            notes.append(note)
    
    # Delete expired notes from database
    if expired_note_ids:
        placeholders = ','.join('?' * len(expired_note_ids))
        conn.execute(f'DELETE FROM notes WHERE id IN ({placeholders})', expired_note_ids)
        conn.commit()
    
    # Create note map
    note_map = {}
    for note in notes:
        note_map[note['fob_id']] = note

    reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.id as fob_table_id
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        WHERE (
              datetime(r.reserved_datetime) > datetime(?)
              OR (r.end_datetime IS NOT NULL AND datetime(r.end_datetime) > datetime(?))
          )
          AND (
              r.display_hours_before = 0
              OR datetime(r.reserved_datetime, '-' || r.display_hours_before || ' hours') <= datetime(?)
          )
    '''
    reservations = conn.execute(reservations_query, (now.isoformat(), now.isoformat(), now.isoformat())).fetchall()


    
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
        if res['fob_table_id'] not in reservation_map:
            reservation_map[res['fob_table_id']] = res
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
            res_dict = dict(res)
            # Format reservation datetime to match checkout time format
            if res_dict.get('reserved_datetime'):
                try:
                    dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['reserved_datetime'] = dt.strftime('%b %d, %Y %H:%M')
                except:
                    pass
            if res_dict.get('end_datetime'):
                try:
                    dt = datetime.fromisoformat(res_dict['end_datetime'])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['end_datetime'] = dt.strftime('%b %d, %Y %H:%M')
                except:
                    pass
            key_dict['reservation'] = res_dict
        else:
            key_dict['reservation'] = None

        formatted_keys.append(key_dict)
    
     # Group by category with natural sorting
    import re
    
    def natural_sort_key(item):
        """Sort key that handles numbers naturally"""
        return [int(text) if text.isdigit() else text.lower() 
                for text in re.split('([0-9]+)', item['vehicle_name'])]
    
    # Group by category with natural sorting
    squad_cars = sorted([k for k in formatted_keys if k['category'] == 'Squad Cars'], 
                       key=natural_sort_key)
    specialized_vehicles = sorted([k for k in formatted_keys if k['category'] == 'Specialized Services Vehicles'],
                         key=natural_sort_key)
    cid_vehicles = sorted([k for k in formatted_keys if k['category'] == 'CID Vehicles'], 
                         key=natural_sort_key)
    other_vehicles = sorted([k for k in formatted_keys if k['category'] == 'Other Vehicles'], 
                       key=natural_sort_key)
    pool_cars = sorted([k for k in formatted_keys if k['category'] == 'Pool Cars'], 
                       key=natural_sort_key)
    admin_cars = sorted([k for k in formatted_keys if k['category'] == 'Admin Cars'], 
                       key=natural_sort_key)
    # Equipment and Key Rings: Sort by checked-out status first, then alphabetically
    def status_then_name_sort(item):
        # Return tuple: (0 if checked out, 1 if available), then natural sort key
        sort_priority = 0 if item.get('checkout_id') else 1
        name_parts = [int(text) if text.isdigit() else text.lower() 
                     for text in re.split('([0-9]+)', item['vehicle_name'])]
        return (sort_priority, name_parts)
    
    equipment = sorted([k for k in formatted_keys if k['category'] == 'Equipment'], 
                      key=status_then_name_sort)
    key_rings = sorted([k for k in formatted_keys if k['category'] == 'Key Rings'], 
                       key=status_then_name_sort)

    
    return render_template('index.html',
                      squad_cars=squad_cars,
                      specialized_vehicles=specialized_vehicles,
                      cid_vehicles=cid_vehicles,
                      other_vehicles=other_vehicles,
                      pool_cars=pool_cars,
                      admin_cars=admin_cars,
                      equipment=equipment,
                      key_rings=key_rings,
                      okta_mode=bool(OKTA_HEADER))
def get_current_status():
    """Get current equipment status - shared logic for API and WebSocket broadcasts"""
    conn = get_db()
    
    # Get all active key fobs with their current checkout status
    query = '''
        SELECT 
            kf.id,
            kf.fob_id,
            kf.vehicle_name,
            kf.category,
            kf.location,
            kf.is_available,
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
    
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz)
    
    # Get notes and filter expired ones
    all_notes = conn.execute("SELECT * FROM notes").fetchall()
    notes = []
    for note in all_notes:
        if note['expires_at']:
            try:
                expires = datetime.fromisoformat(note['expires_at'])
                if expires > now:
                    notes.append(note)
            except:
                notes.append(note)
        else:
            notes.append(note)
    
    # Create note map
    note_map = {}
    for note in notes:
        note_map[note['fob_id']] = note

    # Get active reservations
    reservations_query = '''
        SELECT r.*, u.first_name, u.last_name, kf.id as fob_table_id
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN key_fobs kf ON r.fob_id = kf.id
        WHERE (
              datetime(r.reserved_datetime) > datetime(?)
              OR (r.end_datetime IS NOT NULL AND datetime(r.end_datetime) > datetime(?))
          )
          AND (
              r.display_hours_before = 0
              OR datetime(r.reserved_datetime, '-' || r.display_hours_before || ' hours') <= datetime(?)
          )
        ORDER BY r.reserved_datetime ASC
    '''
    reservations = conn.execute(reservations_query, (now.isoformat(), now.isoformat(), now.isoformat())).fetchall()
    
    # Format reservation datetimes
    formatted_reservations = []
    for res in reservations:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                res_dict['reserved_datetime'] = dt.strftime('%a, %b %d at %I:%M %p')
            except:
                pass
        formatted_reservations.append(res_dict)

    # Create a dict of fob_id -> reservation
    reservation_map = {}
    for res in reservations:
        if res['fob_table_id'] not in reservation_map:
            reservation_map[res['fob_table_id']] = res
    conn.close()
    
    # Format timestamps
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
            res_dict = dict(res)
            # Format reservation datetime to match checkout time format
            if res_dict.get('reserved_datetime'):
                try:
                    dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    res_dict['reserved_datetime'] = dt.strftime('%b %d, %Y %H:%M')
                except:
                    pass
            key_dict['reservation'] = res_dict
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
    
    squad_cars = sorted([k for k in formatted_keys if k['category'] == 'Squad Cars'], 
                       key=natural_sort_key)
    specialized_vehicles = sorted([k for k in formatted_keys if k['category'] == 'Specialized Services Vehicles'],
                         key=natural_sort_key)
    cid_vehicles = sorted([k for k in formatted_keys if k['category'] == 'CID Vehicles'], 
                         key=natural_sort_key)
    other_vehicles = sorted([k for k in formatted_keys if k['category'] == 'Other Vehicles'], 
                       key=natural_sort_key)
    pool_cars = sorted([k for k in formatted_keys if k['category'] == 'Pool Cars'], 
                       key=natural_sort_key)
    admin_cars = sorted([k for k in formatted_keys if k['category'] == 'Admin Cars'], 
                       key=natural_sort_key)
    # Equipment and Key Rings: Sort by checked-out status first, then alphabetically
    def status_then_name_sort(item):
        # Return tuple: (0 if checked out, 1 if available), then natural sort key
        sort_priority = 0 if item.get('checkout_id') else 1
        name_parts = [int(text) if text.isdigit() else text.lower() 
                     for text in re.split('([0-9]+)', item['vehicle_name'])]
        return (sort_priority, name_parts)
    
    equipment = sorted([k for k in formatted_keys if k['category'] == 'Equipment'], 
                      key=status_then_name_sort)
    key_rings = sorted([k for k in formatted_keys if k['category'] == 'Key Rings'], 
                       key=status_then_name_sort)
    
    return {
        'squad_cars': squad_cars,
        'specialized_vehicles': specialized_vehicles,
        'cid_vehicles': cid_vehicles,
        'other_vehicles': other_vehicles,
        'pool_cars': pool_cars,
        'admin_cars': admin_cars,
        'equipment': equipment,
        'key_rings': key_rings,
        'active_reservations': formatted_reservations
    }

@app.route('/api/status')
@require_kiosk_auth
def api_status():
    """API endpoint to get current key status as JSON (requires kiosk auth)"""
    return get_current_status()


@app.route('/api/vehicle/<int:fob_id>')
def api_vehicle_detail(fob_id):
    """Get vehicle details including assignments and recent history"""
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    
    # Get fob details
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    if not fob:
        conn.close()
        return {'error': 'Not found'}, 404
    
    fob_dict = dict(fob)
    
    # Get assignments
    assignments = conn.execute('''
        SELECT va.shift, u.first_name, u.last_name
        FROM vehicle_assignments va
        JOIN users u ON va.user_id = u.id
        WHERE va.fob_id = ?
        ORDER BY va.shift
    ''', (fob_id,)).fetchall()
    fob_dict['assignments'] = [dict(a) for a in assignments]
    
    # Get recent checkout history (last 10)
    history = conn.execute('''
        SELECT u.first_name, u.last_name, c.checked_out_at, c.checked_in_at, c.kiosk_id
        FROM checkouts c
        JOIN users u ON c.user_id = u.id
        WHERE c.fob_id = ?
        ORDER BY c.checked_out_at DESC
        LIMIT 10
    ''', (fob_id,)).fetchall()
    
    formatted_history = []
    for h in history:
        h_dict = dict(h)
        if h_dict['checked_out_at']:
            try:
                dt = datetime.fromisoformat(h_dict['checked_out_at'])
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                dt = dt.astimezone(chicago_tz)
                h_dict['checked_out_at'] = dt.strftime('%b %d, %Y %I:%M %p')
            except:
                pass
        if h_dict['checked_in_at']:
            try:
                dt = datetime.fromisoformat(h_dict['checked_in_at'])
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                dt = dt.astimezone(chicago_tz)
                h_dict['checked_in_at'] = dt.strftime('%b %d, %Y %I:%M %p')
            except:
                pass
        formatted_history.append(h_dict)
    
    fob_dict['history'] = formatted_history
    conn.close()
    return fob_dict

@app.route('/api/notify', methods=['POST'])
@require_kiosk_auth
def api_notify():
    """Receive notification from kiosk that status changed"""
    # Broadcast update to all connected clients
    socketio.emit('status_update', get_current_status())
    return {'status': 'ok'}

@app.route('/api/user/register', methods=['POST'])
@require_kiosk_auth
def register_user():
    """Register a new user from kiosk"""
    data = request.get_json()
    
    card_id = data.get('card_id')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    
    if not card_id or not first_name or not last_name:
        return {'error': 'Missing required fields'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    # Check if card already exists
    existing = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (card_id,)).fetchone()
    if existing:
        conn.close()
        return {'error': 'Card ID already registered'}, 400
    
    # Insert new user
    try:
        conn.execute('''
            INSERT INTO users (card_id, first_name, last_name, registered_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        ''', (card_id, first_name, last_name, datetime.now(chicago_tz).isoformat()))
        conn.commit()

        # Get the newly created user BEFORE closing connection
        user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (card_id,)).fetchone()
        user_dict = dict(user)
        conn.close()

        return {
            'status': 'success', 
            'message': 'User registered successfully',
            'user': user_dict
        }, 201
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/equipment/register', methods=['POST'])
@require_kiosk_auth
def register_equipment():
    """Register new equipment from kiosk"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')
    vehicle_name = data.get('vehicle_name')
    category = data.get('category', 'Equipment')
    location = data.get('location', 'Station')
    
    if not fob_id or not vehicle_name:
        return {'error': 'Missing required fields'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    # Check if fob already exists
    existing = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE', (fob_id,)).fetchone()
    if existing:
        conn.close()
        return {'error': 'Fob ID already registered'}, 400
    
    # Check if vehicle name already exists (for active equipment)
    existing_name = conn.execute('''
        SELECT * FROM key_fobs 
        WHERE vehicle_name = ? COLLATE NOCASE 
        AND is_active = 1
    ''', (vehicle_name,)).fetchone()
    if existing_name:
        conn.close()
        return {'error': f'Vehicle name "{vehicle_name}" is already registered'}, 400
    # Insert new equipment
    try:
        conn.execute('''
            INSERT INTO key_fobs (fob_id, vehicle_name, category, location, registered_at, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (fob_id, vehicle_name, category, location, datetime.now(chicago_tz).isoformat()))
        conn.commit()
        # Get the newly created equipment
        equipment = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE', (fob_id,)).fetchone()
        equipment_dict = dict(equipment)
        conn.close()
        return {
            'status': 'success',
            'message': 'Equipment registered successfully', 
            'equipment': equipment_dict
        }, 201
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/checkout', methods=['POST'])
@require_kiosk_auth
def api_checkout():
    """Checkout a fob to a user"""
    data = request.get_json()
    
    user_id = data.get('user_id')
    fob_id = data.get('fob_id')
    
    if not user_id or not fob_id:
        return {'error': 'Missing user_id or fob_id'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        # Insert checkout
        conn.execute('''
            INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, fob_id, data.get('kiosk_id', 'station'), datetime.now(chicago_tz).isoformat()))
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Checked out successfully'}, 201
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/checkin', methods=['POST'])
@require_kiosk_auth  
def api_checkin():
    """Check in a fob"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')
    
    if not fob_id:
        return {'error': 'Missing fob_id'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        # Get the key_fobs table id from fob_id
        fob = conn.execute('SELECT id FROM key_fobs WHERE fob_id = ? COLLATE NOCASE', (fob_id,)).fetchone()
        
        if not fob:
            conn.close()
            return {'error': 'Fob not found'}, 404
        
        # Update the active checkout
        conn.execute('''
            UPDATE checkouts
            SET checked_in_at = ?
            WHERE fob_id = ? AND checked_in_at IS NULL
        ''', (datetime.now(chicago_tz).isoformat(), fob['id']))
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Checked in successfully'}, 200
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500


@app.route('/api/mark_unavailable', methods=['POST'])
@require_kiosk_auth
def api_mark_unavailable():
    """Mark a fob as unavailable"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')
    user_id = data.get('user_id')
    reason = data.get('reason', '')
    
    if not fob_id:
        return {'error': 'Missing fob_id'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        conn.execute('''
            UPDATE key_fobs SET is_available = 0 WHERE id = ?
        ''', (fob_id,))
        
        # Add a note if reason provided
        if reason:
            # Remove existing note first
            conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
            conn.execute('''
                INSERT INTO notes (fob_id, note_text, created_at)
                VALUES (?, ?, ?)
            ''', (fob_id, f'UNAVAILABLE: {reason}', datetime.now(chicago_tz).isoformat()))
        
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Marked as unavailable'}, 200
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/mark_available', methods=['POST'])
@require_kiosk_auth
def api_mark_available():
    """Mark a fob as available"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')
    user_id = data.get('user_id')
    
    if not fob_id:
        return {'error': 'Missing fob_id'}, 400
    
    conn = get_db()
    
    try:
        conn.execute('''
            UPDATE key_fobs SET is_available = 1 WHERE id = ?
        ''', (fob_id,))
        
        # Remove unavailable note if it exists
        conn.execute("""
            DELETE FROM notes WHERE fob_id = ? AND note_text LIKE 'UNAVAILABLE:%'
        """, (fob_id,))
        
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Marked as available'}, 200
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/lookup', methods=['POST'])
@require_kiosk_auth
def api_lookup():
    """Lookup user, equipment, or checkout status by ID"""
    data = request.get_json()
    
    lookup_type = data.get('type')  # 'user', 'fob', 'scan'
    identifier = data.get('id')
    
    if not lookup_type or not identifier:
        return {'error': 'Missing type or id'}, 400
    
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    
    try:
        if lookup_type == 'user':
            # Look up user by card_id
            user = conn.execute('''
                SELECT * FROM users 
                WHERE card_id = ? COLLATE NOCASE AND is_active = 1
            ''', (identifier,)).fetchone()
            conn.close()
            
            if user:
                return {'found': True, 'type': 'user', 'data': dict(user)}, 200
            else:
                return {'found': False}, 200
                
        elif lookup_type == 'fob':
            # Look up equipment by fob_id with checkout status
            result = conn.execute('''
                SELECT kf.*, c.id as checkout_id, c.checked_out_at, 
                       u.first_name, u.last_name, u.id as user_id
                FROM key_fobs kf
                LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
                LEFT JOIN users u ON c.user_id = u.id
                WHERE kf.fob_id = ? COLLATE NOCASE AND kf.is_active = 1
            ''', (identifier,)).fetchone()
            
            # Get note if exists
            note = None
            reservation = None
            if result:
                note_row = conn.execute('''
                    SELECT * FROM notes WHERE fob_id = ?
                ''', (result['id'],)).fetchone()
                if note_row:
                    note = dict(note_row)
                
                # Get active reservation if exists
                chicago_tz = pytz.timezone('America/Chicago')
                now = datetime.now(chicago_tz)
                
                reservation_rows = conn.execute('''
                    SELECT r.*, u.first_name, u.last_name
                    FROM reservations r
                    LEFT JOIN users u ON r.user_id = u.id
                    WHERE r.fob_id = ?
                    ORDER BY r.reserved_datetime ASC
                ''', (result['id'],)).fetchall()
                
                # Check which reservations are active
                for res in reservation_rows:
                    try:
                        res_dt = datetime.fromisoformat(res['reserved_datetime'])
                        display_start = res_dt - timedelta(hours=res['display_hours_before'])
                        print(f"  Reserved time: {res_dt}")
                        print(f"  Display start: {display_start}")
                        print(f"  Current time: {now}")
                        print(f"  res_dt > now: {res_dt > now}")
                        print(f"  display_start <= now: {display_start <= now}")
                        if res_dt > now and display_start <= now:
                            reservation = dict(res)
                            print(f"  ✓ ACTIVE RESERVATION FOUND!")
                            break
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        pass
            
            conn.close()
            
            if result:
                fob_dict = dict(result)
                fob_dict['note'] = note
                fob_dict['reservation'] = reservation
                return {'found': True, 'type': 'fob', 'data': fob_dict}, 200
            else:
                return {'found': False}, 200
                
        elif lookup_type == 'scan':
            # Universal lookup - check if it's a user or fob
            user = conn.execute('''
                SELECT * FROM users WHERE card_id = ? COLLATE NOCASE
            ''', (identifier,)).fetchone()
            
            fob = conn.execute('''
                SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE
            ''', (identifier,)).fetchone()
            
            conn.close()
            
            if user:
                return {'found': True, 'type': 'user', 'data': dict(user)}, 200
            elif fob:
                return {'found': True, 'type': 'fob', 'data': dict(fob)}, 200
            else:
                return {'found': False}, 200
        
        else:
            conn.close()
            return {'error': 'Invalid lookup type'}, 400
            
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/search/users', methods=['POST'])
@require_kiosk_auth
def api_search_users():
    """Search users by name or card_id"""
    data = request.get_json()
    search = data.get('search', '')
    
    conn = get_db()
    
    try:
        users = conn.execute('''
            SELECT * FROM users 
            WHERE last_name LIKE ? OR card_id LIKE ?
        ''', (f'%{search}%', f'%{search}%')).fetchall()
        conn.close()
        
        user_list = [dict(user) for user in users]
        return {'users': user_list}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/list/equipment', methods=['GET'])
@require_kiosk_auth
def api_list_equipment():
    """List all active equipment with checkout status"""
    conn = get_db()
    
    try:
        equipment = conn.execute('''
            SELECT kf.*, c.id as checkout_id, c.checked_out_at, 
                   u.first_name, u.last_name
            FROM key_fobs kf
            LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
            LEFT JOIN users u ON c.user_id = u.id
            WHERE kf.is_active = 1
            ORDER BY kf.category, kf.vehicle_name
        ''').fetchall()
        conn.close()
        
        equipment_list = [dict(item) for item in equipment]
        return {'equipment': equipment_list}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/search/equipment', methods=['POST'])
@require_kiosk_auth
def api_search_equipment():
    """Search equipment by name"""
    data = request.get_json()
    search = data.get('search', '')
    
    conn = get_db()
    
    try:
        equipment = conn.execute('''
            SELECT * FROM key_fobs 
            WHERE vehicle_name LIKE ? AND is_active = 1
        ''', (f'%{search}%',)).fetchall()
        conn.close()
        
        equipment_list = [dict(item) for item in equipment]
        return {'equipment': equipment_list}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

# Admin login - only available if ADMIN_PASSWORD is set AND not in OKTA mode
if ADMIN_PASSWORD and not OKTA_HEADER:
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        """Admin login page (development/emergency use only)"""
        next_url = request.args.get('next') or request.form.get('next')
        if request.method == 'POST':
            password = request.form.get('password')
            if password == ADMIN_PASSWORD:
                session['admin'] = True
                if next_url:
                    return redirect(next_url)
                return redirect(url_for('admin_dashboard'))
            else:
                return render_template('admin_login.html', error='Invalid password', next=next_url)
        
        return render_template('admin_login.html', next=next_url)

@app.route('/api/bulk_checkout', methods=['POST'])
@require_kiosk_auth
def api_bulk_checkout():
    """Bulk checkout multiple items to a user"""
    data = request.get_json()
    
    user_id = data.get('user_id')
    fob_ids = data.get('fob_ids', [])  # List of fob table IDs
    kiosk_id = data.get('kiosk_id', 'station')
    
    if not user_id or not fob_ids:
        return {'error': 'Missing user_id or fob_ids'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    checked_out = []
    errors = []
    
    try:
        for fob_id in fob_ids:
            try:
                # Check if already checked out
                existing = conn.execute('''
                    SELECT c.*, u.id as user_id
                    FROM checkouts c
                    JOIN users u ON c.user_id = u.id
                    WHERE c.fob_id = ? AND c.checked_in_at IS NULL
                ''', (fob_id,)).fetchone()
                
                if existing:
                    # Handoff transfer
                    if existing['user_id'] != user_id:
                        # Check in from previous user
                        conn.execute('''
                            UPDATE checkouts SET checked_in_at = ? WHERE id = ?
                        ''', (datetime.now(chicago_tz).isoformat(), existing['id']))
                        # Check out to new user
                        conn.execute('''
                            INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at)
                            VALUES (?, ?, ?, ?)
                        ''', (user_id, fob_id, kiosk_id, datetime.now(chicago_tz).isoformat()))
                        checked_out.append(fob_id)
                    # else: already checked out to this user, skip
                else:
                    # Normal checkout
                    conn.execute('''
                        INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, fob_id, kiosk_id, datetime.now(chicago_tz).isoformat()))
                    checked_out.append(fob_id)
                    
            except Exception as e:
                errors.append({'fob_id': fob_id, 'error': str(e)})
        
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {
            'status': 'success',
            'checked_out': checked_out,
            'errors': errors
        }, 201
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/barns_transfer', methods=['POST'])
@require_kiosk_auth
def api_barns_transfer():
    """Transfer a vehicle to The Barns"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')  # key_fobs table ID
    kiosk_id = data.get('kiosk_id', 'station')
    
    if not fob_id:
        return {'error': 'Missing fob_id'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        # Get or create The Barns user
        barns_user = conn.execute('''
            SELECT * FROM users WHERE card_id = ? COLLATE NOCASE
        ''', ('BARNS',)).fetchone()
        
        if not barns_user:
            conn.execute('''
                INSERT INTO users (card_id, first_name, last_name, is_active)
                VALUES (?, ?, ?, ?)
            ''', ('BARNS', 'The', 'Barns', 1))
            conn.commit()
            barns_user = conn.execute('''
                SELECT * FROM users WHERE card_id = ? COLLATE NOCASE
            ''', ('BARNS',)).fetchone()
        
        # Check current checkout status
        current_checkout = conn.execute('''
            SELECT * FROM checkouts WHERE fob_id = ? AND checked_in_at IS NULL
        ''', (fob_id,)).fetchone()
        
        if current_checkout:
            # Check in from current user
            conn.execute('''
                UPDATE checkouts SET checked_in_at = ? WHERE id = ?
            ''', (datetime.now(chicago_tz).isoformat(), current_checkout['id']))
        
        # Check out to The Barns
        conn.execute('''
            INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at)
            VALUES (?, ?, ?, ?)
        ''', (barns_user['id'], fob_id, kiosk_id, datetime.now(chicago_tz).isoformat()))
        
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Transferred to The Barns'}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/user/replace_card', methods=['POST'])
@require_kiosk_auth
def api_replace_card():
    """Replace a user's card ID"""
    data = request.get_json()
    
    user_id = data.get('user_id')
    new_card_id = data.get('new_card_id')
    
    if not user_id or not new_card_id:
        return {'error': 'Missing user_id or new_card_id'}, 400
    
    conn = get_db()
    
    try:
        # Check if new card ID already exists
        existing = conn.execute('''
            SELECT * FROM users WHERE card_id = ? COLLATE NOCASE
        ''', (new_card_id,)).fetchone()
        
        if existing:
            conn.close()
            return {'error': 'Card ID already in use'}, 400
        
        # Update the card ID
        conn.execute('''
            UPDATE users SET card_id = ? WHERE id = ?
        ''', (new_card_id, user_id))
        conn.commit()
        conn.close()
        
        return {'status': 'success', 'message': 'Card replaced'}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/equipment/replace_fob', methods=['POST'])
@require_kiosk_auth
def api_equipment_replace_fob():
    """Replace a fob ID for existing equipment"""
    data = request.get_json()
    
    equipment_id = data.get('equipment_id')
    new_fob_id = data.get('new_fob_id')
    
    if not equipment_id or not new_fob_id:
        return {'error': 'Missing equipment_id or new_fob_id'}, 400
    
    conn = get_db()
    
    try:
        # Check if new fob_id already exists
        existing = conn.execute('''
            SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE
        ''', (new_fob_id,)).fetchone()
        
        if existing:
            conn.close()
            return {'error': 'This fob ID is already registered'}, 400
        
        # Update the fob_id
        conn.execute('''
            UPDATE key_fobs 
            SET fob_id = ?
            WHERE id = ?
        ''', (new_fob_id, equipment_id))
        
        conn.commit()
        conn.close()
        
        return {'success': True}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500


@app.route('/api/note/delete', methods=['POST'])
@require_kiosk_auth
def api_delete_note():
    """Delete a note from a fob"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')  # key_fobs table ID
    
    if not fob_id:
        return {'error': 'Missing fob_id'}, 400
    
    conn = get_db()
    
    try:
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Note deleted'}, 200
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500

@app.route('/api/note/add', methods=['POST'])
@require_kiosk_auth
def api_add_note():
    """Add or replace a note on a fob"""
    data = request.get_json()
    
    fob_id = data.get('fob_id')  # key_fobs table ID
    note_text = data.get('note_text')
    expires_at = data.get('expires_at')  # Optional ISO datetime string
    created_by = data.get('created_by', 'kiosk')
    
    if not fob_id or not note_text:
        return {'error': 'Missing fob_id or note_text'}, 400
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        # Delete existing note (one note per fob)
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        
        # Insert new note
        conn.execute('''
            INSERT INTO notes (fob_id, note_text, created_at, created_by, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (fob_id, note_text, datetime.now(chicago_tz).isoformat(), created_by, expires_at))
        
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        
        return {'status': 'success', 'message': 'Note added'}, 201
        
    except Exception as e:
        conn.close()
        return {'error': str(e)}, 500



@app.route('/admin/logout')
def admin_logout():
    """Logout admin"""
    session.pop('admin', None)
    return redirect(url_for('index'))

@app.route('/inspect/<int:fob_id>')
def inspect_vehicle(fob_id):
    """Vehicle inspection landing page"""
    username = get_authenticated_user()
    if not username:
        if not session.get('admin'):
            return redirect(f'/admin/login?next=/inspect/{fob_id}')
        username = session.get('username', 'Admin')

    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    conn.close()
    
    if not fob:
        return "Vehicle not found", 404

    return render_template('inspection_landing.html', fob=fob, inspector=username)

@app.route('/inspect/<int:fob_id>/cleanliness', methods=['GET', 'POST'])
def inspect_cleanliness(fob_id):
    """Monthly cleanliness inspection form"""
    username = get_authenticated_user()
    if not username:
        if not session.get('admin'):
            return redirect(f'/admin/login?next=/inspect/{fob_id}/cleanliness')
        username = session.get('username', 'Admin')

    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if not fob:
        conn.close()
        return "Vehicle not found", 404

    if request.method == 'POST':
        chicago_tz = pytz.timezone('America/Chicago')
        exterior_clean = 1 if request.form.get('exterior_clean') == '1' else 0
        interior_vacuumed = 1 if request.form.get('interior_vacuumed') == '1' else 0
        wiped_dashboard = 1 if request.form.get('wiped_dashboard') else 0
        wiped_center_console = 1 if request.form.get('wiped_center_console') else 0
        wiped_windows = 1 if request.form.get('wiped_windows') else 0
        wiped_interior_doors = 1 if request.form.get('wiped_interior_doors') else 0
        wiped_backseats = 1 if request.form.get('wiped_backseats') else 0
        wiped_keyboard_mdc = 1 if request.form.get('wiped_keyboard_mdc') else 0
        comments = request.form.get('comments')
        
        conn.execute('''
            INSERT INTO cleanliness_inspections (
                fob_id, inspector, inspected_at,
                exterior_clean, interior_vacuumed,
                wiped_dashboard, wiped_center_console, wiped_windows,
                wiped_interior_doors, wiped_backseats, wiped_keyboard_mdc,
                comments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            fob_id, username, datetime.now(chicago_tz).isoformat(),
            exterior_clean, interior_vacuumed,
            wiped_dashboard, wiped_center_console, wiped_windows,
            wiped_interior_doors, wiped_backseats, wiped_keyboard_mdc,
            comments
        ))
        conn.commit()
        inspection_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        # Check for issues and email quartermaster
        issues = []
        if not exterior_clean: issues.append("Exterior not clean")
        if not interior_vacuumed: issues.append("Interior not vacuumed")
        if not wiped_dashboard: issues.append("Dashboard not wiped")
        if not wiped_center_console: issues.append("Center console not wiped")
        if not wiped_windows: issues.append("Windows not wiped")
        if not wiped_interior_doors: issues.append("Interior doors not wiped")
        if not wiped_backseats: issues.append("Backseats not wiped")
        if not wiped_keyboard_mdc: issues.append("Keyboard/MDC not wiped")
        
        if issues:
            from email_utils import send_inspection_issues_to_quartermaster
            send_inspection_issues_to_quartermaster(
                vehicle_name=fob['vehicle_name'],
                inspection_type='cleanliness',
                inspector=username,
                inspected_at=datetime.now(chicago_tz).strftime('%B %d, %Y at %I:%M %p'),
                issues=issues,
                comments=comments,
                fob_id=fob_id,
                inspection_id=inspection_id
            )
        
        # Mark any pending assignments as completed
        conn = get_db()
        conn.execute('''
            UPDATE inspection_assignments 
            SET completed_at = ?, completed_inspection_id = ?
            WHERE fob_id = ? AND inspection_type = ? AND completed_at IS NULL
        ''', (datetime.now(chicago_tz).isoformat(), inspection_id, fob_id, 'cleanliness'))
        conn.commit()
        conn.close()
        
        return render_template('inspection_success.html', vehicle_name=fob['vehicle_name'], inspection_type='Monthly Cleanliness')

    conn.close()
    return render_template('cleanliness_form.html', fob=fob, inspector=username)

@app.route('/inspect/<int:fob_id>/quarterly', methods=['GET', 'POST'])
def inspect_quarterly(fob_id):
    """Quarterly inventory inspection form"""
    username = get_authenticated_user()
    if not username:
        if not session.get('admin'):
            return redirect(f'/admin/login?next=/inspect/{fob_id}/quarterly')
        username = session.get('username', 'Admin')

    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if not fob:
        conn.close()
        return "Vehicle not found", 404

    if request.method == 'POST':
        chicago_tz = pytz.timezone('America/Chicago')
        fields = [
            'registration_current', 'tires_inflated', 'compartment_clean',
            'light_bar_working', 'mdc_working', 'radio_working', 'radar_working',
            'scanner_working', 'axon_camera_working', 'spotlight_working',
            'seatbelts_working', 'headlights_working', 'trunk_clean',
            'spare_tire_inflated', 'ar15_present', 'backpack_present',
            'phone_charger_present', 'evidence_bag_present', 'aed_present',
            'tuning_forks_present', 'ice_scraper_present',
            'firstaid_large_gloves', 'firstaid_cloth_tape', 'firstaid_trauma_shears',
            'firstaid_bandaids', 'firstaid_gauze', 'firstaid_alcohol_prep',
            'firstaid_tourniquets', 'firstaid_chest_seals', 'firstaid_sroll_gauze',
            'bio_hazard_kit', 'printer_paper', 'tape_measure', 'emergency_blanket',
            'fire_extinguisher', 'traffic_vest', 'ripp_restraint', 'red_cone',
            'barrier_tape', 'pet_carrier', 'red_paint', 'code100_mask', 'riot_baton',
            'sani_wipes', 'sharps_container', 'stop_sticks', 'water_rescue_bag',
            'window_punch', 'spit_hood', 'citation_book', 'parking_ticket_book'
        ]
        
        values = [fob_id, username, datetime.now(chicago_tz).isoformat()]
        for field in fields:
            val = request.form.get(field)
            if val == '1':
                values.append(1)
            elif val == '0':
                values.append(0)
            else:
                values.append(1 if request.form.get(field) else 0)
        values.append(request.form.get('comments'))
        
        placeholders = ', '.join(['?' for _ in range(len(fields) + 4)])
        field_names = 'fob_id, inspector, inspected_at, ' + ', '.join(fields) + ', comments'
        
        conn.execute(f'INSERT INTO quarterly_inspections ({field_names}) VALUES ({placeholders})', values)
        conn.commit()
        inspection_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        # Build field values dict to check for issues
        field_values = {}
        for i, field in enumerate(fields):
            field_values[field] = values[i + 3]  # offset by fob_id, inspector, inspected_at
        
        field_labels = {
            'registration_current': 'Vehicle registration current and properly displayed',
            'tires_inflated': 'Tires properly inflated',
            'compartment_clean': 'Passenger compartment clean',
            'light_bar_working': 'Light bar working properly',
            'mdc_working': 'MDC clean and working properly',
            'radio_working': 'Police radio working properly',
            'radar_working': 'RADAR working properly',
            'scanner_working': 'Scanner working properly',
            'axon_camera_working': 'AXON Fleet Camera working properly',
            'spotlight_working': 'Spotlight working properly',
            'seatbelts_working': 'Seat belts working properly',
            'headlights_working': 'Headlights, tail lights, and turn signals working properly',
            'trunk_clean': 'Trunk clean and organized',
            'spare_tire_inflated': 'Spare tire properly inflated',
            'ar15_present': 'AR-15 Rifle present',
            'backpack_present': 'Backpack with helmet/plates/mags present',
            'phone_charger_present': 'Cell Phone Charger present',
            'evidence_bag_present': 'Clear evidence bag present',
            'aed_present': 'AED present',
            'tuning_forks_present': 'Tuning Forks present',
            'ice_scraper_present': 'Ice Scraper present',
            'firstaid_large_gloves': 'First Aid: Large Gloves',
            'firstaid_cloth_tape': 'First Aid: Cloth Tape',
            'firstaid_trauma_shears': 'First Aid: Trauma Shears',
            'firstaid_bandaids': 'First Aid: Bandaids',
            'firstaid_gauze': 'First Aid: 4x4 Gauze',
            'firstaid_alcohol_prep': 'First Aid: Alcohol Prep Pads',
            'firstaid_tourniquets': 'First Aid: Tourniquets',
            'firstaid_chest_seals': 'First Aid: Chest Seals',
            'firstaid_sroll_gauze': 'First Aid: S-Roll Gauze',
            'bio_hazard_kit': 'BIO Hazard Kit present',
            'printer_paper': 'Printer Paper present',
            'tape_measure': 'Tape Measure present',
            'emergency_blanket': 'Emergency Blanket present',
            'fire_extinguisher': 'Fire Extinguisher present',
            'traffic_vest': 'Traffic Vest present',
            'ripp_restraint': 'RIPP Restraint present',
            'red_cone': 'Red Cone present',
            'barrier_tape': 'Yellow Barrier Tape present',
            'pet_carrier': 'Pet Carrier present',
            'red_paint': 'Red Paint present',
            'code100_mask': 'Code 100 Mask Kit present',
            'riot_baton': 'Riot Baton present',
            'sani_wipes': 'Sani Wipes present',
            'sharps_container': 'Sharps Container present',
            'stop_sticks': 'Stop Sticks present',
            'water_rescue_bag': 'Water Rescue Bag present',
            'window_punch': 'Window Punch present',
            'spit_hood': 'Spit Hood present',
            'citation_book': 'Citation/Warning Book present',
            'parking_ticket_book': 'Parking Ticket Book present',
        }
        
        issues = [label for field, label in field_labels.items() if field_values.get(field) == 0]
        comments = request.form.get('comments')
        
        if issues:
            from email_utils import send_inspection_issues_to_quartermaster
            send_inspection_issues_to_quartermaster(
                vehicle_name=fob['vehicle_name'],
                inspection_type='quarterly',
                inspector=username,
                inspected_at=datetime.now(chicago_tz).strftime('%B %d, %Y at %I:%M %p'),
                issues=issues,
                comments=comments,
                fob_id=fob_id,
                inspection_id=inspection_id
            )
        
        # Mark any pending assignments as completed
        conn2 = get_db()
        conn2.execute('''
            UPDATE inspection_assignments 
            SET completed_at = ?, completed_inspection_id = ?
            WHERE fob_id = ? AND inspection_type = ? AND completed_at IS NULL
        ''', (datetime.now(chicago_tz).isoformat(), inspection_id, fob_id, 'quarterly'))
        conn2.commit()
        conn2.close()
        
        return render_template('inspection_success.html', vehicle_name=fob['vehicle_name'], inspection_type='Quarterly Inventory')

    conn.close()
    return render_template('quarterly_form.html', fob=fob, inspector=username)

@app.route('/admin/api/assignments')
def api_assignments():
    """Get all inspection assignments as JSON"""
    if not session.get('admin'):
        return {'error': 'Unauthorized'}, 401
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    rows = conn.execute('''
        SELECT ia.*, kf.vehicle_name
        FROM inspection_assignments ia
        JOIN key_fobs kf ON ia.fob_id = kf.id
        ORDER BY ia.completed_at IS NOT NULL, ia.due_date ASC
    ''').fetchall()
    conn.close()
    
    result = []
    for row in rows:
        r = dict(row)
        if r['assigned_at']:
            try:
                dt = datetime.fromisoformat(r['assigned_at'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                r['assigned_at'] = dt.strftime('%b %d, %Y')
            except:
                pass
        if r['completed_at']:
            try:
                dt = datetime.fromisoformat(r['completed_at'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                r['completed_at'] = dt.strftime('%b %d, %Y')
            except:
                pass
        result.append(r)
    
    return result

@app.route('/admin/assignment/delete/<int:assignment_id>')
def delete_inspection_assignment(assignment_id):
    """Delete an inspection assignment"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM inspection_assignments WHERE id = ?', (assignment_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard') + '#inspections')

@app.route('/admin/inspection/assign/<int:fob_id>', methods=['GET', 'POST'])
def assign_inspection(fob_id):
    """Assign an inspection to a supervisor"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    from email_utils import send_inspection_assignment
    
    assigned_by = session.get('username', 'Admin')
    chicago_tz = pytz.timezone('America/Chicago')
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if not fob:
        conn.close()
        return "Vehicle not found", 404
    
    if request.method == 'POST':
        inspection_type = request.form.get('inspection_type')
        assigned_to = request.form.get('assigned_to')
        due_date = request.form.get('due_date')
        
        conn.execute('''
            INSERT INTO inspection_assignments 
            (fob_id, inspection_type, assigned_to, assigned_by, assigned_at, due_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (fob_id, inspection_type, assigned_to, assigned_by, 
               datetime.now(chicago_tz).isoformat(), due_date))
        conn.commit()
        conn.close()
        
        # Send email to assigned supervisor
        send_inspection_assignment(
            assigned_to_email=assigned_to,
            assigned_by=assigned_by,
            vehicle_name=fob['vehicle_name'],
            inspection_type=inspection_type,
            due_date=due_date,
            fob_id=fob_id
        )
        
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    # Get list of admin users for dropdown
    admins = conn.execute('SELECT DISTINCT username FROM admin_users WHERE username != ? ORDER BY username', 
                         (assigned_by,)).fetchall()
    
    # Also get OKTA admins from recent sessions if available
    today = datetime.now(chicago_tz).strftime('%Y-%m-%d')
    conn.close()
    
    return render_template('assign_inspection.html', 
                          fob=fob, 
                          assigned_by=assigned_by,
                          admins=admins,
                          today=today)

@app.route('/admin')
def admin_dashboard():
    """Admin dashboard - Okta or password protected"""

    # Check if running behind Okta proxy
    username = get_authenticated_user()
    
    if username:
        # Okta proxy authentication
        if not is_admin_user(username):
            return "Access denied. You are not authorized to access the admin panel.", 403
        
        # Store in session
        session['admin'] = True
        session['username'] = username
    else:
        # Local development - check session from password login
        if not session.get('admin'):
            return redirect('/admin/login')
    
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

    # Get ALL notes for admin (including expired)
    now = datetime.now(chicago_tz)
    all_notes = conn.execute('SELECT * FROM notes').fetchall()

    note_map = {}
    for note in all_notes:
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
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                
                # Include if future start OR has future end_datetime
                end_dt = None
                if res_dict.get('end_datetime'):
                    try:
                        end_dt = datetime.fromisoformat(res_dict['end_datetime'])
                        if end_dt.tzinfo is not None:
                            end_dt = end_dt.astimezone(chicago_tz)
                        res_dict['end_datetime'] = end_dt.strftime('%a, %b %d at %I:%M %p')
                    except:
                        pass
                
                if dt > now or (end_dt and end_dt > now):
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
    for res in past_reservations_raw:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
                
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
    for res in past_reservations_raw:
        res_dict = dict(res)
        if res_dict['reserved_datetime']:
            try:
                dt = datetime.fromisoformat(res_dict['reserved_datetime'])
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

@app.route('/admin/fob/mark_unavailable/<int:fob_id>', methods=['GET', 'POST'])
def admin_mark_unavailable(fob_id):
    """Mark a fob as unavailable from admin panel"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    
    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        chicago_tz = pytz.timezone('America/Chicago')
        
        conn.execute('UPDATE key_fobs SET is_available = 0 WHERE id = ?', (fob_id,))
        
        username = session.get('username', 'Admin')
        if reason:
            full_reason = f"{reason} (marked by {username})"
        else:
            full_reason = f"Marked by {username}"
        # Remove existing note first
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        conn.execute('''
            INSERT INTO notes (fob_id, note_text, created_at)
            VALUES (?, ?, ?)
        ''', (fob_id, f'UNAVAILABLE: {full_reason}', datetime.now(chicago_tz).isoformat()))
        
        conn.commit()
        conn.close()
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard'))
    
    conn.close()
    return render_template('mark_unavailable.html', fob=fob)

@app.route('/admin/fob/mark_available/<int:fob_id>')
def admin_mark_available(fob_id):
    """Mark a fob as available from admin panel"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE key_fobs SET is_available = 1 WHERE id = ?', (fob_id,))
    # Remove unavailable note if exists
    conn.execute("DELETE FROM notes WHERE fob_id = ? AND note_text LIKE 'UNAVAILABLE:%'", (fob_id,))
    conn.commit()
    conn.close()
    
    socketio.emit('status_update', get_current_status())
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/fob/barns_transfer/<int:fob_id>')
def admin_barns_transfer(fob_id):
    """Transfer a vehicle to The Barns from admin panel"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    try:
        # Get or create The Barns user
        barns_user = conn.execute(
            'SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)
        ).fetchone()
        
        if not barns_user:
            conn.execute(
                'INSERT INTO users (card_id, first_name, last_name, is_active) VALUES (?, ?, ?, ?)',
                ('BARNS', 'The', 'Barns', 1)
            )
            conn.commit()
            barns_user = conn.execute(
                'SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)
            ).fetchone()
        
        # Check current checkout status
        current_checkout = conn.execute(
            'SELECT * FROM checkouts WHERE fob_id = ? AND checked_in_at IS NULL', (fob_id,)
        ).fetchone()
        
        if current_checkout:
            conn.execute(
                'UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                (datetime.now(chicago_tz).isoformat(), current_checkout['id'])
            )
        
        # Check out to The Barns
        conn.execute(
            'INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
            (barns_user['id'], fob_id, 'admin', datetime.now(chicago_tz).isoformat())
        )
        
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard') + '#fobs')
        
    except Exception as e:
        conn.close()
        return f"Error: {str(e)}", 500

@app.route('/admin/api/inspections')
def api_inspections():
    """Get inspections as JSON for admin panel"""
    if not session.get('admin'):
        return {'error': 'Unauthorized'}, 401
    
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    
    inspection_type = request.args.get('type', 'cleanliness')
    fob_id = request.args.get('fob_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    table = 'cleanliness_inspections' if inspection_type == 'cleanliness' else 'quarterly_inspections'
    
    query = f'''
        SELECT i.*, kf.vehicle_name
        FROM {table} i
        JOIN key_fobs kf ON i.fob_id = kf.id
        WHERE 1=1
    '''
    params = []
    
    if fob_id:
        query += ' AND i.fob_id = ?'
        params.append(fob_id)
    if start_date:
        query += ' AND date(i.inspected_at) >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND date(i.inspected_at) <= ?'
        params.append(end_date)
    
    query += ' ORDER BY i.inspected_at DESC LIMIT 200'
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    result = []
    for row in rows:
        r = dict(row)
        if r['inspected_at']:
            try:
                dt = datetime.fromisoformat(r['inspected_at'])
                if dt.tzinfo is not None:
                    dt = dt.astimezone(chicago_tz)
                r['inspected_at'] = dt.strftime('%Y-%m-%d %I:%M %p')
            except:
                pass
        
        # For quarterly, count issues (fields that are 0 but should be 1)
        if inspection_type == 'quarterly':
            issue_fields = [
                'registration_current', 'tires_inflated', 'compartment_clean',
                'light_bar_working', 'mdc_working', 'radio_working', 'radar_working',
                'scanner_working', 'axon_camera_working', 'spotlight_working',
                'seatbelts_working', 'headlights_working', 'trunk_clean',
                'spare_tire_inflated', 'ar15_present', 'backpack_present',
                'phone_charger_present', 'evidence_bag_present', 'aed_present',
                'tuning_forks_present', 'ice_scraper_present',
                'firstaid_large_gloves', 'firstaid_cloth_tape', 'firstaid_trauma_shears',
                'firstaid_bandaids', 'firstaid_gauze', 'firstaid_alcohol_prep',
                'firstaid_tourniquets', 'firstaid_chest_seals', 'firstaid_sroll_gauze',
                'bio_hazard_kit', 'printer_paper', 'tape_measure', 'emergency_blanket',
                'fire_extinguisher', 'traffic_vest', 'ripp_restraint', 'red_cone',
                'barrier_tape', 'pet_carrier', 'red_paint', 'code100_mask', 'riot_baton',
                'sani_wipes', 'sharps_container', 'stop_sticks', 'water_rescue_bag',
                'window_punch', 'spit_hood', 'citation_book', 'parking_ticket_book'
            ]
            r['issues_count'] = sum(1 for f in issue_fields if f in r and r[f] == 0)
        
        result.append(r)
    
    return result

@app.route('/admin/inspection/<inspection_type>/<int:inspection_id>')
def view_inspection(inspection_type, inspection_id):
    """View a single inspection in read-only mode"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    
    table = 'cleanliness_inspections' if inspection_type == 'cleanliness' else 'quarterly_inspections'
    row = conn.execute(f'''
        SELECT i.*, kf.vehicle_name
        FROM {table} i
        JOIN key_fobs kf ON i.fob_id = kf.id
        WHERE i.id = ?
    ''', (inspection_id,)).fetchone()
    conn.close()
    
    if not row:
        return "Inspection not found", 404
    
    r = dict(row)
    if r['inspected_at']:
        try:
            dt = datetime.fromisoformat(r['inspected_at'])
            if dt.tzinfo is not None:
                dt = dt.astimezone(chicago_tz)
            r['inspected_at'] = dt.strftime('%A, %B %d, %Y at %I:%M %p')
        except:
            pass
    
    return render_template('inspection_detail.html', inspection=r, inspection_type=inspection_type)

@app.route('/admin/export/inspections')
def export_inspections():
    """Export inspections as CSV"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    
    inspection_type = request.args.get('type', 'cleanliness')
    fob_id = request.args.get('fob_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    table = 'cleanliness_inspections' if inspection_type == 'cleanliness' else 'quarterly_inspections'
    
    query = f'''
        SELECT i.*, kf.vehicle_name
        FROM {table} i
        JOIN key_fobs kf ON i.fob_id = kf.id
        WHERE 1=1
    '''
    params = []
    
    if fob_id:
        query += ' AND i.fob_id = ?'
        params.append(fob_id)
    if start_date:
        query += ' AND date(i.inspected_at) >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND date(i.inspected_at) <= ?'
        params.append(end_date)
    
    query += ' ORDER BY i.inspected_at DESC'
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    if inspection_type == 'cleanliness':
        writer.writerow(['Date', 'Vehicle', 'Inspector', 'Exterior Clean',
                        'Interior Vacuumed', 'Dashboard', 'Center Console',
                        'Windows', 'Interior Doors', 'Backseats', 'Keyboard/MDC', 'Comments'])
        for row in rows:
            r = dict(row)
            if r['inspected_at']:
                try:
                    dt = datetime.fromisoformat(r['inspected_at'])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    r['inspected_at'] = dt.strftime('%Y-%m-%d %I:%M %p')
                except:
                    pass
            writer.writerow([
                r['inspected_at'], r['vehicle_name'], r['inspector'],
                'Yes' if r['exterior_clean'] else 'No',
                'Yes' if r['interior_vacuumed'] else 'No',
                'Yes' if r['wiped_dashboard'] else 'No',
                'Yes' if r['wiped_center_console'] else 'No',
                'Yes' if r['wiped_windows'] else 'No',
                'Yes' if r['wiped_interior_doors'] else 'No',
                'Yes' if r['wiped_backseats'] else 'No',
                'Yes' if r['wiped_keyboard_mdc'] else 'No',
                r['comments'] or ''
            ])
    else:
        writer.writerow(['Date', 'Vehicle', 'Inspector',
                        'Registration Current', 'Tires Inflated', 'Compartment Clean',
                        'Light Bar Working', 'MDC Working', 'Radio Working', 'RADAR Working',
                        'Scanner Working', 'AXON Camera', 'Spotlight', 'Seat Belts',
                        'Headlights', 'Trunk Clean', 'Spare Tire',
                        'AR-15', 'Backpack', 'Phone Charger', 'Evidence Bag', 'AED',
                        'Tuning Forks', 'Ice Scraper',
                        'FA: Large Gloves', 'FA: Cloth Tape', 'FA: Trauma Shears',
                        'FA: Bandaids', 'FA: Gauze', 'FA: Alcohol Prep',
                        'FA: Tourniquets', 'FA: Chest Seals', 'FA: S-Roll Gauze',
                        'Bio Hazard Kit', 'Printer Paper', 'Tape Measure',
                        'Emergency Blanket', 'Fire Extinguisher', 'Traffic Vest',
                        'RIPP Restraint', 'Red Cone', 'Barrier Tape', 'Pet Carrier',
                        'Red Paint', 'Code 100 Mask', 'Riot Baton', 'Sani Wipes',
                        'Sharps Container', 'Stop Sticks', 'Water Rescue Bag',
                        'Window Punch', 'Spit Hood', 'Citation Book', 'Parking Ticket Book',
                        'Comments'])
        for row in rows:
            r = dict(row)
            if r['inspected_at']:
                try:
                    dt = datetime.fromisoformat(r['inspected_at'])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(chicago_tz)
                    r['inspected_at'] = dt.strftime('%Y-%m-%d %I:%M %p')
                except:
                    pass
            yn = lambda f: 'Yes' if r.get(f) else 'No'
            writer.writerow([
                r['inspected_at'], r['vehicle_name'], r['inspector'],
                yn('registration_current'), yn('tires_inflated'), yn('compartment_clean'),
                yn('light_bar_working'), yn('mdc_working'), yn('radio_working'), yn('radar_working'),
                yn('scanner_working'), yn('axon_camera_working'), yn('spotlight_working'),
                yn('seatbelts_working'), yn('headlights_working'), yn('trunk_clean'), yn('spare_tire_inflated'),
                yn('ar15_present'), yn('backpack_present'), yn('phone_charger_present'),
                yn('evidence_bag_present'), yn('aed_present'), yn('tuning_forks_present'), yn('ice_scraper_present'),
                yn('firstaid_large_gloves'), yn('firstaid_cloth_tape'), yn('firstaid_trauma_shears'),
                yn('firstaid_bandaids'), yn('firstaid_gauze'), yn('firstaid_alcohol_prep'),
                yn('firstaid_tourniquets'), yn('firstaid_chest_seals'), yn('firstaid_sroll_gauze'),
                yn('bio_hazard_kit'), yn('printer_paper'), yn('tape_measure'),
                yn('emergency_blanket'), yn('fire_extinguisher'), yn('traffic_vest'),
                yn('ripp_restraint'), yn('red_cone'), yn('barrier_tape'), yn('pet_carrier'),
                yn('red_paint'), yn('code100_mask'), yn('riot_baton'), yn('sani_wipes'),
                yn('sharps_container'), yn('stop_sticks'), yn('water_rescue_bag'),
                yn('window_punch'), yn('spit_hood'), yn('citation_book'), yn('parking_ticket_book'),
                r['comments'] or ''
            ])
    
    output.seek(0)
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={inspection_type}_inspections.csv'}
    )

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
        make = request.form.get('make') or None
        model = request.form.get('model') or None
        year = request.form.get('year') or None
        
        conn.execute('UPDATE key_fobs SET vehicle_name = ?, category = ?, location = ?, make = ?, model = ?, year = ? WHERE id = ?',
                    (vehicle_name, category, location, make, model, year, fob_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    assignments = conn.execute('''
        SELECT va.*, u.first_name, u.last_name
        FROM vehicle_assignments va
        JOIN users u ON va.user_id = u.id
        WHERE va.fob_id = ?
        ORDER BY va.shift
    ''', (fob_id,)).fetchall()
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('edit_fob.html', fob=fob, assignments=assignments, users=users)

@app.route('/admin/fob/assignment/add/<int:fob_id>', methods=['POST'])
def add_assignment(fob_id):
    """Add a vehicle assignment"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    user_id = request.form.get('user_id')
    shift = request.form.get('shift')
    
    if user_id and shift:
        conn = get_db()
        conn.execute(
            'INSERT INTO vehicle_assignments (fob_id, user_id, shift) VALUES (?, ?, ?)',
            (fob_id, user_id, shift)
        )
        conn.commit()
        conn.close()
    
    return redirect(f'/admin/fob/edit/{fob_id}#assignments')

@app.route('/admin/fob/assignment/delete/<int:assignment_id>/<int:fob_id>')
def delete_assignment(assignment_id, fob_id):
    """Delete a vehicle assignment"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM vehicle_assignments WHERE id = ?', (assignment_id,))
    conn.commit()
    conn.close()
    
    return redirect(f'/admin/fob/edit/{fob_id}#assignments')

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
        
        # Check if new fob_id already exists
        existing = conn.execute('''
            SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE AND id != ?
        ''', (new_fob_id, fob_id)).fetchone()
        
        if existing:
            conn.close()
            # Flash an error message and return to the form
            from flask import flash
            flash(f"Error: This fob is already registered to {existing['vehicle_name']}", 'error')
            return render_template('replace_fob.html', fob=fob, error=f"This fob is already registered to {existing['vehicle_name']}")
        
        # Update the fob_id
        try:
            conn.execute('UPDATE key_fobs SET fob_id = ? WHERE id = ?',
                        (new_fob_id, fob_id))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_dashboard') + '#fobs')
        except Exception as e:
            conn.close()
            from flask import flash
            flash(f"Error replacing fob: {str(e)}", 'error')
            return render_template('replace_fob.html', fob=fob, error=f"Database error: {str(e)}")
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
        end_datetime = request.form.get('end_datetime') or None
        display_hours_before = int(request.form.get('display_hours_before', 24))
        reason = request.form.get('reason')
        created_by = session.get('username', 'admin')
        
        # Convert datetime to Central time
        chicago_tz = pytz.timezone('America/Chicago')
        dt = datetime.strptime(reserved_datetime, '%Y-%m-%dT%H:%M')
        dt = chicago_tz.localize(dt)
        
        # Convert end_datetime if provided
        end_dt_iso = None
        if end_datetime:
            try:
                end_dt = datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M')
                end_dt = chicago_tz.localize(end_dt)
                end_dt_iso = end_dt.isoformat()
            except:
                pass
        
        conn.execute('''
            INSERT INTO reservations (fob_id, user_id, reserved_for_name, reserved_datetime, display_hours_before, reason, created_by, end_datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fob_id, user_id, reserved_for_name, dt.isoformat(), display_hours_before, reason, created_by, end_dt_iso))
        conn.commit()
        conn.close()
        
        # Broadcast update
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard') + '#reservations')
    
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('reserve_fob.html', fob=fob, users=users)

@app.route('/admin/reservation/new', methods=['GET', 'POST'])
def new_reservation():
    """Create a new reservation from the reservations tab"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    if request.method == 'POST':
        fob_id = request.form.get('fob_id')
        user_id = request.form.get('user_id') or None
        reserved_for_name = request.form.get('reserved_for_name')
        reserved_datetime = request.form.get('reserved_datetime')
        end_datetime = request.form.get('end_datetime') or None
        display_hours_before = int(request.form.get('display_hours_before', 24))
        reason = request.form.get('reason')
        created_by = session.get('username', 'admin')
        
        dt = datetime.strptime(reserved_datetime, '%Y-%m-%dT%H:%M')
        dt = chicago_tz.localize(dt)
        
        end_dt_iso = None
        if end_datetime:
            try:
                end_dt = datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M')
                end_dt = chicago_tz.localize(end_dt)
                end_dt_iso = end_dt.isoformat()
            except:
                pass
        
        conn.execute('''
            INSERT INTO reservations (fob_id, user_id, reserved_for_name, reserved_datetime,
                end_datetime, display_hours_before, reason, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fob_id, user_id, reserved_for_name, dt.isoformat(),
               end_dt_iso, display_hours_before, reason, created_by))
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard') + '#reservations')
    
    fobs = conn.execute('''
        SELECT * FROM key_fobs WHERE is_active = 1 ORDER BY category, vehicle_name
    ''').fetchall()
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('new_reservation.html', fobs=fobs, users=users)

@app.route('/admin/reservation/bulk', methods=['GET', 'POST'])
def bulk_reserve():
    """Create reservations for multiple items at once"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    if request.method == 'POST':
        fob_ids = request.form.getlist('fob_ids')
        user_id = request.form.get('user_id') or None
        reserved_for_name = request.form.get('reserved_for_name')
        reserved_datetime = request.form.get('reserved_datetime')
        end_datetime = request.form.get('end_datetime') or None
        display_hours_before = int(request.form.get('display_hours_before', 24))
        reason = request.form.get('reason')
        created_by = session.get('username', 'admin')
        
        if not fob_ids:
            conn.close()
            return redirect(url_for('bulk_reserve'))
        
        dt = datetime.strptime(reserved_datetime, '%Y-%m-%dT%H:%M')
        dt = chicago_tz.localize(dt)
        
        end_dt_iso = None
        if end_datetime:
            try:
                end_dt = datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M')
                end_dt = chicago_tz.localize(end_dt)
                end_dt_iso = end_dt.isoformat()
            except:
                pass
        
        for fob_id in fob_ids:
            conn.execute('''
                INSERT INTO reservations (fob_id, user_id, reserved_for_name, reserved_datetime, 
                    end_datetime, display_hours_before, reason, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (int(fob_id), user_id, reserved_for_name, dt.isoformat(),
                   end_dt_iso, display_hours_before, reason, created_by))
        
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard') + '#reservations')
    
    fobs = conn.execute('''
        SELECT kf.*, c.id as checkout_id
        FROM key_fobs kf
        LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
        WHERE kf.is_active = 1
        ORDER BY kf.category, kf.vehicle_name
    ''').fetchall()
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('bulk_reserve.html', fobs=fobs, users=users)

@app.route('/admin/reservation/edit/<int:reservation_id>', methods=['GET', 'POST'])
def edit_reservation(reservation_id):
    """Edit an existing reservation"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    chicago_tz = pytz.timezone('America/Chicago')
    conn = get_db()
    
    res_raw = conn.execute('''
        SELECT r.*, kf.vehicle_name
        FROM reservations r
        JOIN key_fobs kf ON r.fob_id = kf.id
        WHERE r.id = ?
    ''', (reservation_id,)).fetchone()
    
    if not res_raw:
        conn.close()
        return "Reservation not found", 404
    
    if request.method == 'POST':
        user_id = request.form.get('user_id') or None
        reserved_for_name = request.form.get('reserved_for_name')
        reserved_datetime = request.form.get('reserved_datetime')
        end_datetime = request.form.get('end_datetime') or None
        display_hours_before = int(request.form.get('display_hours_before', 24))
        reason = request.form.get('reason')
        
        dt = datetime.strptime(reserved_datetime, '%Y-%m-%dT%H:%M')
        dt = chicago_tz.localize(dt)
        
        end_dt_iso = None
        if end_datetime:
            try:
                end_dt = datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M')
                end_dt = chicago_tz.localize(end_dt)
                end_dt_iso = end_dt.isoformat()
            except:
                pass
        
        conn.execute('''
            UPDATE reservations 
            SET user_id=?, reserved_for_name=?, reserved_datetime=?, end_datetime=?,
                display_hours_before=?, reason=?
            WHERE id=?
        ''', (user_id, reserved_for_name, dt.isoformat(), end_dt_iso, 
              display_hours_before, reason, reservation_id))
        conn.commit()
        conn.close()
        
        socketio.emit('status_update', get_current_status())
        return redirect(url_for('admin_dashboard') + '#reservations')
    
    # Format datetimes for input fields
    res = dict(res_raw)
    try:
        dt = datetime.fromisoformat(res['reserved_datetime'])
        if dt.tzinfo is not None:
            dt = dt.astimezone(chicago_tz)
        res['reserved_datetime_input'] = dt.strftime('%Y-%m-%dT%H:%M')
    except:
        res['reserved_datetime_input'] = res['reserved_datetime']
    
    if res.get('end_datetime'):
        try:
            end_dt = datetime.fromisoformat(res['end_datetime'])
            if end_dt.tzinfo is not None:
                end_dt = end_dt.astimezone(chicago_tz)
            res['end_datetime_input'] = end_dt.strftime('%Y-%m-%dT%H:%M')
        except:
            res['end_datetime_input'] = res['end_datetime']
    else:
        res['end_datetime_input'] = ''
    
    users = conn.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY last_name, first_name').fetchall()
    conn.close()
    return render_template('edit_reservation.html', res=res, users=users)

@app.route('/admin/reservation/delete/<int:reservation_id>')
def delete_reservation(reservation_id):
    """Delete a reservation"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
    conn.commit()
    conn.close()
    
    # Broadcast update
    socketio.emit('status_update', get_current_status())
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/fob/barcode/<int:fob_id>')
def generate_barcode(fob_id):
    """Generate QR code for a fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
   
    import qrcode
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
   
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    conn.close()
   
    if not fob:
        return "Fob not found", 404
   
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        box_size=3,
        border=1,
    )
    qr.add_data(fob['fob_id'])
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Add text label below QR code
    qr_width, qr_height = qr_img.size
    
    # Convert QR image to RGB if needed
    if qr_img.mode != 'RGB':
        qr_img = qr_img.convert('RGB')
    
    # Set up font and calculate text size
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except:
        font = ImageFont.load_default()
    
    text = fob['vehicle_name']
    # Create temporary draw to measure text
    temp_img = Image.new('RGB', (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    
    # Make final image wide enough for QR code OR text (whichever is wider)
    text_height = 25
    final_width = max(qr_width, text_width + 10)  # +10 for padding
    final_img = Image.new('RGB', (final_width, qr_height + text_height), 'white')
    
    # Center QR code horizontally if text is wider
    qr_x = (final_width - qr_width) // 2
    final_img.paste(qr_img, (qr_x, 0))
    
    # Draw text centered
    draw = ImageDraw.Draw(final_img)
    text_x = (final_width - text_width) // 2
    text_y = qr_height + 5
    draw.text((text_x, text_y), text, fill='black', font=font)
   
    # Save to BytesIO
    buffer = BytesIO()
    final_img.save(buffer, format='PNG')
    buffer.seek(0)
   
    # Return as downloadable PNG
    return send_file(
        buffer,
        mimetype='image/png',
        as_attachment=True,
        download_name=f'{fob["vehicle_name"]}_qrcode.png'
    )

@app.route('/admin/fob/inspection_qr/<int:fob_id>')
def generate_inspection_qr(fob_id):
    """Generate QR code that links to the inspection form"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
   
    import qrcode
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
   
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    conn.close()
   
    if not fob:
        return "Fob not found", 404
   
    # Generate QR code with inspection URL
    inspection_url = f"https://pd-checkout.cityoffargo.com/inspect/{fob_id}"
    
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(inspection_url)
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_width, qr_height = qr_img.size
    
    if qr_img.mode != 'RGB':
        qr_img = qr_img.convert('RGB')
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except:
        font = ImageFont.load_default()
    
    text = f"{fob['vehicle_name']} - Inspection"
    temp_img = Image.new('RGB', (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    
    text_height = 25
    final_width = max(qr_width, text_width + 10)
    final_img = Image.new('RGB', (final_width, qr_height + text_height), 'white')
    
    qr_x = (final_width - qr_width) // 2
    final_img.paste(qr_img, (qr_x, 0))
    
    draw = ImageDraw.Draw(final_img)
    text_x = (final_width - text_width) // 2
    text_y = qr_height + 5
    draw.text((text_x, text_y), text, fill='black', font=font)
   
    buffer = BytesIO()
    final_img.save(buffer, format='PNG')
    buffer.seek(0)
   
    return send_file(
        buffer,
        mimetype='image/png',
        as_attachment=True,
        download_name=f'{fob["vehicle_name"]}_inspection_qr.png'
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
        expires_at = request.form.get('expires_at')  # Get expiration from form
        created_by = session.get('username', 'admin')
        
        chicago_tz = pytz.timezone('America/Chicago')
        
        # Convert expires_at to Chicago timezone if provided
        expires_at_iso = None
        if expires_at:
            try:
                # Parse the datetime-local input (format: YYYY-MM-DDTHH:MM)
                dt = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M')
                # Localize to Chicago timezone
                dt_chicago = chicago_tz.localize(dt)
                expires_at_iso = dt_chicago.isoformat()
            except:
                pass  # If parsing fails, leave as None
        
        # Delete existing note (one at a time)
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        
        # Insert new note with expiration
        conn.execute('''
            INSERT INTO notes (fob_id, note_text, created_at, created_by, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (fob_id, note_text, datetime.now(chicago_tz).isoformat(), created_by, expires_at_iso))
        
        conn.commit()
        socketio.emit('status_update', get_current_status())
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
    socketio.emit('status_update', get_current_status())
    conn.close()
    
    return redirect(url_for('admin_dashboard') + '#fobs')

@app.route('/admin/fob/note/edit/<int:fob_id>', methods=['GET', 'POST'])
def edit_note(fob_id):
    """Edit note and expiration for fob"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    fob = conn.execute('SELECT * FROM key_fobs WHERE id = ?', (fob_id,)).fetchone()
    note = conn.execute('SELECT * FROM notes WHERE fob_id = ?', (fob_id,)).fetchone()
    
    if request.method == 'POST':
        note_text = request.form.get('note_text')
        expires_at = request.form.get('expires_at')  # Optional
        created_by = session.get('username', 'admin')
        
        chicago_tz = pytz.timezone('America/Chicago')
        
        # Parse expiration if provided
        expiration_iso = None
        if expires_at:
            try:
                # Parse datetime string (format: YYYY-MM-DDTHH:MM from HTML datetime-local input)
                dt = datetime.fromisoformat(expires_at)
                dt_aware = chicago_tz.localize(dt)
                expiration_iso = dt_aware.isoformat()
            except:
                pass
        
        # Delete existing note
        conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob_id,))
        
        # Insert updated note
        conn.execute('''
            INSERT INTO notes (fob_id, note_text, created_at, created_by, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (fob_id, note_text, datetime.now(chicago_tz).isoformat(), created_by, expiration_iso))
        
        conn.commit()
        socketio.emit('status_update', get_current_status())
        conn.close()
        return redirect(url_for('admin_dashboard') + '#fobs')
    
    conn.close()
    return render_template('edit_note.html', fob=fob, note=note)

@app.route('/admin/fob/note/expire/<int:fob_id>')
def expire_note(fob_id):
    """Expire note immediately by setting expires_at to now"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    chicago_tz = pytz.timezone('America/Chicago')
    now = datetime.now(chicago_tz).isoformat()
    
    # Update the note's expiration to now
    conn.execute('UPDATE notes SET expires_at = ? WHERE fob_id = ?', (now, fob_id))
    conn.commit()
    socketio.emit('status_update', get_current_status())
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

@app.route('/admin/admins')
def manage_admin_users():
    """Manage admin users"""
    if not session.get('admin'):
        return redirect('/admin/login')
    
    conn = get_db()
    admins_raw = conn.execute('SELECT * FROM admin_users ORDER BY username').fetchall()
    conn.close()
    
    # Convert timestamps to Chicago time
    chicago_tz = pytz.timezone('America/Chicago')
    admins = []
    for admin in admins_raw:
        admin_dict = dict(admin)
        if admin_dict.get('created_at'):
            try:
                # Parse the UTC timestamp
                dt = datetime.fromisoformat(admin_dict['created_at'])
                # If no timezone, assume UTC
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                # Convert to Chicago time
                dt_chicago = dt.astimezone(chicago_tz)
                admin_dict['created_at'] = dt_chicago.strftime('%b %d, %Y %H:%M')
            except:
                pass  # Keep original if parsing fails
        admins.append(admin_dict)

    return render_template('manage_admins.html', admins=admins)

@app.route('/admin/admins/add', methods=['POST'])
def add_admin_user():
    """Add new admin user"""
    if not session.get('admin'):
        return redirect('/admin/login')
    
    username = request.form.get('username')
    
    if username:
        conn = get_db()
        try:
            conn.execute('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)', (username, ''))
            conn.commit()
        except:
            pass  # Already exists
        conn.close()
    
    return redirect('/admin/admins')

@app.route('/admin/admins/delete/<int:admin_id>', methods=['POST'])
def delete_admin_user(admin_id):
    """Delete admin user"""
    if not session.get('admin'):
        return redirect('/admin/login')
    
    conn = get_db()
    conn.execute('DELETE FROM admin_users WHERE id = ?', (admin_id,))
    conn.commit()
    conn.close()
    
    return redirect('/admin/admins')


# Run migrations on startup
run_migrations()

# Start reminder scheduler
import threading
def check_reminders():
    """Check for inspections due in 7 days and send reminders"""
    import time
    from email_utils import send_inspection_reminder
    
    while True:
        try:
            chicago_tz = pytz.timezone('America/Chicago')
            now = datetime.now(chicago_tz)
            reminder_date = (now + timedelta(days=7)).strftime('%Y-%m-%d')
            
            conn = get_db()
            # Find assignments due in 7 days that haven't been completed or reminded
            assignments = conn.execute('''
                SELECT ia.*, kf.vehicle_name
                FROM inspection_assignments ia
                JOIN key_fobs kf ON ia.fob_id = kf.id
                WHERE date(ia.due_date) = ?
                AND ia.completed_at IS NULL
                AND ia.reminder_sent = 0
            ''', (reminder_date,)).fetchall()
            
            for assignment in assignments:
                send_inspection_reminder(
                    assigned_to_email=assignment['assigned_to'],
                    vehicle_name=assignment['vehicle_name'],
                    inspection_type=assignment['inspection_type'],
                    due_date=assignment['due_date'],
                    fob_id=assignment['fob_id']
                )
                conn.execute('UPDATE inspection_assignments SET reminder_sent = 1 WHERE id = ?', 
                           (assignment['id'],))
                conn.commit()
            
            conn.close()
        except Exception as e:
            print(f"Reminder check error: {e}")
        
        # Check once per day (86400 seconds)
        time.sleep(86400)

reminder_thread = threading.Thread(target=check_reminders, daemon=True)
reminder_thread.start()

if __name__ == '__main__':
# Get debug settings from environment (default to False for production safety)
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    ALLOW_UNSAFE_WERKZEUG = os.environ.get('ALLOW_UNSAFE_WERKZEUG', 'False').lower() == 'true'
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=DEBUG, allow_unsafe_werkzeug=ALLOW_UNSAFE_WERKZEUG)
