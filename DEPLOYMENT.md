# Production Deployment Guide

This guide covers deploying the Vehicle & Equipment Checkout System to production.

## Prerequisites

- Docker installed on server
- PostgreSQL database (recommended) or SQLite for testing
- Network connectivity between kiosks and server
- Windows PCs for kiosks with USB ports

---

## Step 1: Server Deployment

### 1.1 Clone Repository
```bash
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system
```

### 1.2 Generate Secure Credentials

Generate a secure password for kiosk authentication:
```bash
# Example - use your own secure password
KIOSK_PASSWORD="YourSecurePassword123!"
```

**Important:** This password will be used by all kiosks to authenticate to the server.

### 1.3 Build Docker Image
```bash
docker build -t checkout-system .
```

### 1.4 Run Docker Container

**For Production:**
```bash
docker run -d \
  --name checkout-app \
  --restart unless-stopped \
  -p 5000:5000 \
  -v /path/to/persistent/storage:/data \
  -e DB_PATH=/data/key_checkout.db \
  -e KIOSK_USER=production_kiosk \
  -e KIOSK_PASS=YourSecurePassword123! \
  checkout-system
```

**Replace:**
- `/path/to/persistent/storage` → Your server's data directory
- `YourSecurePassword123!` → Your generated password

### 1.5 Verify Server is Running
```bash
docker ps
curl http://localhost:5000
```

---

## Step 2: Okta Integration (Optional)

If using Okta for admin authentication:

### 2.1 Configure Okta Proxy

Configure your Okta authentication proxy to:
- Protect `/` and `/admin/*` routes
- Pass authenticated username in header: `x-auth-proxy-username`
- Allow `/api/*` to bypass Okta (kiosk endpoints use Basic Auth)

### 2.2 Enable Okta in Application

Set the header name environment variable:
```bash
docker run -d \
  ... (other settings) ...
  -e USERNAME_HEADER_NAME=x-auth-proxy-username \
  checkout-system
```

### 2.3 Add Authorized Admins

Admins are managed via the web UI at `/admin/admins` or directly in the database:
```bash
sqlite3 /path/to/key_checkout.db "INSERT INTO admin_users (username, password_hash) VALUES ('user.name@company.com', '');"
```

---

## Step 3: Kiosk Setup (Windows)

Perform these steps on each kiosk laptop:

### 3.1 Install Python

1. Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. **Important:** Check "Add Python to PATH" during installation
3. Verify installation: Open Command Prompt and run `python --version`

### 3.2 Clone Repository
```cmd
cd C:\
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system
```

Or download ZIP from GitHub and extract to `C:\checkout-system`

### 3.3 Install Dependencies
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3.4 Configure Kiosk

Edit `Start_Kiosk.bat`:
```batch
@echo off
REM Checkout System Kiosk Launcher for Windows

REM Set environment variables - UPDATE THESE FOR PRODUCTION
set KIOSK_USER=production_kiosk
set KIOSK_PASS=YourSecurePassword123!
set SERVER_URL=https://checkout.company.local:5000

REM Navigate to kiosk directory
cd /d "%~dp0"

REM Activate virtual environment and run kiosk
call venv\Scripts\activate.bat
python kiosk_gui.py

pause
```

**Update these values:**
- `KIOSK_PASS` → Same password as server
- `SERVER_URL` → Your production server URL

### 3.5 Test Kiosk

Double-click `Start_Kiosk.bat` - kiosk should launch and connect to server.

### 3.6 Create Desktop Shortcut (Optional)

Right-click `Start_Kiosk.bat` → Send to → Desktop (create shortcut)

---

## Step 4: Dashboard Display Setup (Windows Mini PC)

### 4.1 Install Chrome

Download and install Google Chrome.

### 4.2 Create Auto-Launch Script

Create `C:\LaunchDashboard.bat`:
```batch
@echo off
start chrome.exe --kiosk --app=https://checkout.company.local:5000
```

### 4.3 Auto-Start on Boot

1. Press `Win + R`, type `shell:startup`, press Enter
2. Copy `LaunchDashboard.bat` into the Startup folder
3. Restart to test

Dashboard should auto-launch fullscreen on boot.

---

## Step 5: Hardware Setup

### 5.1 RFID Readers

- **Type:** HID Keyboard Wedge USB RFID readers
- **Installation:** Plug into kiosk laptop USB port
- **Configuration:** None needed - acts as keyboard input

### 5.2 Barcode Scanners

- **Type:** USB Keyboard Wedge barcode scanners
- **Installation:** Plug into kiosk laptop USB port
- **Configuration:** None needed - acts as keyboard input

---

## Security Checklist

- [ ] Changed default `KIOSK_PASS` from `change-this-in-production`
- [ ] Server accessible only on internal network
- [ ] Okta configured for admin authentication (if applicable)
- [ ] Database stored on persistent volume (not in container)
- [ ] HTTPS enabled (via reverse proxy if needed)
- [ ] Firewall rules configured

---

## Troubleshooting

### Kiosk Shows "Offline Mode"

**Check:**
1. `SERVER_URL` is correct in `Start_Kiosk.bat`
2. `KIOSK_USER` and `KIOSK_PASS` match server configuration
3. Network connectivity: `ping checkout.company.local`
4. Server is running: `docker ps`

### RFID/Barcode Not Working

**Check:**
1. USB connection - try different port
2. Test in Notepad - should type characters when scanned
3. Verify device is HID keyboard wedge type (no drivers needed)

### Dashboard Not Auto-Updating

**Check:**
1. Browser console for errors (F12)
2. WebSocket connection status
3. Server logs: `docker logs checkout-app --tail 50`

### Emojis Show as Boxes

**Windows:** Should work on Windows 10/11 by default  
**Linux:** Install emoji font: `sudo apt install fonts-noto-color-emoji`

---

## Maintenance

### Updating the Application

**Server:**
```bash
cd checkout-system
git pull
docker stop checkout-app
docker rm checkout-app
docker build -t checkout-system .
# Run docker run command from Step 1.4
```

**Kiosks:**
```cmd
cd C:\checkout-system
git pull
```
Restart kiosk.

### Database Backup
```bash
# Backup
docker exec checkout-app sqlite3 /data/key_checkout.db ".backup /data/backup.db"
cp /path/to/data/key_checkout.db /path/to/backups/key_checkout_$(date +%Y%m%d).db

# Restore
cp /path/to/backups/key_checkout_YYYYMMDD.db /path/to/data/key_checkout.db
docker restart checkout-app
```

### Viewing Logs
```bash
# Server logs
docker logs checkout-app --tail 100 -f

# Kiosk logs
# Check terminal output when running Start_Kiosk.bat
```

---

## Support Contacts

- **Developer:** Sam Bollman
- **IT Support:** [Your IT Contact]
- **GitHub:** https://github.com/sambollman/checkout-system
