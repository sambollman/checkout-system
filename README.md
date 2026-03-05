# Vehicle & Equipment Checkout System

RFID-based self-service checkout system for tracking vehicles and equipment. Employees scan their keycard and equipment fob - system tracks who has what, when, and where.

## Current Status
Working prototype running on Raspberry Pi 5. Ready for production deployment on IT infrastructure.

## Features
- **Self-service kiosk:** Scan card, scan fob, done (3 seconds)
- **Bulk checkout:** Scan card once, then scan multiple items - perfect for shift changes
- **Real-time dashboard:** Live status updates via WebSocket
- **Admin panel:** Tabbed interface for user/equipment management, checkout history, reservations
- **Reservations:** Soft-reserve equipment with kiosk warnings
- **Notes with expiration:** Digital equipment tags that auto-delete after expiration (e.g., "Computer broken - expires 3/10")
- **Barcode support:** Print labels for equipment without RFID fobs
- **Multi-location ready:** Tracks which kiosk (garage, station, warehouse)
- **Mobile responsive:** Dashboard works on phones/tablets
- **Dark mode:** For both dashboard and admin panel
- **Category Tabs:** Organize vehicles by type (Squad Cars, Specialized Services, CID Vehicles, Equipment)
- **Barns Transfer:** Transfer vehicles to maintenance facility with or without physical fob (scan or select from list)
- **Flexible Kiosk Windows:** Add notes and transfer vehicles either by scanning fobs or selecting from equipment list
- **Clickable Kiosk Interface:** Button-based UI for all kiosk operations
- **Offline mode:** Kiosk queues transactions when server unavailable, auto-syncs when reconnected

## Technology Stack
- **Backend:** Python 3.11, Flask, Flask-SocketIO
- **Database:** SQLite (production: PostgreSQL recommended)
- **Frontend:** HTML, CSS, JavaScript (vanilla - no frameworks)
- **Kiosk:** Python Tkinter GUI
- **Hardware:** HID RFID reader (USB keyboard wedge)

## Quick Start (Development)

### Prerequisites
- Python 3.11+
- Raspberry Pi OS or Linux/macOS

### Installation
```bash
# Clone repository
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --break-system-packages -r requirements.txt

# Initialize database
python database.py

# Run Flask server
python app.py

# In another terminal, run kiosk GUI
python kiosk_gui.py
```

Access dashboard at: http://localhost:5000  
Admin panel at: http://localhost:5000/admin (password: `admin123`)

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

## Production Deployment

### Docker Setup
```bash
# Build image
docker build -t checkout-system .

# Run container
docker run -d \
  --name checkout-app \
  --restart unless-stopped \
  -p 5000:5000 \
  -v ~/key-checkout-system:/data \
  -e DB_PATH=/data/key_checkout.db \
  -e KIOSK_USER=kiosk \
  -e KIOSK_PASS=secure-password-here \
  checkout-system
```

### Authentication

The application supports two authentication modes:

#### Development Mode (Default)
- Admin panel uses simple password authentication
- Default password: `admin123` (change this!)
- Kiosk endpoints use HTTP Basic Auth with username/password

#### Production Mode (Okta Proxy)
Set the `OKTA_HEADER` environment variable to enable Okta authentication:
```bash
docker run -d \
  --name checkout-app \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e DB_PATH=/data/key_checkout.db \
  -e OKTA_HEADER=X-Forwarded-User \
  -e KIOSK_USER=kiosk \
  -e KIOSK_PASS=secure-password \
  checkout-system
```

**How it works:**
1. IT's Okta proxy authenticates users
2. Proxy passes username in HTTP header (e.g., `X-Forwarded-User: sam.bollman`)
3. Application reads header and checks against authorized admin list
4. Kiosk endpoints bypass Okta and use HTTP Basic Auth

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

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | Yes | `key_checkout.db` | Path to SQLite database file |
| `KIOSK_USER` | Yes | `kiosk` | Username for kiosk Basic Auth |
| `KIOSK_PASS` | Yes | `change-this-in-production` | Password for kiosk Basic Auth |
| `OKTA_HEADER` | No | `X-Forwarded-User` | Header name for Okta username |
| `SERVER_URL` | Kiosk only | `http://localhost:5000` | Server URL for kiosk client |

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

### Multi-Kiosk Deployment

**Architecture:**
```
Central Server (Flask + PostgreSQL)
    ├── Kiosk 1 (Garage) - kiosk_id: 'kiosk1'
    ├── Kiosk 2 (Station) - kiosk_id: 'kiosk2'
    └── Kiosk 3 (Warehouse) - kiosk_id: 'kiosk3'
```

Each kiosk configured with:
- `SERVER_URL`: Central server address
- `KIOSK_USER` and `KIOSK_PASS`: Authentication credentials
- Unique `kiosk_id` in `kiosk_gui.py` constructor

**Offline Mode:**
- Kiosks write to local SQLite database when server unavailable
- Transactions queued in `offline_queue.db`
- Auto-sync every 30 seconds when server reconnects
- Status bar shows "⚠️ OFFLINE MODE (X pending)"

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
├── app.py                 # Flask web server
├── kiosk_gui.py          # Kiosk interface
├── database.py           # Database schema and connection
├── offline_queue.py      # Offline transaction queue
├── templates/
│   ├── index.html        # Main dashboard (category tabs)
│   ├── admin.html        # Admin panel (tabbed interface)
│   ├── reserve_fob.html  # Reservation form
│   ├── add_note.html     # Add note form
│   ├── edit_note.html    # Edit note with expiration
│   └── manage_admins.html # Admin user management
├── Start_Kiosk.bat       # Windows launcher
├── start_kiosk.sh        # Linux launcher
├── Launch_Kiosk.desktop  # Raspberry Pi desktop shortcut
├── key_checkout.db       # SQLite database (dev only)
├── offline_queue.db      # Offline transaction queue
├── requirements.txt      # Python dependencies
├── Dockerfile            # Container build
├── DEPLOYMENT.md         # Production deployment guide
└── README.md            # This file
```

## API Endpoints

### Public
- `GET /` - Main dashboard

### Admin (authenticated)
- `GET /admin` - Admin dashboard (tabbed interface)
- `GET /admin/manage_admins` - Admin user management
- `POST /admin/user/add` - Add user
- `POST /admin/fob/add` - Add equipment
- `GET /admin/export/history` - Export CSV
- `POST /admin/fob/reserve/<id>` - Create reservation
- `GET /admin/fob/barcode/<id>` - Generate barcode
- `POST /admin/fob/note/add/<id>` - Add note
- `POST /admin/fob/note/edit/<id>` - Edit note and expiration
- `GET /admin/fob/note/expire/<id>` - Expire note now
- `GET /admin/fob/note/delete/<id>` - Delete note

### Kiosk (Basic Auth)
- `POST /api/notify` - Trigger dashboard refresh
- `GET /api/status` - Get current equipment status
- `POST /api/offline_sync/checkout` - Sync offline checkout
- `POST /api/offline_sync/checkin` - Sync offline checkin

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
**Offline Sync:** Every 30 seconds when server available

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
- Check offline queue for stuck transactions

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

## Troubleshooting

**"Offline Mode" banner appears:**
- Check `SERVER_URL` is correct in launcher script
- Verify network connection to server
- Confirm `KIOSK_USER` and `KIOSK_PASS` match server configuration
- Test: `curl -u username:password SERVER_URL/api/status`

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
