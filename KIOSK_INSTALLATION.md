# Kiosk Installation Guide - Windows Laptop

**Time Required:** 30-45 minutes  
**Bring:** USB drive with code, RFID reader, test keycard, server info from IT

---

## Pre-Installation Checklist

- [ ] Laptop has admin privileges
- [ ] Internet connection available (for downloading Python)
- [ ] Server URL from IT: ______________________________
- [ ] Kiosk username from IT: ______________________________
- [ ] Kiosk password from IT: ______________________________

---

## Step 1: Install Python 3.11

1. Open browser, go to: **https://python.org/downloads/**
2. Click "Download Python 3.11.x" (latest 3.11 version)
3. Run the installer
4. ⚠️ **CRITICAL:** Check ☑ "Add Python to PATH"
5. Click "Install Now"
6. Wait for installation to complete
7. Click "Close"
8. **Restart the laptop**

**Verify Installation:**
```cmd
Win+R → type "cmd" → Enter
python --version
```
Should show: `Python 3.11.x`

- [ ] Python 3.11 installed
- [ ] Added to PATH
- [ ] Version verified

---

## Step 2: Get the Code

**Option A: Clone from GitHub** (if internet available):
```cmd
cd C:\
git clone https://github.com/sambollman/checkout-system.git
cd checkout-system
```

**Option B: Copy from USB:**
1. Insert USB drive
2. Open File Explorer
3. Copy `checkout-system` folder to `C:\`
4. Open Command Prompt:
```cmd
cd C:\checkout-system
```

- [ ] Code copied to `C:\checkout-system`

---

## Step 3: Create Virtual Environment
```cmd
python -m venv venv
```

Wait for completion (30-60 seconds).

- [ ] Virtual environment created

---

## Step 4: Activate Virtual Environment
```cmd
venv\Scripts\activate
```

Prompt should change to: `(venv) C:\checkout-system>`

- [ ] Virtual environment activated (see `(venv)` in prompt)

---

## Step 5: Install Dependencies
```cmd
pip install -r requirements.txt
```

Wait for all packages to install (2-3 minutes).

- [ ] All dependencies installed

---

## Step 6: Configure Server Settings
```cmd
notepad Start_Kiosk.bat
```

**Find these lines and update:**
```batch
set SERVER_URL=http://localhost:5000
set KIOSK_USER=kiosk
set KIOSK_PASS=change-this-in-production
```

**Change to IT's values:**
```batch
set SERVER_URL=<PASTE_SERVER_URL_HERE>
set KIOSK_USER=<PASTE_USERNAME_HERE>
set KIOSK_PASS=<PASTE_PASSWORD_HERE>
```

**Save:** File → Save  
**Close:** File → Exit

- [ ] Server URL configured
- [ ] Username configured
- [ ] Password configured

---

## Step 7: Test the Kiosk
```cmd
Start_Kiosk.bat
```

**Expected Results:**

✅ **If server is ready:**
- Large key icon 🔑
- "Scan your keycard to begin"
- Buttons at bottom (Bulk Checkout, Barns Transfer, etc.)

⚠️ **If server not deployed yet:**
- Orange banner: "⚠️ OFFLINE MODE (0 pending)"
- Everything else works the same
- Will sync when server comes online

**Close the kiosk:** Click the X button

- [ ] Kiosk launches successfully
- [ ] Shows either online or offline mode

---

## Step 8: Test RFID Reader

1. Plug in OMNIKEY reader via USB
2. Windows will detect it (no driver needed)
3. Open Notepad
4. Scan an employee keycard
5. Should type numbers/letters in Notepad

**Then test in kiosk:**
```cmd
Start_Kiosk.bat
```
Scan keycard → should show employee greeting

- [ ] Reader detected by Windows
- [ ] Reader outputs in Notepad
- [ ] Reader works in kiosk

---

## Step 9: Set Up Auto-Launch (Optional)

**Make kiosk start automatically when laptop boots:**

### Method 1: Startup Folder (Recommended)

1. Press `Win+R`
2. Type: `shell:startup`
3. Press Enter (Startup folder opens)
4. Right-click in folder
5. New → Shortcut
6. Click "Browse"
7. Navigate to: `C:\checkout-system\Start_Kiosk.bat`
8. Click "Next"
9. Click "Finish"

**Test:** Restart laptop → kiosk should auto-launch

- [ ] Shortcut created in Startup folder
- [ ] Tested auto-launch

### Method 2: Full Kiosk Mode (Optional)

**Auto-login so no one needs to log in:**

1. Press `Win+R`
2. Type: `netplwiz`
3. Press Enter
4. Uncheck ☐ "Users must enter a username and password to use this computer"
5. Click "Apply"
6. Enter password when prompted
7. Click "OK"

**Result:** PC boots → auto-login → kiosk launches

- [ ] Auto-login configured (if desired)

---

## Step 10: Optional Settings

### Disable Screen Sleep
1. Settings → System → Power & Sleep
2. Screen: **Never**
3. Sleep: **Never**

### Disable Windows Updates During Work Hours
1. Settings → Windows Update → Advanced Options
2. Active Hours → Set to your shift times

- [ ] Screen sleep disabled
- [ ] Active hours configured

---

## Troubleshooting

### "python is not recognized"
**Problem:** Python not in PATH  
**Solution:** Reinstall Python, check "Add Python to PATH" box

### "Module not found" errors
**Problem:** Virtual environment not activated  
**Solution:** Run `venv\Scripts\activate` first (look for `(venv)` in prompt)

### RFID reader not working
**Problem:** Reader not in keyboard wedge mode  
**Solution:** 
- Verify it outputs in Notepad when you scan
- May need configuration software (ask Cody/IT)
- Try different USB port

### "Cannot connect to server"
**Possible causes:**
- Server not deployed yet (offline mode is OK)
- Wrong SERVER_URL in Start_Kiosk.bat
- Firewall blocking connection
- Wrong username/password

**Check:**
```cmd
curl http://YOUR-SERVER-URL/api/status -u username:password
```
Should return JSON data if working.

### Kiosk window too small/large
**Solution:** The GUI auto-sizes, but you can:
- Press F11 for fullscreen (press F11 again to exit)
- Adjust Windows display scaling: Settings → Display → Scale

---

## Installation Complete! ✅

**Final Checklist:**
- [ ] Python 3.11 installed
- [ ] Code in C:\checkout-system
- [ ] Dependencies installed
- [ ] Server settings configured
- [ ] Kiosk launches successfully
- [ ] RFID reader works
- [ ] Auto-launch configured (optional)

**Next Steps:**
1. Wait for IT to deploy server
2. Add employees and equipment via admin panel
3. Train employees on kiosk usage

**Support:**
- Sam Bollman: [Your Phone/Email]
- GitHub: https://github.com/sambollman/checkout-system
- Documentation: README.md, DEPLOYMENT.md

---

## Quick Reference Commands

**Activate virtual environment:**
```cmd
cd C:\checkout-system
venv\Scripts\activate
```

**Start kiosk manually:**
```cmd
Start_Kiosk.bat
```

**Update code from GitHub:**
```cmd
cd C:\checkout-system
git pull
```

**Reinstall dependencies after update:**
```cmd
venv\Scripts\activate
pip install -r requirements.txt
```

---

**Installation Date:** _______________  
**Installed By:** _______________  
**Tested By:** _______________  
**Notes:** _______________________________________________
