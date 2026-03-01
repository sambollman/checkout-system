# Vehicle & Equipment Checkout System

RFID-based self-service checkout system for tracking vehicles and equipment. Employees scan their keycard and equipment fob - system tracks who has what, when, and where.

## Current Status
Working prototype running on Raspberry Pi 5. Ready for production deployment on IT infrastructure.

## Features
- **Self-service kiosk:** Scan card, scan fob, done (3 seconds)
- **Real-time dashboard:** Live status updates via WebSocket
- **Admin panel:** User/equipment management, checkout history, reservations
- **Reservations:** Soft-reserve equipment with kiosk warnings
- **Notes:** Digital equipment tags (e.g., "Computer broken")
- **Barcode support:** Print labels for equipment without RFID fobs
- **Multi-location ready:** Tracks which kiosk (garage, station, warehouse)
- **Mobile responsive:** Dashboard works on phones/tablets
- **Dark mode:** For both dashboard and admin panel

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
pip install -r requirements.txt

# Initialize database
python database.py

# Run Flask server
python app.py

# In another terminal, run kiosk GUI
python kiosk_gui.py
```

Access dashboard at: http://localhost:5000
Admin panel at: http://localhost:5000/admin (password: `admin123`)

### Server Setup
(existing Docker instructions stay here...)

### Running the Kiosk

**Windows:**
1. Install Python 3.11+
2. Clone repository
3. Double-click `Start_Kiosk.bat`

**Linux:**
1. Install Python 3.11+
2. Clone repository
3. Run: `./start_kiosk.sh`

**Note:** Update environment variables in the launcher scripts for production:
- `KIOSK_USER` - Username for Basic Auth
- `KIOSK_PASS` - Password for Basic Auth  
- `SERVER_URL` - URL of the server (e.g., `https://checkout.company.local`)

For production deployment, IT should set these to secure values.


## Production Deployment
### Authentication

The application supports two authentication modes:

#### Development Mode (Default)
- Admin panel uses simple password authentication
- Default password: `admin123` (change this!)
- Kiosk endpoints use HTTP Basic Auth with username/password

#### Production Mode (Okta Proxy)
Set the `USERNAME_HEADER_NAME` environment variable to enable Okta authentication:
```bash
# Docker run example
docker run -d \
  --name checkout-app \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e DB_PATH=/data/key_checkout.db \
  -e USERNAME_HEADER_NAME=x-auth-proxy-username \
  -e KIOSK_USER=kiosk \
  -e KIOSK_PASS=secure-password \
  checkout-system
```

**How it works:**
1. IT's Okta proxy authenticates users
2. Proxy passes username in HTTP header (e.g., `x-auth-proxy-username: sam.bollman`)
3. Application reads header and checks against authorized admin list
4. Kiosk endpoints bypass Okta and use HTTP Basic Auth

**Authorized Admins:**

Admins are managed via the web UI - no code changes needed!

1. **Initial Setup:** Add first admin to database:
```bash
   sqlite3 /path/to/key_checkout.db "INSERT INTO admin_users (username, password_hash) VALUES ('your.username', '');"
```

2. **Adding More Admins:** 
   - Log in to admin panel
   - Click "Manage Admins"
   - Add usernames (they'll authenticate via Okta)

3. **Removing Admins:**
   - Go to "Manage Admins"
   - Click "Remove" next to their name

**Note:** In production with Okta, the `password_hash` column is unused. Okta handles authentication, the app only checks if the username exists in the `admin_users` table.


⚠️ **Security:** Only enable `USERNAME_HEADER_NAME` when application is behind Okta proxy. If accessible directly, anyone can forge the header.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | Yes | `key_checkout.db` | Path to SQLite database file |
| `KIOSK_USER` | Yes | `kiosk` | Username for kiosk Basic Auth |
| `KIOSK_PASS` | Yes | `change-this-in-production` | Password for kiosk Basic Auth |
| `USERNAME_HEADER_NAME` | No | None | Header name for Okta username (e.g., `x-auth-proxy-username`) |
| `SERVER_URL` | Kiosk only | `http://localhost:5000` | Server URL for kiosk client |


### Environment Variables

**Database Location:**
```bash
export DB_PATH=/data/checkout.db
```

**Kiosk Configuration:**
```bash
export SERVER_URL=https://checkout.company.local
export KIOSK_USER=kiosk_username
export KIOSK_PASS=kiosk_password
```

### Docker Deployment

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5000

# Run with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
```

**Run Container:**
```bash
docker build -t checkout-system .
docker run -d \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e DB_PATH=/data/checkout.db \
  checkout-system
```

### Database Setup

**PostgreSQL Migration:**
1. Export SQLite data: `sqlite3 key_checkout.db .dump > backup.sql`
2. Modify `database.py` to use PostgreSQL connection
3. Import data to PostgreSQL
4. Update `DB_PATH` environment variable

**Auto-Compacting:**
Database automatically runs VACUUM weekly to reclaim space.

### Authentication Integration

**Okta Proxy:**
App expects authenticated user info in request header. Modify admin routes to read token:
```python
def get_current_user():
    token = request.headers.get('X-Auth-Token')
    # Parse token to extract username
    return username
```

**Kiosk Basic Auth:**
Kiosk supports HTTP Basic Authentication - set `KIOSK_USER` and `KIOSK_PASS` environment variables.

### Multi-Kiosk Deployment

**Architecture:**
```
Central Server (Flask + PostgreSQL)
    ├── Kiosk 1 (Garage)
    ├── Kiosk 2 (Station)
    └── Kiosk 3 (Warehouse)
```

Each kiosk configured with:
- `SERVER_URL`: Central server address
- Authentication credentials
- Unique `kiosk_id` (set in kiosk code)

## Hardware Requirements

### Server
- VM or container
- 2-4 CPU cores
- 4-8 GB RAM
- 50 GB storage
- PostgreSQL database

### Kiosk (per location)
- Thin client PC or Raspberry Pi 5
- HID RFID Prox reader ($80-120)
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
├── templates/
│   ├── index.html        # Main dashboard
│   ├── admin.html        # Admin panel
│   ├── reserve_fob.html  # Reservation form
│   └── add_note.html     # Note form
├── key_checkout.db       # SQLite database (dev only)
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## API Endpoints

### Public
- `GET /` - Main dashboard

### Admin (authenticated)
- `GET /admin` - Admin dashboard
- `POST /admin/user/add` - Add user
- `POST /admin/fob/add` - Add equipment
- `GET /admin/export/history` - Export CSV
- `POST /admin/fob/reserve/<id>` - Create reservation
- `GET /admin/fob/barcode/<id>` - Generate barcode

### Kiosk (Basic Auth)
- `POST /api/notify` - Trigger dashboard refresh
- `GET /api/status` - Get current equipment status
- `POST /api/offline_sync/checkout` - Sync offline checkout
- `POST /api/offline_sync/checkin` - Sync offline checkin

### Admin User Management
- `GET /admin/admins` - Manage admin users
- `POST /admin/admins/add` - Add new admin
- `POST /admin/admins/delete/<id>` - Remove admin

## Database Schema

**Tables:**
- `users` - Employees (card_id, first_name, last_name)
- `key_fobs` - Equipment/vehicles (fob_id, vehicle_name, category)
- `checkouts` - Transaction log (user_id, fob_id, checked_out_at, checked_in_at)
- `reservations` - Future reservations (fob_id, user_id, reserved_datetime)
- `notes` - Equipment notes (fob_id, note_text)
- `admin_users` - Admin authentication

## Configuration

**Default Admin Password:** `admin123`  
⚠️ **CHANGE THIS IN PRODUCTION!**

**Session Timeout:** 30 seconds at kiosk  
**Database Compact:** Weekly automatic VACUUM  
**Timezone:** All timestamps in Central Time (America/Chicago)

## Support & Maintenance

**Estimated Maintenance:** <2 hours/month
- Database auto-compacts weekly
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
- Enable HTTPS
- Use strong authentication (Okta recommended)
- Store database outside Docker container
- Regular backups

## Known Limitations
- SQLite not recommended for >10 concurrent kiosks (use PostgreSQL)
- No email notifications (add if needed)
- No mobile app (web dashboard is mobile-responsive)

## Future Enhancements
- Email/Teams notifications on checkout
- Mobile app for status viewing
- RFID location tracking
- Integration with maintenance scheduling
- Advanced analytics and reporting

## Contact
Sam Bollman  
[Your Email]  
[Your Phone]

## License
Proprietary - Internal use only
