@echo off
REM Checkout System Kiosk Launcher for Windows
REM Double-click this file to start the kiosk application

REM Set environment variables (update KIOSK_PASS for production)
REM SERVER_URL must be the internal-only kiosk host - it is the only hostname
REM that preserves the Authorization header this kiosk needs for Basic Auth.
set KIOSK_USER=kiosk
set KIOSK_PASS=change-this-in-production
set SERVER_URL=https://pd-checkout-kiosk.cityoffargo.com

REM Navigate to kiosk directory
cd /d "%~dp0"

REM Activate virtual environment and run kiosk
call venv\Scripts\activate.bat
python kiosk_gui.py

REM Keep window open if there's an error
pause
