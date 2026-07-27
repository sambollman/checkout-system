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

### 5. Configure Reverse Proxy

> **Do not use a single catch-all `location /` for this system.** In production it
> is served on three hostnames with three different auth models (Okta staff site,
> anonymous internal-only display, Basic-Auth internal-only kiosk API). One
> `proxy_pass` with no path split either breaks the kiosks or exposes the
> PII-bearing `/api/vehicle/<id>` route to anyone who can reach the host.
>
> The authoritative configuration is **README.md -> Production Reverse Proxy**
> (`pd-checkout.cityoffargo.com.conf` plus `snippets/internal-only.conf`). Follow
> that section. The minimal one-location snippet that used to be printed here was
> removed because copying it literally produced an open deployment.

The proxy must satisfy all of these:
- [ ] TLS terminated at nginx; 80 -> 443 redirect on all three hostnames
- [ ] Internal DNS records exist for `pd-checkout-display` and `pd-checkout-kiosk`
- [ ] `X-Auth-Proxy-Username` is set by the auth-proxy and cleared on every path
      where a client could otherwise supply it
- [ ] `Authorization` is preserved *only* on the kiosk host's `/api/` location
- [ ] `snippets/internal-only.conf` is included on the display and kiosk server
      blocks, and on the main site's `/api/vehicle/` location

### 6. Verify Deployment
- [ ] Can access admin panel via public URL
- [ ] OKTA authentication works
- [ ] Can add/remove admin users via `/admin/admins`

---

## My Setup Tasks (After IT Deploys)

### Main Kiosk Computer
The kiosk is a native application that only calls `/api/*`. It must use the
dedicated kiosk hostname, not the public staff URL.
```batch
# Edit Start_Kiosk.bat:
set SERVER_URL=https://pd-checkout-kiosk.cityoffargo.com
set KIOSK_USER=<USERNAME_FROM_IT>
set KIOSK_PASS=<PASSWORD_FROM_IT>
```

### Downtown Trikke Station
```batch
# Edit Start_Trikke_Kiosk.bat:
set SERVER_URL=https://pd-checkout-kiosk.cityoffargo.com
set KIOSK_USER=<USERNAME_FROM_IT>
set KIOSK_PASS=<PASSWORD_FROM_IT>
```

### Dashboard Display Computer
Uses the anonymous read-only display host — no credentials. It serves only the
dashboard, static assets, the WebSocket, and `/api/vehicle/<id>`.
```batch
# Chrome kiosk mode shortcut:
chrome.exe --kiosk --app=https://pd-checkout-display.cityoffargo.com
```

Both the kiosk and display hostnames are restricted to internal networks, so
these machines must be on the internal network to reach them.

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

- [ ] Add admin users via `/admin/admins`
- [ ] Add all employees to system
- [ ] Add all equipment/vehicles with fobs
- [ ] Test checkout/checkin from main kiosk
- [ ] Test checkout/checkin from downtown kiosk
- [ ] Verify dashboard updates in real-time
- [ ] Test offline mode (disconnect network, scan, reconnect)
- [ ] Set up dashboard display on TV
- [ ] Train employees on kiosk usage
