#!/bin/bash
# Checkout System Kiosk Launcher for Linux
# Double-click this file (or run: ./start_kiosk.sh) to start the kiosk

# Set environment variables (update these for production)
export KIOSK_USER=kiosk
export KIOSK_PASS=change-this-in-production
export SERVER_URL=http://localhost:5000

# Navigate to script directory
cd "$(dirname "$0")"

# Activate virtual environment and run kiosk
source venv/bin/activate
python kiosk_gui.py
