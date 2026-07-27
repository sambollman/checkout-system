@echo off
echo Starting Bike Station Kiosk...

REM Set server connection details
REM SERVER_URL must be the internal-only kiosk host - it is the only hostname
REM that preserves the Authorization header this kiosk needs for Basic Auth.
set SERVER_URL=https://pd-checkout-kiosk.cityoffargo.com
set KIOSK_USER=kiosk
set KIOSK_PASS=change-this-in-production

REM Navigate to script directory
cd /d %~dp0

REM Activate virtual environment
call venv\Scripts\activate

REM Run kiosk with trikke-station ID
python kiosk_gui.py --kiosk-id downtown

pause
