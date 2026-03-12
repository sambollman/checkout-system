@echo off
echo Starting Bike Station Kiosk...

REM Set server connection details
set SERVER_URL=http://localhost:5000
set KIOSK_USER=kiosk
set KIOSK_PASS=change-this-in-production

REM Navigate to script directory
cd /d %~dp0

REM Activate virtual environment
call venv\Scripts\activate

REM Run kiosk with trikke-station ID
python kiosk_gui.py --kiosk-id downtown

pause
