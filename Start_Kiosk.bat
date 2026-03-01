@echo off
REM Checkout System Kiosk Launcher for Windows
REM Double-click this file to start the kiosk application

REM Set environment variables (update these for production)
set KIOSK_USER=kiosk
set KIOSK_PASS=test-password-123
set SERVER_URL=http://localhost:5000

REM Navigate to kiosk directory
cd /d "%~dp0"

REM Activate virtual environment and run kiosk
call venv\Scripts\activate.bat
python kiosk_gui.py

REM Keep window open if there's an error
pause
