#!/usr/bin/env python3
import tkinter as tk
from tkinter import font
import time
from database import get_db
from datetime import datetime, timedelta
import threading
import pytz
import threading
import requests
import os

# Server configuration
SERVER_URL = os.getenv('SERVER_URL', 'http://localhost:5000')
KIOSK_USER = os.getenv('KIOSK_USER', 'kiosk')
KIOSK_PASS = os.getenv('KIOSK_PASS', 'change-this-in-production')


class KioskGUI:
    def __init__(self, kiosk_id='kiosk1'):
        self.kiosk_id = kiosk_id
        self.current_user = None
        self.scan_timeout = 60
        self.last_scan_time = None
        self.pending_fob = None
        self.pending_fob_mark_available = False
        self.replace_mode = None # 'card' or 'fob'
        self.replace_item = None # The item being replaced
        self.note_mode = False
        self.barns_scan_mode = False
        self.unavailable_mode = False
        self.pending_unavailable_fob = None
        self.bulk_checkout_mode = False
        self.bulk_items = []


        # Create main window
        self.root = tk.Tk()
        self.root.title("Key Checkout Kiosk")
        self.root.configure(bg='black')
        self.root.attributes('-fullscreen', True)
        self.root.bind('<F12>', self.exit_fullscreen)
        self.root.bind('<F11>', self.enter_fullscreen)
        self.root.bind('<Escape>', self.emergency_reset)
    
        # Create fonts
        self.title_font = font.Font(family='Arial', size=48, weight='bold')
        self.header_font = font.Font(family='Arial', size=36, weight='bold')
        self.body_font = font.Font(family='Arial', size=24)
        self.small_font = font.Font(family='Arial', size=18)
        
        # Title at top (outside container)
        self.title_label = tk.Label(
            self.root,
            text="VEHICLE & EQUIPMENT CHECKOUT",
            font=self.title_font,
            fg='white',
            bg='black'
        )
        self.title_label.pack(pady=(80, 10))
        
        # Main message area - centered
        self.message_frame = tk.Frame(self.root, bg='black')
        self.message_frame.pack(expand=True)

        # Hidden entry field to capture keyboard input
        self.entry = tk.Entry(self.root)
        self.entry.place(x=-100, y=-100)  # Hide it off-screen
        self.entry.focus_set()
        self.entry.bind('<Return>', lambda e: None)  # Prevent beep on Enter
        
        # Instructions at bottom (outside container)
        self.instructions_label = tk.Label(
            self.root,
            text="",
            font=self.small_font,
            fg='#666666',
            bg='black',
            justify='center'
        )
        self.instructions_label.pack(pady=(10, 20))

        # Bind keyboard input
        self.root.bind('<Key>', self.on_key_press)
        self.scan_buffer = ""
        
        # Show welcome screen
        # Check server connection on startup
        if self.check_server_available():
            self.show_welcome()
        else:
            self.show_offline_screen()
        
        # Start timeout checker
        self.check_timeout_loop()

    def emergency_reset(self, event=None):
        """Reset everything and return to welcome screen (triggered by ESC key)"""
        # Reset all state
        self.current_user = None
        self.pending_fob = None
        self.pending_fob_mark_available = False
        self.bulk_checkout_mode = False
        self.bulk_items = []
        self.replace_mode = None
        self.replace_item = None
        self.note_mode = False
        self.barns_scan_mode = False
        self.unavailable_mode = False
        self.pending_unavailable_fob = None
        
        # Return to welcome
        self.show_welcome()


    def notify_server(self):
        """Notify server that status changed"""
        try:
            requests.post(
                f'{SERVER_URL}/api/notify',
                auth=(KIOSK_USER, KIOSK_PASS),
                timeout=1,
                verify=True
            )
        except:
            pass  # Fail silently if server unavailable
    
    def check_server_available(self):
        """Check if server is reachable"""
        try:
            response = requests.get(
                f'{SERVER_URL}/api/status',
                auth=(KIOSK_USER, KIOSK_PASS),
                timeout=1,
                verify=False
            )
            return response.status_code == 200
        except:
            return False

    def is_network_error(self, exception):
        """Check if exception is a network/connection error"""
        return isinstance(exception, (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException
        ))

    def register_user_api(self, card_id, first_name, last_name):
        """Register a new user via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/user/register',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'card_id': card_id,
                    'first_name': first_name,
                    'last_name': last_name
                },
                timeout=5,
                verify=False
            )

            if response.status_code == 201:
                data = response.json()
                return True, data['user']  # Return user dict on success
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            return False, str(e)
    
    def register_equipment_api(self, fob_id, vehicle_name, category, location):
        """Register new equipment via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/equipment/register',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id,
                    'vehicle_name': vehicle_name,
                    'category': category,
                    'location': location
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 201:
                data = response.json()
                return True, data['equipment'] # Return equipment dict on success
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)

    def checkout_api(self, user_id, fob_id):
            """Checkout via API"""
            try:
                response = requests.post(
                    f'{SERVER_URL}/api/checkout',
                    auth=(KIOSK_USER, KIOSK_PASS),
                    json={
                        'user_id': user_id,
                        'fob_id': fob_id,
                        'kiosk_id': self.kiosk_id
                    },
                    timeout=5,
                    verify=False
                )
                if response.status_code == 201:
                    return True, None
                else:
                    error_msg = response.json().get('error', 'Unknown error')
                    return False, error_msg
            except Exception as e:
                if self.is_network_error(e):
                    self.show_offline_screen()
                    return False, None
                return False, str(e)
    
    def checkin_api(self, fob_id):
            """Check in via API"""
            try:
                response = requests.post(
                    f'{SERVER_URL}/api/checkin',
                    auth=(KIOSK_USER, KIOSK_PASS),
                    json={
                        'fob_id': fob_id
                    },
                    timeout=5,
                    verify=False
                )
                if response.status_code == 200:
                    return True, None
                else:
                    error_msg = response.json().get('error', 'Unknown error')
                    return False, error_msg
            except Exception as e:
                if self.is_network_error(e):
                    self.show_offline_screen()
                    return False, None
                return False, str(e)


    def mark_unavailable_api(self, fob_id, user_id, reason=''):
        """Mark equipment as unavailable via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/mark_unavailable',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id,
                    'user_id': user_id,
                    'reason': reason
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)

    def mark_available_api(self, fob_id, user_id):
        """Mark equipment as available via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/mark_available',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id,
                    'user_id': user_id
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)

    def bulk_checkout_api(self, user_id, fob_ids):
        """Bulk checkout multiple items via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/bulk_checkout',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'user_id': user_id,
                    'fob_ids': fob_ids,
                    'kiosk_id': self.kiosk_id
                },
                timeout=10
            )
            if response.status_code == 201:
                data = response.json()
                return True, data
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)
    
    def barns_transfer_api(self, fob_id):
        """Transfer to The Barns via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/barns_transfer',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id,
                    'kiosk_id': self.kiosk_id
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)
    
    def replace_card_api(self, user_id, new_card_id):
        """Replace user's card via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/user/replace_card',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'user_id': user_id,
                    'new_card_id': new_card_id
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)
    
    def replace_fob_api(self, equipment_id, new_fob_id):
        """Replace fob ID via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/equipment/replace_fob',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'equipment_id': equipment_id,
                    'new_fob_id': new_fob_id
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)


    def delete_note_api(self, fob_id):
        """Delete note via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/note/delete',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)


    def add_note_api(self, fob_id, note_text, expires_at=None):
        """Add note via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/note/add',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'fob_id': fob_id,
                    'note_text': note_text,
                    'expires_at': expires_at
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 201:
                return True, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)

    def lookup_api(self, lookup_type, identifier):
        """Look up user, fob, or scan via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/lookup',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={
                    'type': lookup_type,
                    'id': identifier
                },
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('found'):
                    return True, data.get('data')
                else:
                    return False, None
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, 'OFFLINE'
            return False, str(e)
    
    def search_users_api(self, search_text):
        """Search users via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/search/users',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={'search': search_text},
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get('users', [])
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)
    
    def search_equipment_api(self, search_text):
        """Search equipment via API"""
        try:
            response = requests.post(
                f'{SERVER_URL}/api/search/equipment',
                auth=(KIOSK_USER, KIOSK_PASS),
                json={'search': search_text},
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get('equipment', [])
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)

    def list_equipment_api(self):
        """List all equipment via API"""
        try:
            response = requests.get(
                f'{SERVER_URL}/api/list/equipment',
                auth=(KIOSK_USER, KIOSK_PASS),
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get('equipment', [])
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, error_msg
        except Exception as e:
            if self.is_network_error(e):
                self.show_offline_screen()
                return False, None
            return False, str(e)



    def get_text_input(self, prompt, title="Input"):
        """Show a dialog to get text input with larger text"""
        from tkinter import simpledialog, font as tkfont
        
        # Create custom dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg='white')
        dialog.geometry("600x300")  # Bigger dialog
        
        # Center it
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Prompt label - bigger text
        prompt_label = tk.Label(
            dialog,
            text=prompt,
            font=tkfont.Font(size=18),
            bg='white',
            wraplength=550,
            justify='left'
        )
        prompt_label.pack(pady=(30, 20))
        
        # Entry field - bigger
        entry_var = tk.StringVar()
        entry = tk.Entry(
            dialog,
            textvariable=entry_var,
            font=tkfont.Font(size=24),
            width=25
        )
        entry.pack(pady=20)
        entry.focus_set()
        
        result = [None]
        
        def on_ok():
            result[0] = entry_var.get()
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        # Buttons - bigger
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        ok_button = tk.Button(
            button_frame,
            text="OK",
            command=on_ok,
            font=tkfont.Font(size=18),
            width=10,
            height=2
        )
        ok_button.pack(side='left', padx=10)
        
        cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            command=on_cancel,
            font=tkfont.Font(size=18),
            width=10,
            height=2
        )
        cancel_button.pack(side='left', padx=10)
        
        # Bind Enter key
        entry.bind('<Return>', lambda e: on_ok())
        
        dialog.wait_window()
        return result[0]

    def start_replace_card_mode(self):
        """Start the process to replace a lost/broken card"""
        # Ask for user's name or old card number
        search = self.get_text_input("Replace Lost Card\n\nEnter your last name or old card number:")
        if not search:
            self.show_welcome()
            return
        
        # Search for user via api
        success, users = self.search_users_api(search)
        
        if not success or not users:
            self.show_error("No users found matching that search")
            return
        
        if len(users) == 1:
            # Found exactly one user
            user = users[0]
            self.replace_mode = 'card'
            self.replace_item = user
            
            # Show instruction to scan new card
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="🔄",
                font=font.Font(size=120),
                fg='#FF9800',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text=f"Replacing card for:\n{user['first_name']} {user['last_name']}",
                font=self.header_font,
                fg='#FF9800',
                bg='black',
                justify='center'
            )
            msg_label.pack(pady=(0, 20))
            
            instruction_label = tk.Label(
                self.message_frame,
                text="Scan your NEW card now",
                font=self.body_font,
                fg='white',
                bg='black'
            )
            instruction_label.pack()
            
            self.instructions_label.config(text="Session will timeout after 60 seconds")
            self.last_scan_time = datetime.now()
        else:
            # Multiple matches - let them choose
            from tkinter import Toplevel, Button, Label
            
            result = [None]
            
            def select_user(u):
                result[0] = u
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("Select User")
            dialog.geometry("600x400")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text="Multiple users found. Select yours:", 
                  font=font.Font(size=18), bg='white').pack(pady=(20, 10))
            
            for user in users:
                btn = Button(dialog, 
                           text=f"{user['first_name']} {user['last_name']} - Card: {user['card_id']}", 
                           command=lambda u=user: select_user(u),
                           font=font.Font(size=16), 
                           width=40, 
                           height=2)
                btn.pack(pady=5)
            
            dialog.wait_window()
            
            if result[0]:
                user = result[0]
                self.replace_mode = 'card'
                self.replace_item = user
                
                # Show instruction to scan new card
                self.clear_message_frame()
                
                icon_label = tk.Label(
                    self.message_frame,
                    text="🔄",
                    font=font.Font(size=120),
                    fg='#FF9800',
                    bg='black'
                )
                icon_label.pack(pady=(50, 30))
                
                msg_label = tk.Label(
                    self.message_frame,
                    text=f"Replacing card for:\n{user['first_name']} {user['last_name']}",
                    font=self.header_font,
                    fg='#FF9800',
                    bg='black',
                    justify='center'
                )
                msg_label.pack(pady=(0, 20))
                
                instruction_label = tk.Label(
                    self.message_frame,
                    text="Scan your NEW card now",
                    font=self.body_font,
                    fg='white',
                    bg='black'
                )
                instruction_label.pack()
                
                self.instructions_label.config(text="Session will timeout after 60 seconds")
                self.last_scan_time = datetime.now()
            else:
                self.show_welcome()

    def start_replace_fob_mode(self):
        """Start the process to replace a lost/broken fob"""
        # Ask for vehicle/equipment name
        search = self.get_text_input("Replace Lost Fob\n\nEnter vehicle or equipment name:")
        if not search:
            self.show_welcome()
            return
        
        # Search for fob via api
        success, fobs = self.search_equipment_api(search)
        
        if not success or not fobs:
            self.show_error("No equipment/vehicles found matching that search")
            return
        
        if len(fobs) == 1:
            # Found exactly one fob
            fob = fobs[0]
            self.replace_mode = 'fob'
            self.replace_item = fob
            
            # Show instruction to scan new fob
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="🔄",
                font=font.Font(size=120),
                fg='#FF9800',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text=f"Replacing fob for:\n{fob['vehicle_name']}",
                font=self.header_font,
                fg='#FF9800',
                bg='black',
                justify='center'
            )
            msg_label.pack(pady=(0, 20))
            
            instruction_label = tk.Label(
                self.message_frame,
                text="Scan the NEW fob now",
                font=self.body_font,
                fg='white',
                bg='black'
            )
            instruction_label.pack()
            
            self.instructions_label.config(text="Session will timeout after 60 seconds")
            self.last_scan_time = datetime.now()
        else:
            # Multiple matches - let them choose
            from tkinter import Toplevel, Button, Label
            
            result = [None]
            
            def select_fob(f):
                result[0] = f
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("Select Equipment/Vehicle")
            dialog.geometry("600x400")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text="Multiple items found. Select one:", 
                  font=font.Font(size=18), bg='white').pack(pady=(20, 10))
            
            for fob in fobs:
                btn = Button(dialog, 
                           text=f"{fob['vehicle_name']} ({fob['category']}) - Fob: {fob['fob_id']}", 
                           command=lambda f=fob: select_fob(f),
                           font=font.Font(size=16), 
                           width=40, 
                           height=2)
                btn.pack(pady=5)
            
            dialog.wait_window()
            
            if result[0]:
                fob = result[0]
                self.replace_mode = 'fob'
                self.replace_item = fob
                
                # Show instruction to scan new fob
                self.clear_message_frame()
                
                icon_label = tk.Label(
                    self.message_frame,
                    text="🔄",
                    font=font.Font(size=120),
                    fg='#FF9800',
                    bg='black'
                )
                icon_label.pack(pady=(50, 30))
                
                msg_label = tk.Label(
                    self.message_frame,
                    text=f"Replacing fob for:\n{fob['vehicle_name']}",
                    font=self.header_font,
                    fg='#FF9800',
                    bg='black',
                    justify='center'
                )
                msg_label.pack(pady=(0, 20))
                
                instruction_label = tk.Label(
                    self.message_frame,
                    text="Scan the NEW fob now",
                    font=self.body_font,
                    fg='white',
                    bg='black'
                )
                instruction_label.pack()
                
                self.instructions_label.config(text="Session will timeout after 60 seconds")
                self.last_scan_time = datetime.now()
            else:
                self.show_welcome()



    def exit_fullscreen(self, event=None):
        """Exit fullscreen mode"""
        self.root.attributes('-fullscreen', False)
        self.root.update_idletasks()
    
    def enter_fullscreen(self, event=None):
        """Enter fullscreen mode"""
        self.root.attributes('-fullscreen', True)
        self.root.update_idletasks()
        # Force a redraw of current screen
        if self.current_user:
            self.show_user_greeting(self.current_user)
        else:
            self.show_welcome()

    def clear_message_frame(self):
        """Clear all widgets from message frame"""
        for widget in self.message_frame.winfo_children():
            widget.destroy()
    
    def show_offline_screen(self):
        """Display offline/connection error screen"""
        self.clear_message_frame()
        
        # Big warning icon
        icon_label = tk.Label(
            self.message_frame,
            text="🚫",
            font=font.Font(size=120),
            fg='#f44336',
            bg='black'
        )
        icon_label.pack(pady=(50, 30))
        
        # Error message
        msg_label = tk.Label(
            self.message_frame,
            text="System Offline",
            font=self.header_font,
            fg='#f44336',
            bg='black'
        )
        msg_label.pack(pady=(0, 20))
        
        # Instructions
        instruction_label = tk.Label(
            self.message_frame,
            text="Cannot connect to server\n\nPlease contact a supervisor",
            font=self.body_font,
            fg='white',
            bg='black',
            justify='center'
        )
        instruction_label.pack(pady=(0, 20))
        
        # Status message
        status_label = tk.Label(
            self.message_frame,
            text="Retrying connection...",
            font=font.Font(size=14),
            fg='#999',
            bg='black'
        )
        status_label.pack()
        
        self.instructions_label.config(text="System will resume automatically when connection is restored")
        
        # Schedule connection retry in 15 seconds
        self.root.after(15000, self.retry_connection)
    
    def retry_connection(self):
        """Try to reconnect to server"""
        if self.check_server_available():
            # Connection restored - return to welcome
            self.show_welcome()
        else:
            # Still offline - show offline screen again (which schedules another retry)
            self.show_offline_screen()
   


    def show_welcome(self):
        """Display welcome screen"""
        self.clear_message_frame()
        self.current_user = None
        self.bulk_checkout_mode = False
        self.bulk_items = []
    
        # Big icon/emoji
        icon_label = tk.Label(
            self.message_frame,
            text="🔑",
            font=font.Font(size=120),
            fg='white',
            bg='black'
        )
        icon_label.pack(pady=(50, 20))
    
        # Main instruction
        msg_label = tk.Label(
            self.message_frame,
            text="Scan your keycard to begin",
            font=self.header_font,
            fg='white',
            bg='black'
        )
        msg_label.pack(pady=(0, 30))
    
        # Button container - First row
        button_frame1 = tk.Frame(self.message_frame, bg='black')
        button_frame1.pack(pady=10)
    
        # Bulk Checkout button (new!)
        bulk_btn = tk.Button(
            button_frame1,
            text="🛒 Bulk Checkout",
            font=font.Font(size=16, weight='bold'),
            bg='#4CAF50',
            fg='white',
            width=18,
            height=2,
            command=self.start_bulk_checkout
        )
        bulk_btn.pack(side='left', padx=10)
    
        # Barns Transfer button
        barns_btn = tk.Button(
            button_frame1,
            text="🔧 Barns Transfer",
            font=font.Font(size=16, weight='bold'),
            bg='#795548',
            fg='white',
            width=18,
            height=2,
            command=self.barns_transfer
        )
        barns_btn.pack(side='left', padx=10)
    
        # Button container - Second row
        button_frame2 = tk.Frame(self.message_frame, bg='black')
        button_frame2.pack(pady=10)
    
        # Add Note button
        note_btn = tk.Button(
            button_frame2,
            text="📝 Add Note",
            font=font.Font(size=16, weight='bold'),
            bg='#2196F3',
            fg='white',
            width=15,
            height=2,
            command=self.add_note
        )
        note_btn.pack(side='left', padx=10)
    
        # Replace Fob button
        fob_btn = tk.Button(
            button_frame2,
            text="🔑 Replace Fob",
            font=font.Font(size=16, weight='bold'),
            bg='#FF9800',
            fg='white',
            width=15,
            height=2,
            command=self.replace_fob
        )
        fob_btn.pack(side='left', padx=10)
    
        # Replace Card button
        card_btn = tk.Button(
            button_frame2,
            text="💳 Replace Card",
            font=font.Font(size=16, weight='bold'),
            bg='#9C27B0',
            fg='white',
            width=15,
            height=2,
            command=self.replace_card
        )
        card_btn.pack(side='left', padx=10)

        # Button container - Third row
        button_frame3 = tk.Frame(self.message_frame, bg='black')
        button_frame3.pack(pady=10)

        # Mark Unavailable button
        unavailable_btn = tk.Button(
            button_frame3,
            text="🚫 Mark Unavailable",
            font=font.Font(size=16, weight='bold'),
            bg='#f44336',
            fg='white',
            width=20,
            height=2,
            command=self.start_mark_unavailable
        )
        unavailable_btn.pack(side='left', padx=10)

        # Instructions
        self.entry.focus_set()
        self.instructions_label.config(text="")
        self.instructions_label.config(text="Press ESC to reset • F11/F12 for fullscreen")
        
    
    def start_bulk_checkout(self):
        """Start bulk checkout mode"""
        self.bulk_checkout_mode = True
        self.bulk_items = []
        self.clear_message_frame()
        
        icon_label = tk.Label(
            self.message_frame,
            text="🛒",
            font=font.Font(size=120),
            fg='#4CAF50',
            bg='black'
        )
        icon_label.pack(pady=(50, 30))
        
        msg_label = tk.Label(
            self.message_frame,
            text="Bulk Checkout Mode\n\nScan your keycard or first item",
            font=self.header_font,
            fg='#4CAF50',
            bg='black',
            justify='center'
        )
        msg_label.pack(pady=(0, 20))
        
        # Cancel button
        cancel_btn = tk.Button(
            self.message_frame,
            text="❌ Cancel",
            font=font.Font(size=16, weight='bold'),
            bg='#f44336',
            fg='white',
            width=15,
            height=2,
            command=self.cancel_bulk_checkout
        )
        cancel_btn.pack(pady=20)
        
        self.instructions_label.config(text="Scan your employee keycard to continue")
        self.last_scan_time = datetime.now()

    def show_bulk_scanning(self):
        """Show bulk scanning screen with item list"""
        self.clear_message_frame()
        
        # Header
        if self.current_user:
            header_text = f"🛒 Bulk Checkout - {self.current_user['first_name']} {self.current_user['last_name']}"
        else:
            header_text = "🛒 Bulk Checkout"

        header_label = tk.Label(
            self.message_frame,
            text=header_text,
            font=font.Font(size=20, weight='bold'),
            fg='#4CAF50',
            bg='black'
        )
        header_label.pack(pady=(20, 10))
        
        if self.current_user:
            instruction_text = f"Scan items for {self.current_user['first_name']} {self.current_user['last_name']}"
        else:
            instruction_text = "Scan items and your keycard"
        instruction_label = tk.Label(
            self.message_frame,
            text=instruction_text,
            font=self.body_font,
            fg='white',
            bg='black'
        )
        instruction_label.pack(pady=(0, 20))
        
        # Scrollable list frame
        list_frame = tk.Frame(self.message_frame, bg='black')
        list_frame.pack(pady=10, fill='both', expand=True)
        
        if self.bulk_items:
            for item in self.bulk_items:
                item_label = tk.Label(
                    list_frame,
                    text=f"✅ {item['vehicle_name']}",
                    font=font.Font(size=16),
                    fg='#4CAF50',
                    bg='black',
                    anchor='w'
                )
                item_label.pack(pady=5, padx=20, fill='x')
        else:
            placeholder_label = tk.Label(
                list_frame,
                text="(No items scanned yet)",
                font=font.Font(size=16),
                fg='#666',
                bg='black'
            )
            placeholder_label.pack(pady=5)
        
        # Button container
        button_frame = tk.Frame(self.message_frame, bg='black')
        button_frame.pack(pady=20)
        
        # Done button
        done_btn = tk.Button(
            button_frame,
            text="✅ Done",
            font=font.Font(size=18, weight='bold'),
            bg='#4CAF50',
            fg='white',
            width=12,
            height=2,
            command=self.complete_bulk_checkout
        )
        done_btn.pack(side='left', padx=10)
        
        # Cancel button
        cancel_btn = tk.Button(
            button_frame,
            text="❌ Cancel",
            font=font.Font(size=18, weight='bold'),
            bg='#f44336',
            fg='white',
            width=12,
            height=2,
            command=self.cancel_bulk_checkout
        )
        cancel_btn.pack(side='left', padx=10)
        
        self.instructions_label.config(text=f"{len(self.bulk_items)} item(s) scanned • Timeout in 60 seconds")

    def add_bulk_item(self, fob):
        """Add item to bulk checkout list"""
        # Check if already in list
        if any(item['id'] == fob['id'] for item in self.bulk_items):
            # Show brief "already scanned" message
            self.clear_message_frame()
            tk.Label(self.message_frame, text="⚠️", font=font.Font(size=80), 
                  fg='#FF9800', bg='black').pack(pady=(50, 20))
            tk.Label(self.message_frame, text=f"{fob['vehicle_name']}\nalready in list!", 
                  font=self.header_font, fg='#FF9800', bg='black', justify='center').pack()
            self.root.after(1500, self.show_bulk_scanning)
            return
        
        # Add to list
        self.bulk_items.append(dict(fob))
        
        # Show brief confirmation
        self.clear_message_frame()
        tk.Label(self.message_frame, text="✅", font=font.Font(size=80), 
              fg='#4CAF50', bg='black').pack(pady=(50, 20))
        tk.Label(self.message_frame, text=f"{fob['vehicle_name']}\nadded!", 
              font=self.header_font, fg='#4CAF50', bg='black', justify='center').pack()
        
        # Return to scanning screen
        self.root.after(1000, self.show_bulk_scanning)
        self.last_scan_time = datetime.now()

    def complete_bulk_checkout(self):
        """Complete bulk checkout and check out all items"""
        if not self.current_user:
            # Stay in bulk checkout, just show message
            self.clear_message_frame()
            
            tk.Label(self.message_frame, text="⚠️", font=font.Font(size=80), 
                  fg='#FF9800', bg='black').pack(pady=(50, 20))
            
            tk.Label(self.message_frame, text="Please scan your keycard", 
                  font=self.header_font, fg='#FF9800', bg='black').pack(pady=(0, 20))
            
            tk.Label(self.message_frame, text=f"You have {len(self.bulk_items)} item(s) ready to check out", 
                  font=self.body_font, fg='white', bg='black').pack()
            
            # Return to bulk scanning screen after 2 seconds
            self.root.after(2000, self.show_bulk_scanning)
            return

        if not self.bulk_items:
            self.show_error("No items to check out")
            return
        
        # Check for reservations
        import pytz
        chicago_tz = pytz.timezone('America/Chicago')
        now = datetime.now(chicago_tz)
        
        reserved_items = []
        for fob in self.bulk_items:
            reservation = fob.get('reservation')
            if reservation:
                reserved_for = ""
                if reservation.get('first_name'):
                    reserved_for = f"{reservation['first_name']} {reservation['last_name']}"
                elif reservation.get('reserved_for_name'):
                    reserved_for = reservation['reserved_for_name']
                
                try:
                    res_dt = datetime.fromisoformat(reservation['reserved_datetime'])
                    formatted_time = res_dt.strftime('%a, %b %d at %I:%M %p')
                except:
                    formatted_time = str(reservation['reserved_datetime'])
                
                reserved_items.append({
                    'fob': fob,
                    'reserved_for': reserved_for,
                    'time': formatted_time,
                    'reason': reservation.get('reason', '')
                })
        
        # If there are reserved items, show warning dialog
        items_to_checkout = self.bulk_items  # Default: checkout everything
        
        if reserved_items:
            from tkinter import Toplevel, Button, Label, Frame
            
            dialog_choice = [None]  # 'all', 'skip', or None
            
            def on_checkout_all():
                dialog_choice[0] = 'all'
                dialog.destroy()
            
            def on_skip_reserved():
                dialog_choice[0] = 'skip'
                dialog.destroy()
            
            def on_cancel():
                dialog_choice[0] = None
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("⚠️ Reserved Items")
            dialog.geometry("800x700")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text="⚠️", font=font.Font(size=60), 
                  bg='white', fg='#FF9800').pack(pady=(20, 10))
            
            Label(dialog, text=f"{len(reserved_items)} Reserved Item(s) in Your List", 
                  font=font.Font(size=22, weight='bold'), bg='white').pack(pady=(0, 20))
            
            # Scrollable list of reserved items
            list_frame = Frame(dialog, bg='white')
            list_frame.pack(pady=10, fill='both', expand=True, padx=30)
            
            for item in reserved_items:
                item_container = Frame(list_frame, bg='#FFF3CD', relief='solid', borderwidth=1)
                item_container.pack(fill='x', pady=5)
                
                Label(item_container, text=f"🔑 {item['fob']['vehicle_name']}", 
                      font=font.Font(size=16, weight='bold'), bg='#FFF3CD', 
                      anchor='w').pack(fill='x', padx=10, pady=(5, 0))
                
                info_text = f"Reserved for: {item['reserved_for']}\nTime: {item['time']}"
                if item['reason']:
                    info_text += f"\nReason: {item['reason']}"
                
                Label(item_container, text=info_text, 
                      font=font.Font(size=13), bg='#FFF3CD', 
                      anchor='w', justify='left').pack(fill='x', padx=10, pady=(0, 5))
            
            Label(dialog, text="What would you like to do?", 
                  font=font.Font(size=18, weight='bold'), bg='white').pack(pady=(10, 15))
            
            button_frame = Frame(dialog, bg='white')
            button_frame.pack(pady=15)
            
            Button(button_frame, text="Check Out All Items", command=on_checkout_all,
                   font=font.Font(size=16), bg='#4CAF50', fg='white',
                   width=20, height=2).pack(side='left', padx=8)
            
            Button(button_frame, text="Skip Reserved Items", command=on_skip_reserved,
                   font=font.Font(size=16), bg='#FF9800', fg='white',
                   width=20, height=2).pack(side='left', padx=8)
            
            Button(button_frame, text="Cancel", command=on_cancel,
                   font=font.Font(size=16), bg='#f44336', fg='white',
                   width=15, height=2).pack(side='left', padx=8)
            
            dialog.wait_window()
            
            if dialog_choice[0] is None:
                # User cancelled
                return
            elif dialog_choice[0] == 'skip':
                # Remove reserved items from checkout list
                reserved_fob_ids = {item['fob']['id'] for item in reserved_items}
                items_to_checkout = [fob for fob in self.bulk_items if fob['id'] not in reserved_fob_ids]
                
                if not items_to_checkout:
                    self.show_error("No items left to check out")
                    return
        
        # Bulk checkout via API
        fob_ids = [fob['id'] for fob in items_to_checkout]
        success, result = self.bulk_checkout_api(self.current_user['id'], fob_ids)

        if not success:
            self.show_error(f"Bulk checkout failed: {result}")
            return
        
        # Get results
        checked_out_fob_ids = result.get('checked_out', [])
        errors = result.get('errors', [])
        
        # Map back to vehicle names
        checked_out_items = [fob['vehicle_name'] for fob in items_to_checkout if fob['id'] in checked_out_fob_ids]
        failed_items = [fob['vehicle_name'] for fob in items_to_checkout if fob['id'] not in checked_out_fob_ids]
        
        skipped_items = []
        if reserved_items and dialog_choice[0] == 'skip':
            skipped_items = [item['fob']['vehicle_name'] for item in reserved_items]
        
        self.notify_server()
        
        # Show success screen
        self.clear_message_frame()
        
        tk.Label(self.message_frame, text="✅", font=font.Font(size=100), 
              fg='#4CAF50', bg='black').pack(pady=(30, 20))
        
        tk.Label(self.message_frame, text=f"Bulk Checkout Complete!", 
              font=self.header_font, fg='#4CAF50', bg='black').pack(pady=(0, 20))
        
        tk.Label(self.message_frame, text=f"{len(checked_out_items)} item(s) checked out", 
              font=self.body_font, fg='white', bg='black').pack()
        
        if checked_out_items:
            items_frame = tk.Frame(self.message_frame, bg='black')
            items_frame.pack(pady=10)
            for item in checked_out_items[:5]:  # Show first 5
                tk.Label(items_frame, text=f"• {item}", font=font.Font(size=14), 
                      fg='white', bg='black').pack()
            if len(checked_out_items) > 5:
                tk.Label(items_frame, text=f"... and {len(checked_out_items) - 5} more", 
                      font=font.Font(size=14), fg='#666', bg='black').pack()
        
        if skipped_items:
            tk.Label(self.message_frame, text=f"⏭️ {len(skipped_items)} reserved item(s) skipped", 
                  font=font.Font(size=14), fg='#FF9800', bg='black').pack(pady=(10, 0))
        
        if failed_items:
            tk.Label(self.message_frame, text=f"⚠️ {len(failed_items)} item(s) failed", 
                  font=font.Font(size=14), fg='#FF9800', bg='black').pack(pady=(10, 0))
        
        # Reset and return to welcome
        self.bulk_checkout_mode = False
        self.bulk_items = []
        self.current_user = None
        self.root.after(4000, self.show_welcome)

    def cancel_bulk_checkout(self):
        """Cancel bulk checkout and return to welcome"""
        self.bulk_checkout_mode = False
        self.bulk_items = []
        self.current_user = None
        self.show_welcome()
    
    def add_note(self):
        """Button handler for adding note"""
        self.start_note_mode()
    
    def replace_fob(self):
        """Button handler for replacing fob"""
        self.start_replace_fob_mode()
    
    def replace_card(self):
        """Button handler for replacing card"""
        self.start_replace_card_mode()

    def start_mark_unavailable(self):
        """Start mark unavailable mode"""
        from tkinter import Toplevel, Button, Label

        # Ask if they have the fob
        result = [None]

        def on_yes():
            result[0] = True
            dialog.destroy()

        def on_no():
            result[0] = False
            dialog.destroy()

        dialog = Toplevel(self.root)
        dialog.title("Mark Unavailable")
        dialog.geometry("700x400")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()

        Label(dialog, text="🚫", font=font.Font(size=80),
              bg='white', fg='#f44336').pack(pady=(30, 20))

        Label(dialog, text="Do you have the equipment with you?",
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(0, 30))

        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)

        Button(button_frame, text="Yes - I'll Scan It", command=on_yes,
               font=font.Font(size=18), bg='#4CAF50', fg='white',
               width=18, height=2).pack(side='left', padx=10)

        Button(button_frame, text="No - Select from List", command=on_no,
               font=font.Font(size=18), bg='#2196F3', fg='white',
               width=20, height=2).pack(side='left', padx=10)

        dialog.wait_window()

        if result[0] is True:
            # Scan mode - first ask for keycard
            self.unavailable_mode = True
            self.clear_message_frame()

            tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                  fg='#f44336', bg='black').pack(pady=(50, 30))

            tk.Label(self.message_frame, text="Mark Unavailable",
                  font=self.header_font, fg='#f44336', bg='black').pack(pady=(0, 20))

            tk.Label(self.message_frame, text="Scan your keycard first",
                  font=self.body_font, fg='white', bg='black').pack()

            self.last_scan_time = datetime.now()

        elif result[0] is False:
            self.show_equipment_list_for_unavailable()
        else:
            self.show_welcome()

    def show_equipment_list_for_unavailable(self):
        """Show list of equipment to select for marking unavailable"""
        from tkinter import Toplevel, Button, Label, Listbox, Scrollbar, SINGLE

        success, all_items = self.list_equipment_api()

        if not success or not all_items:
            self.show_error("No equipment found")
            return

        result = [None]

        def on_select():
            selection = listbox.curselection()
            if selection and selection[0] in item_indices:
                actual_index = item_indices[selection[0]]
                result[0] = all_items[actual_index]
                dialog.destroy()

        dialog = Toplevel(self.root)
        dialog.title("Mark Unavailable - Select Equipment")
        dialog.geometry("900x850")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()

        Label(dialog, text="🚫 Mark Equipment Unavailable",
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(20, 10))

        Label(dialog, text="Select the equipment:",
              font=font.Font(size=14), bg='white').pack(pady=(0, 20))

        list_frame = tk.Frame(dialog, bg='white')
        list_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))

        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        listbox = Listbox(list_frame, font=font.Font(size=14), height=25,
                         yscrollcommand=scrollbar.set, selectmode=SINGLE)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)

        item_indices = {}
        listbox_index = 0
        current_category = None

        for i, item in enumerate(all_items):
            if item['category'] != current_category:
                current_category = item['category']
                listbox.insert('end', f"--- {current_category} ---")
                listbox.itemconfig(listbox_index, {'bg': '#E0E0E0', 'fg': '#666'})
                listbox_index += 1
            listbox.insert('end', f"  {item['vehicle_name']}")
            item_indices[listbox_index] = i
            listbox_index += 1

        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)

        Button(button_frame, text="Mark Unavailable", command=on_select,
               font=font.Font(size=16), bg='#f44336', fg='white',
               width=18, height=2).pack(side='left', padx=10)

        Button(button_frame, text="Cancel", command=dialog.destroy,
               font=font.Font(size=16), bg='#999', fg='white',
               width=12, height=2).pack(side='left', padx=10)

        dialog.wait_window()

        if result[0]:
            # Need keycard first - store selected fob and prompt for card
            self.pending_unavailable_fob = result[0]
            self.unavailable_mode = True
            self.clear_message_frame()

            tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                  fg='#f44336', bg='black').pack(pady=(50, 30))

            tk.Label(self.message_frame, text=f"Marking {result[0]['vehicle_name']} Unavailable",
                  font=self.header_font, fg='#f44336', bg='black', justify='center').pack(pady=(0, 20))

            tk.Label(self.message_frame, text="Scan your keycard to confirm",
                  font=self.body_font, fg='white', bg='black').pack()

            self.last_scan_time = datetime.now()
        else:
            self.show_welcome()

    def complete_mark_unavailable(self, fob, user):
        """Complete the mark unavailable process"""
        # Ask for reason
        reason = self.get_text_input("Reason for marking unavailable\n(e.g., 'MDC issue - reported to I.S.')")
        self.last_scan_time = datetime.now()

        # Include who marked it unavailable
        full_reason = f"{reason} (marked by {user['first_name']} {user['last_name']})" if reason else f"Marked by {user['first_name']} {user['last_name']}"
        success, error = self.mark_unavailable_api(fob['id'], user['id'], full_reason)

        if not success:
            self.show_error(f"Failed to mark unavailable: {error}")
            return

        self.notify_server()
        self.unavailable_mode = False
        self.pending_unavailable_fob = None
        self.current_user = None

        self.clear_message_frame()
        tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
              fg='#f44336', bg='black').pack(pady=(50, 30))
        tk.Label(self.message_frame, text=f"{fob['vehicle_name']}\nmarked unavailable",
              font=self.header_font, fg='#f44336', bg='black', justify='center').pack()

        self.root.after(3000, self.show_welcome)

    def barns_transfer(self):
        """Transfer vehicle to The Barns"""
        from tkinter import Toplevel, Button, Label, Listbox, Scrollbar, SINGLE
        
        # Ask if they have the fob
        result = [None]
        
        def on_yes():
            result[0] = True
            dialog.destroy()
        
        def on_no():
            result[0] = False
            dialog.destroy()
        
        dialog = Toplevel(self.root)
        dialog.title("Barns Transfer")
        dialog.geometry("700x400")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()
        
        Label(dialog, text="🏭", font=font.Font(size=80),
              bg='white', fg='#795548').pack(pady=(30, 20))
        
        Label(dialog, text="Do you have the vehicle fob with you?", 
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(0, 30))
        
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Yes - I'll Scan It", command=on_yes,
               font=font.Font(size=18), bg='#4CAF50', fg='white',
               width=18, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="No - Select from List", command=on_no,
               font=font.Font(size=18), bg='#2196F3', fg='white',
               width=20, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if result[0] is True:
            # They have the fob - show scan prompt
            self.barns_scan_mode = True
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="🏭",
                font=font.Font(size=120),
                fg='#795548',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text="Barns Transfer",
                font=self.header_font,
                fg='#795548',
                bg='black'
            )
            msg_label.pack(pady=(0, 20))
            
            instructions_label = tk.Label(
                self.message_frame,
                text="Scan vehicle fob to transfer to Barns",
                font=self.body_font,
                fg='white',
                bg='black'
            )
            instructions_label.pack()
            
            self.last_scan_time = datetime.now()
            return
            
        elif result[0] is False:
            # Continue with list selection (existing code below)
            pass
        else:
            # Cancelled
            self.show_welcome()
            return
        
        # Get all vehicles via API
        success, all_equipment = self.list_equipment_api()
        
        if not success:
            self.show_error(f"Failed to load vehicles: {all_equipment}")
            return
        
        # Filter to just vehicles (not equipment)
        vehicles = [item for item in all_equipment 
                   if item.get('category') in ('Squad Cars', 'Specialized Services Vehicles', 'CID Vehicles', 'Other Vehicles')]
        
        if not vehicles:
            self.show_error("No vehicles found")
            return
        
        # Create selection dialog
        result = [None]
        
        def on_select():
            selection = listbox.curselection()
            if selection:
                result[0] = vehicles[selection[0]]
                dialog.destroy()
        
        dialog = Toplevel(self.root)
        dialog.title("Barns Transfer - Select Vehicle")
        dialog.geometry("800x800")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()
        
        Label(dialog, text="🏭 Transfer Vehicle to The Barns", 
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(20, 10))
        
        Label(dialog, text="Select the vehicle being dropped off:", 
              font=font.Font(size=14), bg='white').pack(pady=(0, 20))
        
        # Listbox with scrollbar
        list_frame = tk.Frame(dialog, bg='white')
        list_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        listbox = Listbox(list_frame, font=font.Font(size=14), height=20, 
                         yscrollcommand=scrollbar.set, selectmode=SINGLE)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)
        
        # Populate list
        for v in vehicles:
            status = "Available" if not v['checkout_id'] else f"Checked out to {v['first_name']} {v['last_name']}"
            listbox.insert('end', f"{v['vehicle_name']} - {status}")
        
        # Buttons
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Transfer to Barns", command=on_select,
               font=font.Font(size=16), bg='#795548', fg='white',
               width=18, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="Cancel", command=dialog.destroy,
               font=font.Font(size=16), bg='#999', fg='white',
               width=12, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if not result[0]:
            return
        
        vehicle = result[0]
        
        # Perform transfer
        self.perform_barns_transfer(vehicle)


    def perform_barns_transfer(self, vehicle):
        """Actually perform the barns transfer for a given vehicle"""
        from tkinter import Label
        
        # Transfer via API
        success, error = self.barns_transfer_api(vehicle['id'])
        
        if not success:
            self.show_error(f"Transfer failed: {error}")
            return
        
        self.notify_server()
        
        # Show success
        self.clear_message_frame()
        
        Label(self.message_frame, text="✅", font=font.Font(size=120),
              fg='#4CAF50', bg='black').pack(pady=(50, 30))
        
        Label(self.message_frame, 
              text=f"{vehicle['vehicle_name']}\ntransferred to The Barns",
              font=self.header_font, fg='white', bg='black',
              justify='center').pack()
        
        self.root.after(3000, self.show_welcome)


    def show_user_greeting(self, user):
        """Show greeting after card scan"""
        self.clear_message_frame()
        
        # Greeting
        greeting_label = tk.Label(
            self.message_frame,
            text=f"👋 Hello, {user['first_name']} {user['last_name']}!",
            font=self.header_font,
            fg='#4CAF50',
            bg='black'
        )
        greeting_label.pack(pady=(100, 50))
        
        # Next step
        instruction_label = tk.Label(
            self.message_frame,
            text="Now scan the key fob you want",
            font=self.body_font,
            fg='white',
            bg='black'
        )
        instruction_label.pack()
        
        self.instructions_label.config(
            text="Session will timeout after 60 seconds of inactivity"
        )
    
    def show_checkout_success(self, vehicle_name, category='Vehicle'):
        """Show successful checkout"""
        self.clear_message_frame()
        
        # Success icon
        icon_label = tk.Label(
            self.message_frame,
            text="✅",
            font=font.Font(size=120),
            fg='#4CAF50',
            bg='black'
        )
        icon_label.pack(pady=(50, 30))
        
        # Message
        msg_label = tk.Label(
            self.message_frame,
            text=f"{vehicle_name} checked out!",
            font=self.header_font,
            fg='#4CAF50',
            bg='black'
        )
        msg_label.pack(pady=(0, 20))
        
        # Reminder
        reminder_text = "Return keys to the proper hook when done" if category == 'Vehicle' else "Return equipment to proper location when done"
        reminder_label = tk.Label(
            self.message_frame,
            text=reminder_text,
            font=self.body_font,
            fg='white',
            bg='black'
        )
        reminder_label.pack()
        
        self.instructions_label.config(text="")
        
        # Return to welcome after 3 seconds
        self.root.after(3000, self.show_welcome)
    
    def show_checkin_success(self, vehicle_name, was_with=None):
        """Show successful check-in"""
        self.clear_message_frame()
        
        # Success icon
        icon_label = tk.Label(
            self.message_frame,
            text="✅",
            font=font.Font(size=120),
            fg='#4CAF50',
            bg='black'
        )
        icon_label.pack(pady=(50, 30))
        
        # Message
        msg_text = f"{vehicle_name} returned"
        if was_with:
            msg_text += f"\n(was with {was_with})"
        
        msg_label = tk.Label(
            self.message_frame,
            text=msg_text,
            font=self.header_font,
            fg='#4CAF50',
            bg='black',
            justify='center'
        )
        msg_label.pack()
        
        self.instructions_label.config(text="")
        
        # Return to welcome after 3 seconds
        self.root.after(3000, self.show_welcome)
    
    def show_error(self, message):
        """Show error message"""
        self.clear_message_frame()
        
        # Error icon
        icon_label = tk.Label(
            self.message_frame,
            text="❌",
            font=font.Font(size=120),
            fg='#f44336',
            bg='black'
        )
        icon_label.pack(pady=(50, 30))
        
        # Message
        msg_label = tk.Label(
            self.message_frame,
            text=message,
            font=self.body_font,
            fg='#f44336',
            bg='black',
            wraplength=800,
            justify='center'
        )
        msg_label.pack()
        
        self.instructions_label.config(text="")
        
        # Return to welcome after 3 seconds
        self.root.after(3000, self.show_welcome)
    
    def on_key_press(self, event):
        """Handle keyboard input"""
        # Handle F11 and Escape for fullscreen
        if event.keysym == 'F11':
            self.toggle_fullscreen()
            return
        elif event.keysym == 'Escape':
            self.exit_fullscreen()
            return
        
        # Handle Enter key - process scan
        if event.char == '\r' or event.char == '\n':
            # Process the scan buffer
            scan_data = self.scan_buffer.strip()
            self.scan_buffer = ""
            
            if scan_data:
                self.process_scan(scan_data)
        elif event.char.isprintable():
            # Add to buffer
            self.scan_buffer += event.char
    def process_scan(self, scan_data):
        """Process a scanned card or fob"""
        # Check if we're in replace mode - bypass lookup for new card/fob
        if self.replace_mode == 'card':
            self.handle_card_scan(scan_data)
            return
        elif self.replace_mode == 'fob':
            self.handle_fob_scan(scan_data)
            return


        # Look up via API
        found, data = self.lookup_api('scan', scan_data)
        # If we went offline, stop processing
        if data == 'OFFLINE':
            return
        
        if found and data:
            # API returns type in the response, but let's check the data structure
            if 'first_name' in data:  # It's a user
                self.handle_card_scan(scan_data)
            else:  # It's a fob
                self.handle_fob_scan(scan_data)
        else:
            # Ask if card or equipment with custom larger dialog
            from tkinter import Toplevel, Button, Label
            
            result = [None]
            
            def on_keycard():
                result[0] = True
                dialog.destroy()
            
            def on_equipment():
                result[0] = False
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("Unknown Scan")
            dialog.geometry("600x350")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text=f"ID: {scan_data}", 
                  font=font.Font(size=16), bg='white').pack(pady=(30, 10))
            
            Label(dialog, text="Is this an employee keycard or equipment?", 
                  font=font.Font(size=18), bg='white', wraplength=550).pack(pady=(10, 30))
            
            Button(dialog, text="Employee Keycard", command=on_keycard, 
                   font=font.Font(size=18), width=20, height=2).pack(pady=10)
            Button(dialog, text="Equipment", command=on_equipment, 
                   font=font.Font(size=18), width=20, height=2).pack(pady=10)
            
            dialog.wait_window()
            is_card = result[0] if result[0] is not None else True
            
            if is_card:
                self.handle_card_scan(scan_data)
            else:
                self.handle_fob_scan(scan_data)

    
    def handle_card_scan(self, card_id):
        """Handle a card scan"""
        
        # Check if in unavailable mode - need keycard to confirm
        if self.unavailable_mode and not self.current_user:
            found, user = self.lookup_api('user', card_id)
            if not found or not user:
                self.show_error("Unknown card. Please register at the admin panel.")
                return
            self.current_user = user
            
            # If we already have a fob selected (from list), complete it
            if self.pending_unavailable_fob:
                self.complete_mark_unavailable(self.pending_unavailable_fob, user)
            else:
                # Waiting for fob scan
                self.clear_message_frame()
                tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                      fg='#f44336', bg='black').pack(pady=(50, 30))
                tk.Label(self.message_frame, text=f"Hello {user['first_name']}!\nNow scan the item to mark unavailable",
                      font=self.header_font, fg='#f44336', bg='black', justify='center').pack(pady=(0, 20))
                self.last_scan_time = datetime.now()
            return

        # Check if in bulk checkout mode
        if self.bulk_checkout_mode and not self.current_user:
            # Look up user via API
            found, user = self.lookup_api('user', card_id)

            if not found or not user:
                self.show_error("Unknown card. Please register at the admin panel.")
                return

            self.current_user = user
            self.show_bulk_scanning()
            return

        # Check if we're in replace mode
        if self.replace_mode == 'card' and self.replace_item:
            # This is the NEW card being scanned
            # Check if new card already exists via API
            found, existing = self.lookup_api('user', card_id)
            if found and existing:
                self.replace_mode = None
                self.replace_item = None
                self.show_error("This card is already registered to someone else")
                return
            
            # Replace card via API
            success, error = self.replace_card_api(self.replace_item['id'], card_id)
            
            if not success:
                self.replace_mode = None
                self.replace_item = None
                self.show_error(f"Card replacement failed: {error}")
                return
            
            # Show success
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="✅",
                font=font.Font(size=120),
                fg='#4CAF50',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text="Card replaced successfully!",
                font=self.header_font,
                fg='#4CAF50',
                bg='black'
            )
            msg_label.pack(pady=(0, 20))
            
            detail_label = tk.Label(
                self.message_frame,
                text=f"{self.replace_item['first_name']} {self.replace_item['last_name']}\nNew card registered",
                font=self.body_font,
                fg='white',
                bg='black',
                justify='center'
            )
            detail_label.pack()
            
            self.instructions_label.config(text="")
            self.replace_mode = None
            self.replace_item = None
            
            # Return to welcome after 3 seconds
            self.root.after(3000, self.show_welcome)
            return

        # Check if there's a pending fob to check out
        if hasattr(self, 'pending_fob') and self.pending_fob:
            # Check if we're marking available + checkout
            if self.pending_fob_mark_available:
                found, user = self.lookup_api('user', card_id)
                if not found or not user:
                    self.show_error("Unknown card. Please register at the admin panel.")
                    return
                # Mark available first
                success, error = self.mark_available_api(self.pending_fob['id'], user['id'])
                if not success:
                    self.show_error(f"Failed to mark available: {error}")
                    return
                # Then check out
                success, error = self.checkout_api(user['id'], self.pending_fob['id'])
                if not success:
                    self.show_error(f"Checkout failed: {error}")
                    return
                self.notify_server()
                fob_name = self.pending_fob['vehicle_name']
                fob_category = self.pending_fob['category']
                self.pending_fob = None
                self.pending_fob_mark_available = False
                self.current_user = None
                self.show_checkout_success(fob_name, fob_category)
                return

            # Look up user via API
            found, user = self.lookup_api('user', card_id)
            if not found or not user:
                # New user - register them first
                first_name = self.get_text_input("First time? Enter your first name:")
                if not first_name:
                    self.pending_fob = None
                    self.show_error("Registration cancelled")
                    return
                
                last_name = self.get_text_input("Enter your last name:")
                if not last_name:
                    self.pending_fob = None
                    self.show_error("Registration cancelled")
                    return
                
                # Register user via API
                success, error_or_response = self.register_user_api(card_id, first_name.strip().title(), last_name.strip().title())
                if not success:
                    self.pending_fob = None
                    self.show_error(f"Error registering user: {error_or_response}")
                    return
                
                # User data returned from API - no DB query needed!
                user = error_or_response  # This is actually the response when success=True
            
            # Check if the pending fob has a reservation
            if self.pending_fob.get('reservation'):
                reservation = self.pending_fob['reservation']
                reserved_for = ""
                if reservation.get('first_name'):
                    reserved_for = f"{reservation['first_name']} {reservation['last_name']}"
                elif reservation.get('reserved_for_name'):
                    reserved_for = reservation['reserved_for_name']
                
                # Format the reservation datetime
                try:
                    res_dt = datetime.fromisoformat(reservation['reserved_datetime'])
                    formatted_time = res_dt.strftime('%a, %b %d at %I:%M %p')
                except:
                    formatted_time = str(reservation['reserved_datetime'])
                
                # Show warning dialog
                from tkinter import Toplevel, Button, Label
                
                result = [None]
                
                def on_yes():
                    result[0] = True
                    dialog.destroy()
                
                def on_no():
                    result[0] = False
                    dialog.destroy()
                
                dialog = Toplevel(self.root)
                dialog.title("⚠️ Reserved Item")
                dialog.geometry("700x600")
                dialog.configure(bg='white')
                dialog.transient(self.root)
                dialog.grab_set()
                
                Label(dialog, text="⚠️", font=font.Font(size=80), 
                      bg='white', fg='#FF9800').pack(pady=(30, 20))
                
                Label(dialog, text=f"{self.pending_fob['vehicle_name']} is RESERVED", 
                      font=font.Font(size=24, weight='bold'), bg='white').pack(pady=(0, 20))
                
                info_text = f"Reserved For: {reserved_for}\nTime: {formatted_time}"
                if reservation.get('reason'):
                    info_text += f"\n\nReason: {reservation['reason']}"
                
                Label(dialog, text=info_text, 
                      font=font.Font(size=18), bg='white', 
                      wraplength=600, justify='center').pack(pady=(0, 30))
                
                Label(dialog, text="Do you want to check it out anyway?", 
                      font=font.Font(size=20), bg='white').pack(pady=(0, 20))
                
                button_frame = tk.Frame(dialog, bg='white')
                button_frame.pack(pady=20)
                
                Button(button_frame, text="Yes, Check Out", command=on_yes,
                       font=font.Font(size=18), bg='#4CAF50', fg='white',
                       width=16, height=2).pack(side='left', padx=10)
                
                Button(button_frame, text="No, Cancel", command=on_no,
                       font=font.Font(size=18), bg='#f44336', fg='white',
                       width=16, height=2).pack(side='left', padx=10)
                
                dialog.wait_window()
                
                if not result[0]:
                    self.pending_fob = None
                    self.show_welcome()
                    return

            # Check out the pending fob via API
            success, error = self.checkout_api(user['id'], self.pending_fob['id'])
            if not success:
                self.pending_fob = None
                self.show_error(f"Checkout failed: {error}")
                return
            
            self.notify_server()
            
            self.show_checkout_success(self.pending_fob['vehicle_name'], self.pending_fob['category'])
            self.pending_fob = None
            self.current_user = None
            return

            

        # Look up user via API
        found, user = self.lookup_api('user', card_id)
        
        if not found or not user:
            # New user - register them
            first_name = self.get_text_input("First time? Enter your first name:")
            self.last_scan_time = datetime.now()  # Reset timeout
            if not first_name:
                self.show_error("Registration cancelled")
                return
            
            last_name = self.get_text_input("Enter your last name:")
            self.last_scan_time = datetime.now()  # Reset timeout
            if not last_name:
                self.show_error("Registration cancelled")
                return
            
            # Register the user
            # Register user via API
            success, result = self.register_user_api(card_id, first_name.strip().title(), last_name.strip().title())
            if not success:
                self.show_error(f"Error registering user: {result}")
                return
            
            # User data returned from API
            user = result
        self.current_user = user
        self.last_scan_time = datetime.now()
        self.show_user_greeting(user)


    def handle_fob_scan(self, fob_id):
        """Handle a fob scan"""
        
        # Check if in unavailable mode - fob scan to mark unavailable
        if self.unavailable_mode:
            found, fob = self.lookup_api('fob', fob_id)
            if not found or not fob:
                self.show_error("Unknown fob")
                return
            if self.current_user:
                # Card already scanned, complete it
                self.complete_mark_unavailable(fob, self.current_user)
            else:
                # Card not scanned yet - store fob and prompt for card
                self.pending_unavailable_fob = fob
                self.clear_message_frame()
                tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                      fg='#f44336', bg='black').pack(pady=(50, 30))
                tk.Label(self.message_frame, text=f"{fob['vehicle_name']}\nScan your keycard to confirm",
                      font=self.header_font, fg='#f44336', bg='black', justify='center').pack(pady=(0, 20))
                self.last_scan_time = datetime.now()
            return
        
        # Check if in note mode
        if self.note_mode:

            found, fob = self.lookup_api('fob', fob_id)
            
            if not found or not fob:
                self.show_welcome()
                return
            
            self.show_note_input(fob)
            return

        # Check if we're in fob replace mode
        if self.replace_mode == 'fob' and self.replace_item:
            # This is the NEW fob being scanned
            # Check if new fob already exists via API
            found, existing = self.lookup_api('fob', fob_id)
            if found and existing:
                self.replace_mode = None
                self.replace_item = None
                self.show_error("This fob is already registered to another item")
                return
            
            # Replace fob via API
            success, error = self.replace_fob_api(self.replace_item['id'], fob_id)
            
            if not success:
                self.replace_mode = None
                self.replace_item = None
                self.show_error(f"Fob replacement failed: {error}")
                return
            
            # Show success
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="✅",
                font=font.Font(size=120),
                fg='#4CAF50',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text="Fob replaced successfully!",
                font=self.header_font,
                fg='#4CAF50',
                bg='black'
            )
            msg_label.pack(pady=(0, 20))
            
            detail_label = tk.Label(
                self.message_frame,
                text=f"{self.replace_item['vehicle_name']}\nNew fob registered",
                font=self.body_font,
                fg='white',
                bg='black',
                justify='center'
            )
            detail_label.pack()
            
            self.instructions_label.config(text="")
            self.replace_mode = None
            self.replace_item = None
            
            # Return to welcome after 3 seconds
            self.root.after(3000, self.show_welcome)
            return


        # Check if in bulk checkout mode
        if self.bulk_checkout_mode:
            found, fob = self.lookup_api('fob', fob_id)
            if found and fob:
                self.add_bulk_item(fob)
            else:
                self.show_error("Unknown fob")
            return
            if fob:
                self.add_bulk_item(dict(fob))
            else:
                self.show_error("Unknown fob")
            return

        # Check if in Barns scan mode
        if self.barns_scan_mode:
            found, fob = self.lookup_api('fob', fob_id)
            if not found or not fob:
                self.show_error("Equipment not found")
                return
            
            # Perform barns transfer with this fob
            self.barns_scan_mode = False
            self.perform_barns_transfer(fob)
            return
        
        # Look up fob via API
        found, fob = self.lookup_api('fob', fob_id)
        
        if not found or not fob:
            # New fob - register it
            
            vehicle_name = self.get_text_input("New Key Fob! What is this for?\n(e.g., 'Squad 91', 'Thermal 2')")
            self.last_scan_time = datetime.now() # reset timeout
            if not vehicle_name:
                self.show_error("Registration cancelled")
                return
            
        # Ask for category with dropdown
            from tkinter import Toplevel, Button, Label, ttk
            
            result = [None]
            
            def on_submit():
                result[0] = category_var.get()
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("Category")
            dialog.geometry("600x350")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text="What category is this equipment?", 
                  font=font.Font(size=18), bg='white', wraplength=550).pack(pady=(40, 20))
            
            # Dropdown for category
            category_var = tk.StringVar(value="Squad Cars")
            categories = ["Squad Cars", "Specialized Services Vehicles", "CID Vehicles", "Other Vehicles", "Pool Cars", "Admin Cars", "Equipment", "Key Rings"]
            
            dropdown = ttk.Combobox(dialog, textvariable=category_var, values=categories, 
                                   font=font.Font(size=16), state='readonly', width=20)
            dropdown.pack(pady=20)
            
            Button(dialog, text="Continue", command=on_submit, 
                   font=font.Font(size=18), bg='#4CAF50', fg='white',
                   width=15, height=2).pack(pady=20)
            
            dialog.wait_window()
            category = result[0] if result[0] else "Squad Cars"
            self.last_scan_time = datetime.now()  # Reset timeout
            
            location = self.get_text_input("Location (press OK for 'Station'):", title="Location") or "Station"
            self.last_scan_time = datetime.now()  # Reset timeout


            # Register the equipment via API
            success, result = self.register_equipment_api(fob_id, vehicle_name.strip(), category, location.strip())
            if not success:
                self.show_error(f"Error registering equipment: {result}")
                return
            
            # Equipment data returned from API
            fob = result
            self.notify_server()
   
            # If user already scanned card, check out the new fob immediately
            if self.current_user:
                # Checkout via API
                success, error = self.checkout_api(self.current_user['id'], fob['id'])
                if not success:
                    self.show_error(f"Checkout failed: {error}")
                    return
                
                self.notify_server()
                self.show_checkout_success(fob['vehicle_name'], fob['category'])
                    
                return
            else:
                # No user scanned yet - show success and prompt
                    self.clear_message_frame()
                    
                    icon_label = tk.Label(
                        self.message_frame,
                        text="✅",
                        font=font.Font(size=120),
                        fg='#4CAF50',
                        bg='black'
                    )
                    icon_label.pack(pady=(50, 30))
                    
                    msg_label = tk.Label(
                        self.message_frame,
                        text=f"✅ {vehicle_name} registered!",
                        font=self.header_font,
                        fg='#4CAF50',
                        bg='black'
                    )
                    msg_label.pack(pady=(0, 20))
                    
                    instruction_label = tk.Label(
                        self.message_frame,
                        text="Scan your keycard to check it out",
                        font=self.body_font,
                        fg='white',
                        bg='black'
                    )
                    instruction_label.pack()
                    
                    self.instructions_label.config(text="")
                    
                    # Return to welcome after 3 seconds
                    self.root.after(3000, self.show_welcome)
                    return
                    
        
        # Check if it's currently checked out (lookup API already includes this info)
        checkout = None
        if fob.get('checkout_id'):
            # Fob is checked out - create checkout dict from fob data
            checkout = {
                'id': fob['checkout_id'],
                'user_id': fob.get('user_id'),
                'first_name': fob.get('first_name'),
                'last_name': fob.get('last_name')
            }
        
        if checkout:
            # Check if there's a different user trying to take it
            if self.current_user and self.current_user['id'] != checkout['user_id']:
                # Handoff: check in from previous user, check out to new user
                # First check in
                success, error = self.checkin_api(fob['fob_id'])
                if not success:
                    self.show_error(f"Check-in failed: {error}")
                    return
                
                # Then check out to new user
                success, error = self.checkout_api(self.current_user['id'], fob['id'])
                if not success:
                    self.show_error(f"Checkout failed: {error}")
                    return
                
                self.notify_server()
                
                self.clear_message_frame()
                
                icon_label = tk.Label(
                    self.message_frame,
                    text="🔄",
                    font=font.Font(size=120),
                    fg='#FFA500',
                    bg='black'
                )
                icon_label.pack(pady=(50, 30))
                
                was_with = f"{checkout['first_name']} {checkout['last_name']}"
                msg_label = tk.Label(
                    self.message_frame,
                    text=f"{fob['vehicle_name']} transferred",
                    font=self.header_font,
                    fg='#FFA500',
                    bg='black'
                )
                msg_label.pack(pady=(0, 20))
                
                detail_label = tk.Label(
                    self.message_frame,
                    text=f"From: {was_with}\nTo: {self.current_user['first_name']} {self.current_user['last_name']}",
                    font=self.body_font,
                    fg='white',
                    bg='black',
                    justify='center'
                )
                detail_label.pack()
                
                self.instructions_label.config(text="")
                self.current_user = None
                
                # Return to welcome after 3 seconds
                self.root.after(3000, self.show_welcome)
            else:
                # Check in via API
                success, error = self.checkin_api(fob['fob_id'])
                if not success:
                    self.show_error(f"Check-in failed: {error}")
                    return
                
                self.notify_server()
                
                was_with = f"{checkout['first_name']} {checkout['last_name']}"
                self.show_checkin_success(fob['vehicle_name'], was_with)
                self.current_user = None

        else:
            # Check it out
            if self.current_user:
                # Check if item is unavailable
                if fob.get('is_available') == 0:
                    self.clear_message_frame()
                    
                    tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                          fg='#9E9E9E', bg='black').pack(pady=(30, 10))
                    
                    tk.Label(self.message_frame, text=f"{fob['vehicle_name']} is UNAVAILABLE",
                          font=self.header_font, fg='#9E9E9E', bg='black').pack(pady=(0, 10))
                    
                    if fob.get('note') and fob['note'].get('note_text'):
                        tk.Label(self.message_frame, text=fob['note']['note_text'],
                              font=self.body_font, fg='#FF9800', bg='black',
                              wraplength=800, justify='center').pack(pady=(0, 20))
                    
                    tk.Label(self.message_frame, text="This item has been marked unavailable.",
                          font=self.body_font, fg='white', bg='black').pack(pady=(0, 20))
                    
                    button_frame = tk.Frame(self.message_frame, bg='black')
                    button_frame.pack(pady=10)
                    
                    def on_mark_available_with_user():
                        self.pending_fob = fob
                        self.pending_fob_mark_available = True
                        # User already scanned - complete immediately
                        success, error = self.mark_available_api(fob['id'], self.current_user['id'])
                        if not success:
                            self.show_error(f"Failed to mark available: {error}")
                            return
                        success, error = self.checkout_api(self.current_user['id'], fob['id'])
                        if not success:
                            self.show_error(f"Checkout failed: {error}")
                            return
                        self.notify_server()
                        self.pending_fob = None
                        self.pending_fob_mark_available = False
                        current = self.current_user
                        self.current_user = None
                        self.show_checkout_success(fob['vehicle_name'], fob['category'])
                    
                    def on_cancel_unavailable():
                        self.current_user = None
                        self.show_welcome()
                    
                    tk.Button(button_frame, text="✅ Mark Available & Check Out",
                          font=font.Font(size=16, weight='bold'),
                          bg='#4CAF50', fg='white', width=28, height=2,
                          command=on_mark_available_with_user).pack(side='left', padx=10)
                    
                    tk.Button(button_frame, text="❌ Cancel",
                          font=font.Font(size=16, weight='bold'),
                          bg='#f44336', fg='white', width=12, height=2,
                          command=on_cancel_unavailable).pack(side='left', padx=10)
                    
                    self.instructions_label.config(text="Session will timeout after 60 seconds")
                    self.last_scan_time = datetime.now()
                    return

                # Check if reserved - use Python datetime for proper timezone handling
                from tkinter import messagebox
                
                chicago_tz = pytz.timezone('America/Chicago')
                now = datetime.now(chicago_tz)
                
                # Get reservation from fob data (already included from API lookup)
                reservation = fob.get('reservation')
                
                if reservation:
                    reserved_for = ""
                    if reservation['first_name']:
                        reserved_for = f"{reservation['first_name']} {reservation['last_name']}"
                    elif reservation['reserved_for_name']:
                        reserved_for = reservation['reserved_for_name']
                    
                    # Format the reservation datetime nicely
                    try:
                        res_dt = datetime.fromisoformat(reservation['reserved_datetime'])
                        formatted_time = res_dt.strftime('%a, %b %d at %I:%M %p')
                    except:
                        formatted_time = str(reservation['reserved_datetime'])
                    
                    # Custom larger warning dialog
                    from tkinter import Toplevel, Button, Label
                    
                    result = [None]
                    
                    def on_yes():
                        result[0] = True
                        dialog.destroy()
                    
                    def on_no():
                        result[0] = False
                        dialog.destroy()
                    
                    dialog = Toplevel(self.root)
                    dialog.title("⚠️ Reserved Item")
                    dialog.geometry("700x600")
                    dialog.configure(bg='white')
                    dialog.transient(self.root)
                    dialog.grab_set()
                    
                    Label(dialog, text="⚠️", font=font.Font(size=80), 
                          bg='white', fg='#FF9800').pack(pady=(30, 20))
                    
                    Label(dialog, text=f"{fob['vehicle_name']} is RESERVED", 
                          font=font.Font(size=24, weight='bold'), bg='white').pack(pady=(0, 20))
                    
                    info_text = f"Reserved For: {reserved_for}\nTime: {formatted_time}"
                    if reservation['reason']:
                        info_text += f"\n\nReason: {reservation['reason']}"
                    
                    Label(dialog, text=info_text, font=font.Font(size=18), 
                          bg='white', wraplength=650, justify='center').pack(pady=(0, 30))
                    
                    Label(dialog, text="Check out anyway?", font=font.Font(size=20, weight='bold'), 
                          bg='white').pack(pady=(0, 20))
                    
                    button_frame = tk.Frame(dialog, bg='white')
                    button_frame.pack(pady=40)
                    
                    Button(button_frame, text="Yes, Check Out", command=on_yes, 
                           font=font.Font(size=18), bg='#4CAF50', fg='white', 
                           width=15, height=2).pack(side='left', padx=10)
                    
                    Button(button_frame, text="No, Cancel", command=on_no, 
                           font=font.Font(size=18), bg='#f44336', fg='white', 
                           width=15, height=2).pack(side='left', padx=10)
                    
                    dialog.wait_window()
                    
                    if not result[0]:
                        self.show_welcome()
                        return


  
                # Checkout via API
                success, error = self.checkout_api(self.current_user['id'], fob['id'])
                if not success:
                    self.show_error(f"Checkout failed: {error}")
                    return
                
                self.notify_server()
                self.show_checkout_success(fob['vehicle_name'], fob['category'])
                self.current_user = None
            else:
                
                # Check if item is unavailable
                if fob.get('is_available') == 0:
                    self.clear_message_frame()
                    
                    tk.Label(self.message_frame, text="🚫", font=font.Font(size=120),
                          fg='#9E9E9E', bg='black').pack(pady=(30, 10))
                    
                    tk.Label(self.message_frame, text=f"{fob['vehicle_name']} is UNAVAILABLE",
                          font=self.header_font, fg='#9E9E9E', bg='black').pack(pady=(0, 10))
                    
                    # Show note/reason if exists
                    if fob.get('note') and fob['note'].get('note_text'):
                        tk.Label(self.message_frame, text=fob['note']['note_text'],
                              font=self.body_font, fg='#FF9800', bg='black',
                              wraplength=800, justify='center').pack(pady=(0, 20))
                    
                    tk.Label(self.message_frame, text="This item has been marked unavailable.",
                          font=self.body_font, fg='white', bg='black').pack(pady=(0, 20))
                    
                    button_frame = tk.Frame(self.message_frame, bg='black')
                    button_frame.pack(pady=10)
                    
                    def on_mark_available():
                        self.pending_fob = fob
                        self.pending_fob_mark_available = True
                        self.clear_message_frame()
                        tk.Label(self.message_frame, text="✅", font=font.Font(size=120),
                              fg='#4CAF50', bg='black').pack(pady=(50, 30))
                        tk.Label(self.message_frame, text=f"Scan your keycard to\nmark available & check out",
                              font=self.header_font, fg='#4CAF50', bg='black', justify='center').pack()
                        self.last_scan_time = datetime.now()
                    
                    def on_cancel():
                        self.show_welcome()
                    
                    tk.Button(button_frame, text="✅ Mark Available & Check Out",
                          font=font.Font(size=16, weight='bold'),
                          bg='#4CAF50', fg='white', width=28, height=2,
                          command=on_mark_available).pack(side='left', padx=10)
                    
                    tk.Button(button_frame, text="❌ Cancel",
                          font=font.Font(size=16, weight='bold'),
                          bg='#f44336', fg='white', width=12, height=2,
                          command=on_cancel).pack(side='left', padx=10)
                    
                    self.instructions_label.config(text="Session will timeout after 60 seconds")
                    self.last_scan_time = datetime.now()
                    return
                
                # Show available message and wait for card
                self.clear_message_frame()
                
                icon_label = tk.Label(
                    self.message_frame,
                    text="🔑",
                    font=font.Font(size=120),
                    fg='#FFA500',  # Orange
                    bg='black'
                )
                icon_label.pack(pady=(50, 30))
                
                msg_label = tk.Label(
                    self.message_frame,
                    text=f"{fob['vehicle_name']} is available",
                    font=self.header_font,
                    fg='#FFA500',
                    bg='black'
                )
                msg_label.pack(pady=(0, 20))
                
                instruction_label = tk.Label(
                    self.message_frame,
                    text="Scan your keycard to check it out",
                    font=self.body_font,
                    fg='white',
                    bg='black'
                )
                instruction_label.pack()
                
                self.instructions_label.config(text="Session will timeout after 60 seconds")
                
                # Store this fob for later checkout
                self.pending_fob = fob
                self.last_scan_time = datetime.now()




    def check_timeout_loop(self):
        """Check for session timeout"""
        if (self.current_user or self.replace_mode or self.note_mode or self.pending_fob) and self.last_scan_time:
            elapsed = (datetime.now() - self.last_scan_time).total_seconds()
            if elapsed > self.scan_timeout:
                self.show_error("Session timeout")
                self.current_user = None
                self.pending_fob = None
                self.replace_mode = None
                self.replace_item = None
                self.last_scan_time = None
                self.note_mode = False
      
        # Check again in 1 second
        self.root.after(1000, self.check_timeout_loop)
    
    def run(self):
        """Start the GUI"""
        self.root.mainloop()

    def start_note_mode(self):
        """Start note addition mode - ask if they have the fob"""
        from tkinter import Toplevel, Button, Label
        
        result = [None]
        
        def on_yes():
            result[0] = True
            dialog.destroy()
        
        def on_no():
            result[0] = False
            dialog.destroy()
        
        dialog = Toplevel(self.root)
        dialog.title("Add Note")
        dialog.geometry("700x400")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()
        
        Label(dialog, text="📝", font=font.Font(size=80),
              bg='white', fg='#FFC107').pack(pady=(30, 20))
        
        Label(dialog, text="Do you have the equipment with you?", 
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(0, 30))
        
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Yes - I'll Scan It", command=on_yes,
               font=font.Font(size=18), bg='#4CAF50', fg='white',
               width=18, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="No - Select from List", command=on_no,
               font=font.Font(size=18), bg='#2196F3', fg='white',
               width=20, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if result[0] is True:
            # They have the fob - show scan prompt
            self.note_mode = True
            self.clear_message_frame()
            
            icon_label = tk.Label(
                self.message_frame,
                text="📝",
                font=font.Font(size=120),
                fg='#FFC107',
                bg='black'
            )
            icon_label.pack(pady=(50, 30))
            
            msg_label = tk.Label(
                self.message_frame,
                text="Add Note to Equipment",
                font=self.header_font,
                fg='#FFC107',
                bg='black'
            )
            msg_label.pack(pady=(0, 20))
            
            instructions_label = tk.Label(
                self.message_frame,
                text="Scan equipment to add note",
                font=self.body_font,
                fg='white',
                bg='black'
            )
            instructions_label.pack()
            
            self.last_scan_time = datetime.now()
            
        elif result[0] is False:
            # They don't have it - show selection list
            self.show_equipment_list_for_note()
        else:
            # Cancelled
            self.show_welcome()

    def show_equipment_list_for_note(self):
        """Show list of all equipment to select for adding note"""
        from tkinter import Toplevel, Button, Label, Listbox, Scrollbar, SINGLE
        # Get all active equipment via API
        success, all_items = self.list_equipment_api()
        
        if not success or not all_items:
            self.show_error("No equipment found")
            return
        
        # Create selection dialog
        result = [None]
        
        def on_select():
            selection = listbox.curselection()
            if selection and selection[0] in item_indices:
                actual_index = item_indices[selection[0]]
                selected_item = all_items[actual_index]
                # Do fresh lookup to get note data
                found, fob_with_note = self.lookup_api('fob', selected_item['fob_id'])
                if found and fob_with_note:
                    result[0] = fob_with_note
                else:
                    result[0] = selected_item
                dialog.destroy()
        
        dialog = Toplevel(self.root)
        dialog.title("Add Note - Select Equipment")
        dialog.geometry("900x850")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()
        
        Label(dialog, text="📝 Add Note to Equipment", 
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(20, 10))
        
        Label(dialog, text="Select the equipment:", 
              font=font.Font(size=14), bg='white').pack(pady=(0, 20))
        
        # Listbox with scrollbar
        list_frame = tk.Frame(dialog, bg='white')
        list_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        
        scrollbar = Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        listbox = Listbox(list_frame, font=font.Font(size=14), height=25, 
                         yscrollcommand=scrollbar.set, selectmode=SINGLE)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)
        
        # Populate list - group by category
        # Track which listbox indices correspond to actual items
        item_indices = {}  # Maps listbox index to all_items index
        listbox_index = 0
        
        current_category = None
        for i, item in enumerate(all_items):
            if item['category'] != current_category:
                current_category = item['category']
                listbox.insert('end', f"--- {current_category} ---")
                listbox.itemconfig(listbox_index, {'bg': '#E0E0E0', 'fg': '#666'})
                listbox_index += 1
            
            listbox.insert('end', f"  {item['vehicle_name']}")
            item_indices[listbox_index] = i  # Map this listbox position to the item
            listbox_index += 1
        
        # Buttons
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Add Note", command=on_select,
               font=font.Font(size=16), bg='#FFC107', fg='black',
               width=15, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="Cancel", command=dialog.destroy,
               font=font.Font(size=16), bg='#999', fg='white',
               width=12, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if result[0]:
            # Show note input for selected equipment
            self.show_note_input(result[0])
        else:
            self.show_welcome()

    def show_note_input(self, fob):
        """Show text input for note or prompt to replace/delete existing"""
        from tkinter import Toplevel, Label, Text, Button, Checkbutton, BooleanVar, Frame, Entry
        from datetime import datetime, timedelta
        
        # Check if note already exists (from fob data)
        existing_note = fob.get('note')
        
        if existing_note:
            # Show replace/delete dialog
            result = [None]
            
            def on_replace():
                result[0] = 'replace'
                dialog.destroy()
            
            def on_delete():
                result[0] = 'delete'
                dialog.destroy()
            
            def on_cancel():
                result[0] = None
                dialog.destroy()
            
            dialog = Toplevel(self.root)
            dialog.title("Note Exists")
            dialog.geometry("700x500")
            dialog.configure(bg='white')
            dialog.transient(self.root)
            dialog.grab_set()
            
            Label(dialog, text="📝", font=font.Font(size=60), 
                  bg='white', fg='#FFC107').pack(pady=(30, 20))
            
            Label(dialog, text=f"{fob['vehicle_name']} has a note:", 
                  font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(0, 20))
            
            Label(dialog, text=f'"{existing_note["note_text"]}"', 
                  font=font.Font(size=16), bg='white', fg='#666', 
                  wraplength=600, justify='center').pack(pady=(0, 10))
            
            # Show expiration if set
            if existing_note['expires_at']:
                try:
                    chicago_tz = pytz.timezone('America/Chicago')
                    exp_dt = datetime.fromisoformat(existing_note['expires_at'])
                    if exp_dt.tzinfo is not None:
                        exp_dt = exp_dt.astimezone(chicago_tz)
                    formatted_exp = exp_dt.strftime('%b %d, %Y %H:%M')  # Mar 25, 2026 21:15
                    Label(dialog, text=f"Expires: {formatted_exp}", 
                          font=font.Font(size=14), bg='white', fg='#FF9800').pack(pady=(0, 20))
                except:
                    Label(dialog, text=f"Expires: {existing_note['expires_at']}", 
                          font=font.Font(size=14), bg='white', fg='#FF9800').pack(pady=(0, 20))
            else:
                Label(dialog, text="No expiration set", 
                      font=font.Font(size=14), bg='white', fg='#666').pack(pady=(0, 20))
            
            Label(dialog, text="What would you like to do?", 
                  font=font.Font(size=18), bg='white').pack(pady=(0, 20))
            
            button_frame = tk.Frame(dialog, bg='white')
            button_frame.pack(pady=20)
            
            Button(button_frame, text="Replace Note", command=on_replace, 
                   font=font.Font(size=16), bg='#FFC107', fg='black', 
                   width=15, height=2).pack(side='left', padx=10)
            
            Button(button_frame, text="Delete Note", command=on_delete, 
                   font=font.Font(size=16), bg='#f44336', fg='white', 
                   width=15, height=2).pack(side='left', padx=10)
            
            Button(button_frame, text="Cancel", command=on_cancel, 
                   font=font.Font(size=16), bg='#666', fg='white', 
                   width=15, height=2).pack(side='left', padx=10)
            
            dialog.wait_window()
            
            if result[0] == 'delete':
                # Delete the note
                chicago_tz = pytz.timezone('America/Chicago')
                # Delete note via API
                success, error = self.delete_note_api(fob['id'])
                if not success:
                    self.show_error(f"Failed to delete note: {error}")
                    return
                
                self.notify_server()
                
                # Show success
                self.clear_message_frame()
                
                Label(self.message_frame, text="✅", font=font.Font(size=120), 
                      fg='#4CAF50', bg='black').pack(pady=(50, 30))
                
                Label(self.message_frame, text="Note deleted!", 
                      font=self.header_font, fg='#4CAF50', bg='black').pack()
                
                self.root.after(2000, self.show_welcome)
                self.note_mode = False
                return
            elif result[0] == 'replace':
                # Continue to text input below
                pass
            else:
                # Cancel
                self.show_welcome()
                self.note_mode = False
                return
        
        # Show text input (either new note or replacing existing)
        result = {'note': None, 'expires_at': None}
        
        def on_submit():
            note_text = text_widget.get("1.0", "end-1c").strip()
            if not note_text:
                return
            
            result['note'] = note_text
            
            # Check if expiration is set
            if has_expiration.get():
                try:
                    # Parse date and time
                    date_str = date_entry.get().strip()
                    time_str = time_entry.get().strip()
                    
                    if date_str and time_str:
                        # Combine date and time
                        chicago_tz = pytz.timezone('America/Chicago')
                        dt_str = f"{date_str} {time_str}"
                        dt = datetime.strptime(dt_str, '%m/%d/%Y %H:%M')
                        dt_aware = chicago_tz.localize(dt)
                        result['expires_at'] = dt_aware.isoformat()
                except Exception as e:
                    print(f"Error parsing expiration: {e}")
                    # Continue without expiration if parsing fails
            
            dialog.destroy()
        
        def on_cancel():
            result['note'] = None
            dialog.destroy()
        
        def toggle_expiration():
            """Show/hide expiration fields"""
            if has_expiration.get():
                expiration_frame.pack(pady=10, before=button_frame)
            else:
                expiration_frame.pack_forget()
        
        dialog = Toplevel(self.root)
        dialog.title("Add Note")
        dialog.geometry("700x650")
        dialog.configure(bg='white')
        dialog.transient(self.root)
        dialog.grab_set()
        
        Label(dialog, text="📝", font=font.Font(size=60), 
              bg='white', fg='#FFC107').pack(pady=(30, 20))
        
        title_text = f"Replace note for {fob['vehicle_name']}" if existing_note else f"Add note for {fob['vehicle_name']}"
        Label(dialog, text=title_text, 
              font=font.Font(size=20, weight='bold'), bg='white').pack(pady=(0, 20))
        
        Label(dialog, text="Type note (e.g., 'Computer not working')", 
              font=font.Font(size=14), bg='white').pack(pady=(0, 10))
        
        text_widget = Text(dialog, font=font.Font(size=16), width=50, height=5, 
                          wrap='word', bg='#f0f0f0')
        text_widget.pack(pady=10, padx=20)
        
        # Pre-fill with existing note if replacing
        if existing_note:
            text_widget.insert("1.0", existing_note['note_text'])
        
        text_widget.focus()
        
        # Expiration checkbox
        has_expiration = BooleanVar(value=False)
        checkbox = Checkbutton(dialog, text="⏰ Set Expiration", 
                              variable=has_expiration, command=toggle_expiration,
                              font=font.Font(size=14), bg='white')
        checkbox.pack(pady=10)
        
        # Expiration input frame (hidden by default)
        expiration_frame = Frame(dialog, bg='white')
        
        Label(expiration_frame, text="Date (MM/DD/YYYY):", 
              font=font.Font(size=12), bg='white').pack(side='left', padx=5)
        
        # Default to tomorrow
        chicago_tz = pytz.timezone('America/Chicago')
        tomorrow = datetime.now(chicago_tz) + timedelta(days=1)
        
        date_entry = Entry(expiration_frame, font=font.Font(size=14), width=12)
        date_entry.insert(0, tomorrow.strftime('%m/%d/%Y'))
        date_entry.pack(side='left', padx=5)
        
        Label(expiration_frame, text="Time (HH:MM):", 
              font=font.Font(size=12), bg='white').pack(side='left', padx=5)
        
        time_entry = Entry(expiration_frame, font=font.Font(size=14), width=8)
        time_entry.insert(0, "17:00")  # Default to 5 PM
        time_entry.pack(side='left', padx=5)
        
        # Pre-fill expiration if replacing and has expiration
        if existing_note and existing_note['expires_at']:
            has_expiration.set(True)
            try:
                exp_dt = datetime.fromisoformat(existing_note['expires_at'])
                date_entry.delete(0, 'end')
                date_entry.insert(0, exp_dt.strftime('%m/%d/%Y'))
                time_entry.delete(0, 'end')
                time_entry.insert(0, exp_dt.strftime('%H:%M'))
                expiration_frame.pack(pady=10)
            except:
                pass
        
        # Buttons
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Submit", command=on_submit, 
               font=font.Font(size=16), bg='#4CAF50', fg='white', 
               width=12, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="Cancel", command=on_cancel, 
               font=font.Font(size=16), bg='#666', fg='white', 
               width=12, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if result['note']:
            # Save note
            chicago_tz = pytz.timezone('America/Chicago')
            # Add note via API
            success, error = self.add_note_api(fob['id'], result['note'], result['expires_at'])
            if not success:
                self.show_error(f"Failed to add note: {error}")
                return
            
            self.notify_server()
            
            # Show success
            self.clear_message_frame()
            
            Label(self.message_frame, text="✅", font=font.Font(size=120), 
                  fg='#4CAF50', bg='black').pack(pady=(50, 30))
            
            success_text = "Note updated!" if existing_note else "Note added!"
            Label(self.message_frame, text=success_text, 
                  font=self.header_font, fg='#4CAF50', bg='black').pack()
            
            self.root.after(2000, self.show_welcome)
        else:
            self.show_welcome()
        
        self.note_mode = False


if __name__ == '__main__':
    import sys

    # Check for --kiosk-id argument
    kiosk_id = 'station' #default
    if '--kiosk-id' in sys.argv:
        idx = sys.argv.index('--kiosk-id')
        if idx + 1 < len(sys.argv):
            kiosk_id = sys.argv[idx + 1]

    kiosk = KioskGUI(kiosk_id=kiosk_id)
    kiosk.root.mainloop()
