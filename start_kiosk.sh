#!/bin/bash
# Checkout System Kiosk Launcher for Linux
# Double-click this file (or run: ./start_kiosk.sh) to start the kiosk

# Set environment variables (update KIOSK_PASS for production)
# SERVER_URL must be the internal-only kiosk host - it is the only hostname
# that preserves the Authorization header this kiosk needs for Basic Auth.
export KIOSK_USER=kiosk
export KIOSK_PASS=change-this-in-production
export SERVER_URL=https://pd-checkout-kiosk.cityoffargo.com

# Navigate to script directory
cd "$(dirname "$0")"

# Activate virtual environment and run kiosk
source venv/bin/activate
python kiosk_gui.py
