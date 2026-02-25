#!/usr/bin/env python3
import time
from database import get_db
from datetime import datetime

class KioskApp:
    def __init__(self, kiosk_id='kiosk1'):
        self.kiosk_id = kiosk_id
        self.current_user = None
        self.scan_timeout = 30  # seconds
        self.last_scan_time = None
        
    def clear_screen(self):
        """Clear terminal screen"""
        print('\033[2J\033[H')
    
    def display_welcome(self):
        """Show welcome screen"""
        self.clear_screen()
        print("=" * 50)
        print("    VEHICLE KEY CHECKOUT SYSTEM")
        print("=" * 50)
        print()
        print("Scan your keycard to begin...")
        print()
    
    def get_user_by_card(self, card_id):
        """Look up user by card ID"""
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE card_id = ? AND is_active = 1', 
                           (card_id,)).fetchone()
        conn.close()
        return user
    
    def register_new_user(self, card_id):
        """Register a new user"""
        print("\n🆕 First time? Let's get you registered!")
        first_name = input("Enter your first name: ").strip()
        last_name = input("Enter your last name: ").strip()
        
        if not first_name or not last_name:
            print("❌ Name cannot be empty!")
            return None
        
        conn = get_db()
        try:
            conn.execute('INSERT INTO users (card_id, first_name, last_name) VALUES (?, ?, ?)',
                        (card_id, first_name, last_name))
            conn.commit()
            user = conn.execute('SELECT * FROM users WHERE card_id = ?', (card_id,)).fetchone()
            conn.close()
            print(f"\n✅ Welcome, {first_name} {last_name}!")
            return user
        except Exception as e:
            print(f"❌ Error registering user: {e}")
            conn.close()
            return None
    
    def get_fob_by_id(self, fob_id):
        """Look up key fob by ID"""
        conn = get_db()
        fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? AND is_active = 1', 
                          (fob_id,)).fetchone()
        conn.close()
        return fob
    
    def register_new_fob(self, fob_id):
        """Register a new key fob"""
        print("\n🔑 New key fob detected!")
        vehicle_name = input("What vehicle is this for? (e.g., 'Truck #3', 'White Van'): ").strip()
        
        if not vehicle_name:
            print("❌ Vehicle name cannot be empty!")
            return None

        print("\nCategory:")
        print(" 1. Vehicle")
        print(" 2. Equipment")
        category_choice = input("Enter 1 or 2 (press Enter for Vehicle): ").strip()
        category = "Equipment" if category_choice == "2" else "Vehicle"

        location = input("Location (press Enter for 'Main'): ").strip() or "Main"
        
        conn = get_db()
        try:
            conn.execute('INSERT INTO key_fobs (fob_id, vehicle_name, category, location) VALUES (?, ?, ?,?)',
                        (fob_id, vehicle_name, category, location))
            conn.commit()
            fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ?', (fob_id,)).fetchone()
            conn.close()
            print(f"\n✅ Registered: {vehicle_name}")
            return fob
        except Exception as e:
            print(f"❌ Error registering fob: {e}")
            conn.close()
            return None
    
    def get_current_checkout(self, fob_id):
        """Check if a fob is currently checked out"""
        conn = get_db()
        query = '''
            SELECT c.*, u.first_name, u.last_name, kf.vehicle_name
            FROM checkouts c
            JOIN users u ON c.user_id = u.id
            JOIN key_fobs kf ON c.fob_id = kf.id
            WHERE kf.id = ? AND c.checked_in_at IS NULL
        '''
        checkout = conn.execute(query, (fob_id,)).fetchone()
        conn.close()
        return checkout
    
    def checkout_fob(self, user_id, fob_id, vehicle_name):
        """Check out a key fob to a user"""
        conn = get_db()
        conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id) VALUES (?, ?, ?)',
                    (user_id, fob_id, self.kiosk_id))
        conn.commit()
        conn.close()
        print(f"\n✅ {vehicle_name} checked out!")
        print("Return keys to this hook when done.")
    
    def checkin_fob(self, checkout_id, vehicle_name, was_with_user=None):
        """Check in a key fob"""
        conn = get_db()
        conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                    (datetime.now(), checkout_id))
        conn.commit()
        conn.close()
        
        if was_with_user:
            print(f"\n✅ {vehicle_name} returned")
            print(f"(Was with {was_with_user})")
        else:
            print(f"\n✅ {vehicle_name} returned. Thanks!")
    
    def handle_card_scan(self, card_id):
        """Handle a card scan"""
        user = self.get_user_by_card(card_id)
        
        if not user:
            user = self.register_new_user(card_id)
            if not user:
                return
        
        self.current_user = user
        self.last_scan_time = time.time()
        
        print(f"\n👋 Hi, {user['first_name']} {user['last_name']}!")
        print("\nNow scan the key fob you want to check out...")
    
    def handle_fob_scan(self, fob_id):
        """Handle a fob scan"""
        fob = self.get_fob_by_id(fob_id)
        
        if not fob:
            fob = self.register_new_fob(fob_id)
            if not fob:
                return
        
        # Check if it's currently checked out
        current_checkout = self.get_current_checkout(fob['id'])
        
        if current_checkout:
            # Fob is checked out - return it
            was_with = f"{current_checkout['first_name']} {current_checkout['last_name']}"
            self.checkin_fob(current_checkout['id'], fob['vehicle_name'], was_with)
            self.current_user = None
        else:
            # Fob is available
            if self.current_user:
                # Check it out to current user
                self.checkout_fob(self.current_user['id'], fob['id'], fob['vehicle_name'])
                self.current_user = None
            else:
                # No user scanned yet
                print(f"\n{fob['vehicle_name']} is available.")
                print("Scan your keycard first to check it out.")
    
    def check_timeout(self):
        """Check if we should timeout the current user"""
        if self.current_user and self.last_scan_time:
            if time.time() - self.last_scan_time > self.scan_timeout:
                print("\n⏱️  Session timeout. Starting over...")
                self.current_user = None
                self.last_scan_time = None
                time.sleep(2)
                return True
        return False
    
    def run(self):
        """Main kiosk loop"""
        print("\n🚀 Kiosk starting...\n")
        time.sleep(1)
        
        while True:
            self.display_welcome()
            
            if self.current_user:
                print(f"Current user: {self.current_user['first_name']} {self.current_user['last_name']}")
                print("Waiting for fob scan...")
                print()
            
            # For testing without RFID reader: simulate scanning
            print("=" * 50)
            print("TESTING MODE: Type card/fob numbers")
            print("Card IDs: Start with 'C' (e.g., C12345)")
            print("Fob IDs: Start with 'F' (e.g., F67890)")
            print("Type 'quit' to exit")
            print("=" * 50)
            
            scan = input("\nScan: ").strip()
            
            if scan.lower() == 'quit':
                print("\n👋 Goodbye!")
                break
            
            # Check for timeout
            if self.check_timeout():
                continue
            
            # Determine if it's a card or fob based on prefix
            if scan.startswith('C'):
                self.handle_card_scan(scan)
            elif scan.startswith('F'):
                self.handle_fob_scan(scan)
            else:
                print("❌ Invalid scan. Use C for cards, F for fobs.")
            
            time.sleep(2)

if __name__ == '__main__':
    kiosk = KioskApp()
    kiosk.run()
