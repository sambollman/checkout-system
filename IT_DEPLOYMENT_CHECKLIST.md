# IT Deployment Checklist - Vehicle Checkout System

## Information Needed From IT

### OKTA Configuration
- [ ] **OKTA Header Name:** _______________________
  - Example: `X-Forwarded-User`, `X-Auth-User`, `Remote-User`
  - This is the HTTP header that will contain the authenticated username

- [ ] **Username Format:** _______________________
  - Example: `sam.bollman`, `sbollman`, `sbollman@fargond.gov`
  - Must match exactly when adding admin users

### Server Information
- [ ] **Public URL:** _______________________
  - Example: `https://checkout.fargond.gov`
  - This is what kiosks will connect to

- [ ] **Server IP (if no DNS):** _______________________
  - Example: `http://192.168.1.100:5000`

- [ ] **Kiosk Authentication:**
  - Username: _______________________ (default: `kiosk`)
  - Password: _______________________ (IT will generate secure password)

### Security Confirmation
- [ ] Port 5000 will be bound to localhost only (`127.0.0.1:5000`)
- [ ] Reverse proxy will handle HTTPS/SSL
- [ ] Only proxy server can access port 5000 (firewalled)

---

## IT Deployment Steps

### 1. Clone Repository
```bash
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system
```

### 2. Build Docker Image
```bash
docker build -t checkout-system .
```

### 3. Run Docker Container
```bash
docker run -d \
  --name checkout-app \
  --restart unless-stopped \
  -p 127.0.0.1:5000:5000 \
  -v /data:/data \
  -e DB_PATH=/data/key_checkout.db \
  -e OKTA_HEADER=<HEADER_NAME_FROM_IT> \
  -e KIOSK_USER=<USERNAME_FROM_IT> \
  -e KIOSK_PASS=<PASSWORD_FROM_IT> \
  checkout-system
```

### 4. Initialize Database (First Admin User)
```bash
sqlite3 /data/key_checkout.db "INSERT INTO admin_users (username, password_hash) VALUES ('<your.username>', '');"
```

### 5. Configure Reverse Proxy (nginx example)
```nginx
location / {
    proxy_pass http://localhost:5000;
    proxy_set_header <OKTA_HEADER_NAME> $remote_user;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### 6. Verify Deployment
- [ ] Can access admin panel via public URL
- [ ] OKTA authentication works
- [ ] Can add/remove admin users via `/admin/manage_admins`

---

## My Setup Tasks (After IT Deploys)

### Main Kiosk Computer
```batch
# Edit Start_Kiosk.bat:
set SERVER_URL=<PUBLIC_URL_FROM_IT>
set KIOSK_USER=<USERNAME_FROM_IT>
set KIOSK_PASS=<PASSWORD_FROM_IT>
```

### Downtown Trikke Station
```batch
# Edit Start_Trikke_Kiosk.bat:
set SERVER_URL=<PUBLIC_URL_FROM_IT>
set KIOSK_USER=<USERNAME_FROM_IT>
set KIOSK_PASS=<PASSWORD_FROM_IT>
```

### Dashboard Display Computer
```batch
# Chrome kiosk mode shortcut:
chrome.exe --kiosk --app=<PUBLIC_URL_FROM_IT>
```

---

## Quick Reference

**GitHub Repo:** https://github.com/sambollman/checkout-system

**Documentation:**
- Full deployment guide: `DEPLOYMENT.md`
- OKTA setup details: `README.md` (search "OKTA")
- Multi-kiosk setup: `README.md` (search "Multi-Kiosk")

**Support Contact:**
- Sam Bollman
- [Your Email]
- [Your Phone]

---

## Post-Deployment Checklist

- [ ] Add admin users via `/admin/manage_admins`
- [ ] Add all employees to system
- [ ] Add all equipment/vehicles with fobs
- [ ] Test checkout/checkin from main kiosk
- [ ] Test checkout/checkin from downtown kiosk
- [ ] Verify dashboard updates in real-time
- [ ] Test offline mode (disconnect network, scan, reconnect)
- [ ] Set up dashboard display on TV
- [ ] Train employees on kiosk usage
