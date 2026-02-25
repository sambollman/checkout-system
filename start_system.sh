#!/bin/bash

# Start Flask in background
cd /home/pi/key-checkout-system
source venv/bin/activate
python app.py > flask.log 2>&1 &

# Wait a moment for Flask to start
sleep 3

# Start kiosk GUI
python kiosk_gui.py

# Keep terminal open if there's an error
echo "Press Enter to close..."
read
