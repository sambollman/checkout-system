# Vehicle & Equipment Checkout System

RFID-based self-service checkout system for tracking vehicles and equipment. Employees scan their keycard and equipment fob - system tracks who has what, when, and where.

## Current Status
Working prototype running on Raspberry Pi 5. Ready for production deployment on IT infrastructure.

## Features

- **Real-time Vehicle Tracking**: See which vehicles are checked out and who has them
- **RFID-Based**: Fast checkout using employee keycards and vehicle fobs
- **Bulk Checkout**: Scan one card, then scan multiple vehicles for quick multi-item checkout
- **Special Functions**:
  - Barns Transfer: Send vehicles to The Barns with one button
  - Card Replacement: Replace lost/damaged employee keycards
  - Notes System: Add warnings or reminders with optional expiration
- **Multi-Location Support**: Run multiple kiosk stations (main garage, downtown, etc.)
- **Live Updates**: Dashboard updates in real-time via WebSockets
- **Admin Panel**: Web-based management for users, equipment, and checkout history
- **Category Management**: Organize by Squad Cars, CID Vehicles, Equipment, Key Rings, etc.
- **Smart Sorting**: Checked-out items appear first in Equipment and Key Rings tabs
- **Reservation System**: Reserve vehicles in advance with display windows
- **OKTA Integration**: Enterprise authentication ready for production deployment

## Technology Stack
- **Backend:** Python 3.11, Flask, Flask-SocketIO
- **Database:** SQLite (production: PostgreSQL recommended)
- **Frontend:** HTML, CSS, JavaScript (vanilla - no frameworks)
- **Kiosk:** Python Tkinter GUI
- **Hardware:** HID RFID reader (USB keyboard wedge)

## Quick Start (Development)

### Prerequisites
- Python 3.11+
- Linux/macOS/Windows

### Installation
```bash
# Clone repository
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database
python database.py

# Run Flask server with development settings
export ALLOW_UNSAFE_WERKZEUG=True  # Windows: set ALLOW_UNSAFE_WERKZEUG=True
export ADMIN_PASSWORD=admin123
python app.py

# In another terminal, run kiosk GUI
export SERVER_URL=http://localhost:5000
export KIOSK_USER=kiosk
export KIOSK_PASS=change-this-in-production
python kiosk_gui.py
```

Access dashboard at: http://localhost:5000  
Admin panel at: http://localhost:5000/admin (password: `admin123` in dev mode)

## Kiosk Workflows

### Standard Checkout
1. Scan employee keycard
2. Scan equipment fob
3. Done! (3 seconds total)

### Bulk Checkout
For employees checking out multiple items at shift start:
1. Click **"🛒 Bulk Checkout"** button
2. Scan keycard once
3. Scan all items (vehicle, bags, equipment)
4. Click **"✅ Done"**
5. All items checked out simultaneously

**Example:** Officer checking out Squad 48, 3 evidence bags, and a backpack = 1 card scan + 5 fob scans instead of 10 total scans.

### Barns Transfer
Transfer vehicle to maintenance without physical fob:
1. Click **"🔧 Barns Transfer"**
2. Either scan fob OR select vehicle from list
3. Auto-checks out to "The Barns" user
4. Dashboard shows vehicle at maintenance

### Notes with Expiration
Add temporary equipment status notes:
1. Click **"📝 Add Note"**
2. Scan or select equipment
3. Enter note text (e.g., "AED needs servicing")
4. Optional: Check **"⏰ Set Expiration"** and pick date/time
5. Note displays on dashboard until expired
6. Expired notes auto-delete from database

**Admin Controls:**
- **Edit Note:** Change text or expiration date
- **Expire Now:** Immediately expire a note
- **Delete Note:** Permanently remove

## Admin Panel Features

### Tabbed Interface
- **👥 Users:** Manage employees, replace cards, activate/deactivate
- **🔑 Key Fobs:** Manage equipment, categories, notes, reservations, barcodes
- **📋 Recent History:** Filterable checkout history with export (by date, user, vehicle, limit)
- **📅 Active Reservations:** Current reservations with delete option
- **📅 Past Reservations:** Historical reservations with filtering

### Notes Column
Key Fobs tab now shows:
- Note text (truncated to 50 chars)
- Expiration date/time (if set)
- Visual indicator (yellow box with clock icon for expiring notes)

## Server Deployment

### Production (Docker with OKTA)
```bash
# 1. Clone repository
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system

# 2. Build Docker image
docker build -t checkout-system .

# 3. Run container
docker run -d \
  --name checkout-app \
  --restart unless-stopped \
  -p 127.0.0.1:5000:5000 \              # Bind to localhost only
  -v /data:/data \                       # Persistent database storage
  -e DB_PATH=/data/key_checkout.db \
  -e OKTA_HEADER=X-Auth-Proxy-Username \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e KIOSK_USER=kiosk \
  -e KIOSK_PASS=$(openssl rand -base64 32) \
  -e DEBUG=False \
  -e CORS_ORIGINS=https://checkout.fargond.gov \
  checkout-system

# 4. Initialize first admin user
sqlite3 /data/key_checkout.db \
  "INSERT INTO admin_users (username, password_hash) VALUES ('your.username', '');"

# 5. Configure reverse proxy (nginx example)
# See IT_DEPLOYMENT_CHECKLIST.md for full configuration
```

### Development (Local Testing)
```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Run server
export ALLOW_UNSAFE_WERKZEUG=True
export ADMIN_PASSWORD=testpass123
python app.py

# 3. Run kiosk (separate terminal)
export SERVER_URL=http://localhost:5000
export KIOSK_USER=kiosk
export KIOSK_PASS=change-this-in-production
python kiosk_gui.py
```

### Kiosk Deployment

See `KIOSK_INSTALLATION.md` for detailed installation instructions.

**Quick setup:**
1. Install Python 3.11 on Windows laptop
2. Clone repository
3. Edit `Start_Kiosk.bat` with production SERVER_URL and credentials
4. Add to Windows Startup folder for auto-launch
5. Connect RFID reader via USB



**Authorized Admins:**

Admins are managed via `/admin/manage_admins` - no code changes needed!

1. **Initial Setup:** Add first admin to database:
```bash
sqlite3 /path/to/key_checkout.db "INSERT INTO admin_users (username, password_hash) VALUES ('your.username', '');"
```

2. **Adding More Admins:**
   - Log in to admin panel
   - Go to `/admin/manage_admins`
   - Add usernames (they'll authenticate via Okta)

3. **Removing Admins:**
   - Go to `/admin/manage_admins`
   - Click "Delete" next to their name

**Note:** In production with Okta, the `password_hash` column is empty. Okta handles authentication, the app only checks if the username exists in the `admin_users` table.

⚠️ **Security:** Only enable `OKTA_HEADER` when application is behind Okta proxy. If accessible directly, anyone can forge the header.

### OKTA Deployment Checklist

Before production deployment with OKTA authentication, confirm these details with IT:

**1. Header Configuration:**
- What HTTP header name will contain the authenticated username?
  - Common examples: `X-Forwarded-User`, `X-Auth-User`, `Remote-User`
  - This becomes your `OKTA_HEADER` environment variable

**2. Username Format:**
- What format will usernames be in?
  - Examples: `sam.bollman`, `sbollman`, `sbollman@fargond.gov`
  - Must match exactly when adding to `admin_users` table

**3. Network Security:**
- Will port 5000 be firewalled (only accessible from proxy)?
  - **Recommended:** Bind to localhost only: `-p 127.0.0.1:5000:5000`
  - Prevents direct access that bypasses OKTA authentication
  
**4. Public URL:**
- What will the public-facing URL be?
  - Example: `https://checkout.fargond.gov`
  - Used for kiosk `SERVER_URL` configuration

**5. SSL/TLS:**
- Is HTTPS termination handled by the reverse proxy?
  - Yes (recommended) - proxy handles SSL, communicates with Docker via HTTP
  - Flask app doesn't need SSL certificate configuration

### OKTA Security Best Practices

⚠️ **CRITICAL SECURITY REQUIREMENT:**

The `OKTA_HEADER` feature assumes the application is **only accessible through the OKTA proxy**. If the Docker port is directly accessible, authentication can be bypassed:
```bash
# Example of header forgery if port 5000 is exposed:
curl -H "X-Forwarded-User: admin" http://yourserver:5000/admin
# ^ This would grant admin access without OKTA login!
```

**Required Mitigations:**

1. **Bind to localhost only:**
```bash
   -p 127.0.0.1:5000:5000  # Only accessible from the server itself
```

2. **Firewall external access:**
   - Block port 5000 from external networks
   - Only allow proxy server to connect

3. **Verify setup:**
```bash
   # From external network - should fail:
   curl http://your-server:5000
   
   # From proxy - should work:
   curl http://localhost:5000
```

**Reverse Proxy Configuration Example (nginx):**
```nginx
location / {
    proxy_pass http://localhost:5000;
    proxy_set_header X-Forwarded-User $remote_user;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## Environment Variables

### Server (Docker Container)

**Required:**
```bash
DB_PATH=/data/key_checkout.db              # Database file location
KIOSK_USER=kiosk                           # Kiosk authentication username
KIOSK_PASS=               # Kiosk authentication password
```

**Production (OKTA Mode):**
```bash
OKTA_HEADER=X-Auth-Proxy-Username          # Header containing authenticated username
SECRET_KEY=          # Flask session secret (generate random)
DEBUG=False                                 # Disable debug mode
ALLOW_UNSAFE_WERKZEUG=False                # Use proper WSGI server (gunicorn/uwsgi)
CORS_ORIGINS=https://checkout.domain.com   # Allowed CORS origins
```

**Development/Emergency:**
```bash
ADMIN_PASSWORD=                  # Enable password-based admin login
                                           # Leave empty to disable (OKTA only)
DEBUG=True                                  # Enable debug mode
ALLOW_UNSAFE_WERKZEUG=True                 # Allow Werkzeug dev server
```

### Kiosk (Windows/Linux)

**Required:**
```bash
SERVER_URL=https://checkout.domain.com     # Server URL (HTTPS in production)
KIOSK_USER=kiosk                           # Must match server KIOSK_USER
KIOSK_PASS=               # Must match server KIOSK_PASS

**Set in launcher scripts** (`Start_Kiosk.bat` or `start_kiosk.sh`)

### Kiosk Installation

**Windows (Kiosk Laptop):**
1. Install Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. Clone repository or copy files to laptop
3. Edit `Start_Kiosk.bat`:
   - Set `SERVER_URL` to production server
   - Set `KIOSK_USER` and `KIOSK_PASS` to match server config
4. Double-click `Start_Kiosk.bat` to run
5. Optional: Add to Startup folder for auto-launch

**Linux/Raspberry Pi:**
1. Clone repository
2. Edit `start_kiosk.sh`:
   - Set `SERVER_URL`, `KIOSK_USER`, `KIOSK_PASS`
3. Make executable: `chmod +x start_kiosk.sh`
4. Run: `./start_kiosk.sh`
5. Optional: Create desktop launcher (see `Launch_Kiosk.desktop`)

## Architecture

### Production Architecture (API-Based)
```
┌─────────────────────────────────────────────────────────────┐
│                        IT Infrastructure                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  OKTA Proxy (nginx/Apache)                             │ │
│  │  - HTTPS termination                                   │ │
│  │  - OKTA authentication                                 │ │
│  │  - Sets X-Auth-Proxy-Username header                   │ │
│  └─────────────────┬──────────────────────────────────────┘ │
│                    │                                         │
│  ┌─────────────────▼──────────────────────────────────────┐ │
│  │  Docker Container (Server)                             │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Flask App (app.py)                              │  │ │
│  │  │  - REST API endpoints                            │  │ │
│  │  │  - Admin panel                                   │  │ │
│  │  │  - WebSocket real-time updates                   │  │ │
│  │  │  - Single source of truth                        │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  SQLite Database (Production: PostgreSQL)        │  │ │
│  │  │  - Users, equipment, checkouts                   │  │ │
│  │  │  - Notes, reservations, admins                   │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

           │                                    │
           │ HTTPS API Calls                   │ HTTPS API Calls
           │ (HTTP Basic Auth)                 │ (HTTP Basic Auth)
           ▼                                    ▼
    
┌──────────────────────┐              ┌──────────────────────┐
│  Main Kiosk Station  │              │  Downtown Station    │
│  ┌────────────────┐  │              │  ┌────────────────┐  │
│  │ kiosk_gui.py   │  │              │  │ kiosk_gui.py   │  │
│  │ (Pure Client)  │  │              │  │ (Pure Client)  │  │
│  │ - NO database  │  │              │  │ - NO database  │  │
│  │ - API calls    │  │              │  │ - API calls    │  │
│  │ - RFID reader  │  │              │  │ - RFID reader  │  │
│  └────────────────┘  │              │  └────────────────┘  │
└──────────────────────┘              └──────────────────────┘
```

**Key Architecture Principles:**
- **Server owns the database**: Single source of truth
- **Kiosk is stateless**: 100% API-based, no local data persistence
- **API-first design**: All operations go through REST endpoints
- **Real-time updates**: WebSocket pushes changes to dashboard
- **Multi-kiosk ready**: Each kiosk has unique ID for tracking

## Multi-Kiosk Deployment

The system supports multiple kiosk locations with automatic location tracking.

### Setting Up Additional Kiosks

**1. Each kiosk needs a unique ID:**
- Main station: `station` (default)
- Downtown location: `downtown`
- Any other site: choose a descriptive name

**2. Create a launcher script for each location:**

**Windows Example** (`Start_Downtown_Kiosk.bat`):
```batch
@echo off
echo Starting Downtown Kiosk...

REM Set server connection details
set SERVER_URL=http://your-server-ip:5000
set KIOSK_USER=kiosk
set KIOSK_PASS=your-password

REM Navigate to script directory
cd /d %~dp0

REM Activate virtual environment
call venv\Scripts\activate

REM Run kiosk with location ID
python kiosk_gui.py --kiosk-id downtown

pause
```

**Linux Example** (`start_downtown_kiosk.sh`):
```bash
#!/bin/bash
export SERVER_URL=http://your-server-ip:5000
export KIOSK_USER=kiosk
export KIOSK_PASS=your-password

cd "$(dirname "$0")"
source venv/bin/activate
python kiosk_gui.py --kiosk-id downtown
```

**3. Auto-launch on Windows startup:**

**Option A: Startup Folder** (Easiest)
1. Press `Windows Key + R`
2. Type `shell:startup` and press Enter
3. Right-click → New → Shortcut
4. Browse to your `.bat` file
5. Click Next → Finish

**Option B: Task Scheduler** (More Control)
1. Open Task Scheduler
2. Create Basic Task
3. Name: "Downtown Kiosk"
4. Trigger: "When the computer starts"
5. Action: Start program → browse to `.bat` file
6. Optional: Check "Run with highest privileges"

**Option C: Full Kiosk Mode** (Unattended)
1. Set Windows auto-login: `Win+R` → `netplwiz`
2. Uncheck "Users must enter a username and password"
3. Add shortcut to Startup folder
4. PC boots → auto-login → kiosk launches

**Pro Tip:** Set Windows "Active Hours" in Update settings to prevent mid-shift restarts.

### Location Tracking

All checkouts/checkins automatically record which kiosk was used:
- Admin panel shows kiosk location in checkout history
- Useful for tracking where equipment was last seen
- Helps identify usage patterns by location

## Hardware Requirements

### Server
- VM or container
- 2-4 CPU cores
- 4-8 GB RAM
- 50 GB storage
- PostgreSQL database (production)

### Kiosk (per location)
- Thin client PC, Raspberry Pi 5, or Windows laptop
- HID RFID Prox reader ($80-120) - RFIDeas pcProx Plus recommended
- Monitor (any size)
- Optional: Barcode scanner

### Equipment Tags
- HID RFID key fobs or EM4100 fobs ($0.50-$2 each)
- Printed barcode labels (for non-fob equipment)

## File Structure
```
checkout-system/
├── app.py                      # Flask web server & API
├── kiosk_gui.py               # Kiosk interface (pure API client)
├── database.py                # Database schema and connection
├── templates/
│   ├── index.html             # Main dashboard (category tabs)
│   ├── admin.html             # Admin panel (tabbed interface)
│   ├── admin_login.html       # Admin login (dev mode only)
│   ├── reserve_fob.html       # Reservation form
│   ├── add_note.html          # Add note form
│   ├── edit_note.html         # Edit note with expiration
│   └── manage_admins.html     # Admin user management
├── Start_Kiosk.bat            # Windows main station launcher
├── Start_Trikke_Kiosk.bat     # Windows downtown launcher
├── start_kiosk.sh             # Linux launcher
├── .dockerignore              # Docker build exclusions
├── Dockerfile                 # Container build
├── key_checkout.db            # SQLite database (created on first run)
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── DEPLOYMENT.md              # Production deployment guide
├── IT_DEPLOYMENT_CHECKLIST.md # IT deployment checklist
└── KIOSK_INSTALLATION.md      # Kiosk setup guide
```

## API Endpoints (Complete List)

### Public
- `GET /` - Main dashboard
- `GET /api/status` - Get current system status (JSON, unauthenticated for polling)

### Admin (OKTA header or password auth)
- `GET /admin` - Admin dashboard (tabbed interface)
- `GET /admin/login` - Password login (only if ADMIN_PASSWORD set and not in OKTA mode)
- `GET /admin/logout` - Logout
- `GET /admin/manage_admins` - Admin user management
- `POST /admin/user/add` - Add user
- `POST /admin/fob/add` - Add equipment
- `POST /admin/user/deactivate/<id>` - Deactivate user
- `POST /admin/user/activate/<id>` - Activate user
- `POST /admin/fob/deactivate/<id>` - Deactivate equipment
- `POST /admin/fob/activate/<id>` - Activate equipment
- `GET /admin/export/history` - Export checkout history CSV
- `POST /admin/fob/reserve/<id>` - Create reservation
- `GET /admin/fob/barcode/<id>` - Generate barcode
- `POST /admin/fob/note/add/<id>` - Add note
- `POST /admin/fob/note/edit/<id>` - Edit note and expiration
- `GET /admin/fob/note/expire/<id>` - Expire note immediately
- `GET /admin/fob/note/delete/<id>` - Delete note
- `POST /admin/admins/add` - Add admin user
- `POST /admin/admins/delete/<id>` - Remove admin user

### Kiosk API (HTTP Basic Auth)
**User/Equipment Registration:**
- `POST /api/user/register` - Register new user
  - Body: `{card_id, first_name, last_name}`
  - Returns: Full user object with ID
- `POST /api/equipment/register` - Register new equipment
  - Body: `{fob_id, vehicle_name, category, location}`
  - Returns: Full equipment object with ID

**Checkout/Checkin:**
- `POST /api/checkout` - Check out single item
  - Body: `{user_id, fob_id, kiosk_id}`
- `POST /api/checkin` - Check in single item
  - Body: `{fob_id}`
- `POST /api/bulk_checkout` - Check out multiple items
  - Body: `{user_id, fob_ids: [id1, id2, ...], kiosk_id}`
  - Returns: `{checked_out: [...], errors: [...]}`

**Special Functions:**
- `POST /api/barns_transfer` - Transfer vehicle to The Barns
  - Body: `{fob_id, kiosk_id}`
  - Auto-creates "The Barns" user if needed
- `POST /api/user/replace_card` - Replace user's keycard
  - Body: `{user_id, new_card_id}`

**Notes:**
- `POST /api/note/add` - Add or replace note
  - Body: `{fob_id, note_text, expires_at (optional ISO datetime)}`
- `POST /api/note/delete` - Delete note
  - Body: `{fob_id}`

**System:**
- `POST /api/notify` - Trigger dashboard refresh (WebSocket broadcast)


## Database Schema

**Tables:**
- `users` - Employees (card_id, first_name, last_name, is_active)
- `key_fobs` - Equipment/vehicles (fob_id, vehicle_name, category, location, is_active)
- `checkouts` - Transaction log (user_id, fob_id, checked_out_at, checked_in_at, kiosk_id)
- `reservations` - Future reservations (fob_id, user_id, reserved_datetime, reserved_for_name, reason, display_hours_before, is_active)
- `notes` - Equipment notes (fob_id, note_text, created_at, created_by, **expires_at**)
- `admin_users` - Admin authentication (username, password_hash)

**New in v2.0:**
- `expires_at` column in notes table for auto-expiring notes

## Configuration

**Default Admin Password:** `admin123`  
⚠️ **CHANGE THIS IN PRODUCTION!**

**Session Timeout:** 30 seconds at kiosk  
**Database Compact:** Weekly automatic VACUUM  
**Timezone:** All timestamps in Central Time (America/Chicago)  

## Categories

Dashboard and admin panel organize equipment into:
- **Squad Cars** - Patrol vehicles (48-100, SRO 1-6)
- **Specialized Services Vehicles** - Non-patrol vehicles
- **CID Vehicles** - Detective vehicles
- **Other Vehicles** - Command staff, special purpose
- **Equipment** - Non-vehicle items (AEDs, launchers, etc.)

## Support & Maintenance

**Estimated Maintenance:** <2 hours/month
- Database auto-compacts weekly
- Expired notes auto-delete
- Logs rotate automatically
- Simple Python/Flask stack

**Monitoring:**
- Check Flask logs for errors
- Monitor database size growth
- Verify WebSocket connections

## Security Notes

**Air-Gapped Design:**
- No connection to HR or building access systems
- Only stores: RFID number, first name, last name
- No employee IDs, SSNs, or PII
- Card numbers are random identifiers

**Production Hardening:**
- Change default admin password
- Enable HTTPS (reverse proxy recommended)
- Use strong authentication (Okta recommended)
- Store database outside Docker container
- Regular backups
- Firewall kiosk endpoints (only accessible from kiosk IPs)

## Known Limitations
- SQLite not recommended for >10 concurrent kiosks (use PostgreSQL)
- No email notifications (add if needed)
- No mobile app (web dashboard is mobile-responsive)
- Note expiration granularity is page-load dependent (checks on refresh)
- Network required for all operations (no offline mode)

## Troubleshooting

**Kiosk can't connect to server:**
- Verify SERVER_URL is correct in launcher script
- Check network connectivity: `ping <server-ip>`
- Verify KIOSK_USER and KIOSK_PASS match server configuration
- Check server logs for authentication errors
- Ensure server is running: `docker ps` (should show checkout-app)

**RFID/Barcode scanner not working:**
- Verify USB connection (try different port)
- Test by scanning into Notepad - should type numbers/letters
- Ensure devices are HID keyboard wedge type (no drivers needed)
- Check USB power if using hub

**Python not found:**
- Install Python 3.11+ from [python.org](https://www.python.org/downloads/)
- During installation, check "Add Python to PATH"
- Restart Command Prompt/Terminal after install

**Emojis show as boxes:**
- **Windows:** Should work on Windows 10/11 by default
- **Linux:** Install emoji font: `sudo apt install fonts-noto-color-emoji`
- Restart kiosk after font installation

**Import errors when running:**
- Ensure virtual environment is activated
- Re-run: `pip install --break-system-packages -r requirements.txt`
- Check Python version: `python --version` (should be 3.11+)

**Expired notes not disappearing:**
- Notes are deleted when dashboard loads/refreshes
- WebSocket updates every 5 seconds trigger cleanup
- Check server logs for errors in note filtering code

## Contact
Sam Bollman  
Fargo Police Department  
[Your Email]

## License
Proprietary - Internal use only
