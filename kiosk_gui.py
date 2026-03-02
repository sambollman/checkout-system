#!/usr/bin/env python3
import tkinter as tk
from tkinter import font
import time
from database import get_db
from datetime import datetime, timedelta
from offline_queue import queue_transaction, get_pending_transactions, mark_synced, get_queue_count
import threading
import pytz
import threading
import requests
import os

# Server configuration
SERVER_URL = os.getenv('SERVER_URL', 'http://localhost:5000')
KIOSK_USER = os.getenv('KIOSK_USER', 'kiosk')
KIOSK_PASS = os.getenv('KIOSK_PASS', 'change-this-in-production')

print(f"DEBUG: SERVER_URL={SERVER_URL}")
print(f"DEBUG: KIOSK_USER={KIOSK_USER}")
print(f"DEBUG: KIOSK_PASS={KIOSK_PASS}")

class KioskGUI:
    def __init__(self, kiosk_id='kiosk1'):
        self.kiosk_id = kiosk_id
        self.current_user = None
        self.scan_timeout = 30
        self.last_scan_time = None
        self.pending_fob = None
        self.replace_mode = None # 'card' or 'fob'
        self.replace_item = None # The item being replaced
        self.note_mode = False
        self.offline_mode = False
        self.sync_in_progress = False
        self.pending_count = 0

        # Offline mode indicator
        self.offline_indicator = None

        # Create main window
        self.root = tk.Tk()
        self.root.title("Key Checkout Kiosk")
        self.root.configure(bg='black')
        self.root.attributes('-fullscreen', True)
        self.root.bind('<Escape>', self.exit_fullscreen)
        self.root.bind('<F11>', self.enter_fullscreen)
        
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
        self.show_welcome()
        
        # Start timeout checker
        self.check_timeout_loop()

        # Start connectivity check loop
        self.check_connectivity_loop()
    
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
                timeout=1
            )
            return response.status_code == 200
        except:
            return False

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
        
        # Search for user
        conn = get_db()
        users = conn.execute('''
            SELECT * FROM users 
            WHERE last_name LIKE ? OR card_id LIKE ?
        ''', (f'%{search}%', f'%{search}%')).fetchall()
        conn.close()
        
        if not users:
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
            
            self.instructions_label.config(text="Session will timeout after 30 seconds")
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
                
                self.instructions_label.config(text="Session will timeout after 30 seconds")
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
        
        # Search for fob
        conn = get_db()
        fobs = conn.execute('''
            SELECT * FROM key_fobs 
            WHERE vehicle_name LIKE ? AND is_active = 1
        ''', (f'%{search}%',)).fetchall()
        conn.close()
        
        if not fobs:
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
            
            self.instructions_label.config(text="Session will timeout after 30 seconds")
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
                
                self.instructions_label.config(text="Session will timeout after 30 seconds")
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
    
    def show_welcome(self):
        """Display welcome screen"""
        self.clear_message_frame()
        self.current_user = None
        
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
        
        # Button container
        button_frame = tk.Frame(self.message_frame, bg='black')
        button_frame.pack(pady=20)
        
        # Add Note button
        note_btn = tk.Button(
            button_frame,
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
            button_frame,
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
            button_frame,
            text="💳 Replace Card",
            font=font.Font(size=16, weight='bold'),
            bg='#9C27B0',
            fg='white',
            width=15,
            height=2,
            command=self.replace_card
        )
        card_btn.pack(side='left', padx=10)
        
        # Barns Transfer button
        barns_btn = tk.Button(
            button_frame,
            text="🏭 Barns Transfer",
            font=font.Font(size=16, weight='bold'),
            bg='#795548',
            fg='white',
            width=15,
            height=2,
            command=self.barns_transfer
        )
        barns_btn.pack(side='left', padx=10)
        # Instructions
        self.instructions_label.config(text="Press F11 for fullscreen")
        
    
    def add_note(self):
        """Button handler for adding note"""
        # Simulate pressing 'n' key
        event = type('Event', (), {'char': 'n', 'keysym': 'n'})()
        self.on_key_press(event)
    
    def replace_fob(self):
        """Button handler for replacing fob"""
        # Simulate pressing 'f' key
        event = type('Event', (), {'char': 'f', 'keysym': 'f'})()
        self.on_key_press(event)
    
    def replace_card(self):
        """Button handler for replacing card"""
        # Simulate pressing 'r' key
        event = type('Event', (), {'char': 'r', 'keysym': 'r'})()
        self.on_key_press(event)

    def barns_transfer(self):
        """Transfer vehicle to The Barns"""
        from tkinter import Toplevel, Button, Label, Listbox, Scrollbar, SINGLE
        
        conn = get_db()
        
        # Get "The Barns" user
        barns_user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)).fetchone()
        
        if not barns_user:
            # Create The Barns user if doesn't exist
            conn.execute('INSERT INTO users (card_id, first_name, last_name, is_active) VALUES (?, ?, ?, ?)',
                        ('BARNS', 'The', 'Barns', 1))
            conn.commit()
            barns_user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)).fetchone()
        
        # Get all vehicles (not equipment)
        vehicles = conn.execute('''
            SELECT kf.*, c.id as checkout_id, c.checked_out_at, u.first_name, u.last_name
            FROM key_fobs kf
            LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
            LEFT JOIN users u ON c.user_id = u.id
            WHERE kf.category IN ('Squad Cars', 'CSO Vehicles', 'CID Vehicles')
            AND kf.is_active = 1
            ORDER BY kf.vehicle_name
        ''').fetchall()
        
        conn.close()
        
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
        conn = get_db()
        chicago_tz = pytz.timezone('America/Chicago')
        
        try:
            # If currently checked out, check it in first
            if vehicle['checkout_id']:
                conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                            (datetime.now(chicago_tz), vehicle['checkout_id']))
            
            # Check out to The Barns
            conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                        (barns_user['id'], vehicle['id'], self.kiosk_id, datetime.now(chicago_tz)))
            conn.commit()
            conn.close()
            print("About to call notify server...")
            self.notify_server()
            print(" notify_server completed")
            # Show success
            self.clear_message_frame()
            
            Label(self.message_frame, text="✅", font=font.Font(size=120),
                  fg='#4CAF50', bg='black').pack(pady=(50, 30))
            
            Label(self.message_frame, 
                  text=f"{vehicle['vehicle_name']}\ntransferred to The Barns",
                  font=self.header_font, fg='white', bg='black',
                  justify='center').pack()
            
            self.root.after(3000, self.show_welcome)
            
        except Exception as e:
            conn.close()
            self.show_error(f"Transfer failed: {e}")



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
            text="Session will timeout after 30 seconds of inactivity"
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
        
        # Check for replace mode trigger (R key pressed alone)
        if (event.char == 'r' or event.char == 'R') and not self.scan_buffer:
            self.start_replace_card_mode()
            return
        
        # Check for replace fob mode (F key pressed alone)
        if (event.char == 'f' or event.char == 'F') and not self.scan_buffer:
            self.start_replace_fob_mode()
            return
        
        # Check for note mode (N key pressed alone)
        if (event.char == 'n' or event.char == 'N') and not self.scan_buffer and not self.current_user:
            self.start_note_mode()
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
        # Check if we've seen this ID before
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (scan_data,)).fetchone()
        fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE', (scan_data,)).fetchone()
        conn.close()
        
        # If it exists in either table, route accordingly
        if user:
            self.handle_card_scan(scan_data)
        elif fob:
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
        # Check if we're in replace mode
        if self.replace_mode == 'card' and self.replace_item:
            # This is the NEW card being scanned
            conn = get_db()
            # Check if new card already exists
            existing = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (card_id,)).fetchone()
            if existing:
                conn.close()
                self.replace_mode = None
                self.replace_item = None
                self.show_error("This card is already registered to someone else")
                return
            
            # Update the card ID
            conn.execute('UPDATE users SET card_id = ? WHERE id = ?',
                        (card_id, self.replace_item['id']))
            conn.commit()
            conn.close()
            
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
            conn = get_db()
            user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE AND is_active = 1', 
                               (card_id,)).fetchone()
            conn.close()
            if not user:
                # New user - register them first
                conn.close()
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
                
                conn = get_db()
                try:
                    conn.execute('INSERT INTO users (card_id, first_name, last_name, registered_at) VALUES (?, ?, ?,?)',
                                (card_id, first_name.strip(), last_name.strip(), datetime.now(pytz.timezone('America/Chicago'))))
                    conn.commit()
                    user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (card_id,)).fetchone()
                    conn.close()
                except Exception as e:
                    conn.close()
                    self.pending_fob = None
                    self.show_error(f"Error registering user: {e}")
                    return
            
            # Check out the pending fob - get fresh connection
            conn = get_db()
            try:
                if not self.check_server_available():
                    raise Exception("Server offline")
                conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (user['id'], self.pending_fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                conn.commit()
                conn.close()
                self.notify_server()
            except Exception as e:
                # Server offline - write locally AND queue for sync
                try:
                    conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                                (user['id'], self.pending_fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                    conn.commit()
                    print(f"✓ Written to local DB successfully")
                except Exception as db_error:
                    print(f"✗ Failed to write to local DB: {db_error}")
                finally:
                    conn.close()
                
                # Also queue for server sync
                user_info = {
                    'card_id': user['card_id'],
                    'first_name': user['first_name'],
                    'last_name': user['last_name']
                }
                fob_info = {
                    'fob_id': self.pending_fob['fob_id'],
                    'vehicle_name': self.pending_fob['vehicle_name']
                }
                count = queue_transaction('checkout', user_info, fob_info, self.kiosk_id)
                self.go_offline()
                self.update_offline_count()
                print(f"⚠️ Queued checkout offline ({count} pending): {e}")

            
            self.show_checkout_success(self.pending_fob['vehicle_name'], self.pending_fob['category'])
            self.pending_fob = None
            self.current_user = None
            return

            

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE AND is_active = 1', 
                           (card_id,)).fetchone()
        conn.close()
        
        if not user:
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
            conn = get_db()
            try:
                conn.execute('INSERT INTO users (card_id, first_name, last_name, registered_at) VALUES (?, ?, ?,?)',
                            (card_id, first_name.strip(), last_name.strip(), datetime.now(pytz.timezone('America/Chicago'))))
                conn.commit()
                user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', (card_id,)).fetchone()
                conn.close()
            except Exception as e:
                conn.close()
                self.show_error(f"Error registering user: {e}")
                return
        
        self.current_user = user
        self.last_scan_time = datetime.now()
        self.show_user_greeting(user)


    def handle_fob_scan(self, fob_id):
        """Handle a fob scan"""
        conn = get_db()
        
        # Check if in note mode
        if self.note_mode:
            print("DEBUG: In note mode, fob_id:", fob_id)
            fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE AND is_active = 1', (fob_id,)).fetchone()
            
            if not fob:
                conn.close()
                self.show_welcome()
                return
            
            self.show_note_input(fob)
            conn.close()
            return


        fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE AND is_active = 1', 
                          (fob_id,)).fetchone()
        
        if not fob:
            # New fob - register it
            conn.close()
            
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
            categories = ["Squad Cars", "CSO Vehicles", "CID Vehicles", "Equipment"]
            
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


        # Register the fob
            conn = get_db()
            try:
                conn.execute('INSERT INTO key_fobs (fob_id, vehicle_name, category, location, registered_at) VALUES (?, ?, ?, ?,?)',
                            (fob_id, vehicle_name.strip(), category, location.strip(), datetime.now(pytz.timezone('America/Chicago'))))
                conn.commit()
                fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE', (fob_id,)).fetchone()
                conn.close()
                
                self.notify_server()
   
                # If user already scanned card, check out the new fob immediately
                if self.current_user:
                    conn = get_db()
                    try:
                        if not self.check_server_available():
                            raise Exception("Server offline")
                        conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                        conn.commit()
                        conn.close()
                        self.notify_server()
                    except Exception as e:
                        # Server offline - write locally AND queue for sync
                        conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                        conn.commit()
                        conn.close()
                        
                        # Also queue for server sync
                        user_info = {
                            'card_id': self.current_user['card_id'],
                            'first_name': self.current_user['first_name'],
                            'last_name': self.current_user['last_name']
                        }
                        fob_info = {
                            'fob_id': fob['fob_id'],
                            'vehicle_name': fob['vehicle_name']
                        }
                        count = queue_transaction('checkout', user_info, fob_info, self.kiosk_id)
                        self.go_offline()
                        self.update_offline_count()
                        print(f"⚠️ Queued checkout offline ({count} pending): {e}")
                    
                    self.show_checkout_success(fob['vehicle_name'], fob['category'])
                    self.current_user = None
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
                    
            except Exception as e:
                conn.close()
                self.show_error(f"Error registering fob: {e}")
                return
        
        # Check if it's currently checked out
        conn = get_db()
        checkout = conn.execute('''
            SELECT c.*, u.first_name, u.last_name
            FROM checkouts c
            JOIN users u ON c.user_id = u.id
            WHERE c.fob_id = ? AND c.checked_in_at IS NULL
        ''', (fob['id'],)).fetchone()
        
        if checkout:
            # Check if there's a different user trying to take it
            if self.current_user and self.current_user['id'] != checkout['user_id']:
                # Handoff: check in from previous user, check out to new user
                try:
                    if not self.check_server_available():
                        raise Exception("Server offline")
                    conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                                (datetime.now(pytz.timezone('America/Chicago')), checkout['id']))
                    conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                    conn.commit()
                    conn.close()
                    self.notify_server()
                except Exception as e:
                    # Server offline - write locally AND queue for sync
                    conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                                (datetime.now(pytz.timezone('America/Chicago')), checkout['id']))
                    conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                    conn.commit()
                    conn.close()
                    
                    # Also queue for server sync
                    fob_info = {'fob_id': fob['fob_id'], 'vehicle_name': fob['vehicle_name']}
                    queue_transaction('checkin', None, fob_info, self.kiosk_id)
                    
                    user_info = {
                        'card_id': self.current_user['card_id'],
                        'first_name': self.current_user['first_name'],
                        'last_name': self.current_user['last_name']
                    }
                    count = queue_transaction('checkout', user_info, fob_info, self.kiosk_id)
                    self.go_offline()
                    self.update_offline_count()
                    print(f"⚠️ Queued handoff offline ({count} pending): {e}")
                
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
                # Same user returning it, or no user scanned
                try:
                    if not self.check_server_available():
                        raise Exception("Server offline")
                    conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                                (datetime.now(pytz.timezone('America/Chicago')), checkout['id']))
                    conn.commit()
                    conn.close()
                    self.notify_server()
                except Exception as e:
                    # Server offline - write locally AND queue for sync
                    conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                                (datetime.now(pytz.timezone('America/Chicago')), checkout['id']))
                    conn.commit()
                    conn.close()
                    
                    # Also queue for server sync
                    fob_info = {
                        'fob_id': fob['fob_id'],
                        'vehicle_name': fob['vehicle_name']
                    }
                    count = queue_transaction('checkin', None, fob_info, self.kiosk_id)
                    self.go_offline()
                    self.update_offline_count()
                    print(f"⚠️ Queued checkin offline ({count} pending): {e}")
                
                was_with = f"{checkout['first_name']} {checkout['last_name']}"
                self.show_checkin_success(fob['vehicle_name'], was_with)
                self.current_user = None

        else:
            # Check it out
            if self.current_user:
                # Check if reserved - use Python datetime for proper timezone handling
                from tkinter import messagebox
                
                chicago_tz = pytz.timezone('America/Chicago')
                now = datetime.now(chicago_tz)
                
                # Get all reservations for this fob
                all_reservations = conn.execute('''
                    SELECT r.*, u.first_name, u.last_name
                    FROM reservations r
                    LEFT JOIN users u ON r.user_id = u.id
                    WHERE r.fob_id = ?
                ''', (fob['id'],)).fetchall()
                
                # Check if any are active (in Python to handle timezones)
                reservation = None
                print(f"DEBUG: Checking {len(all_reservations)} reservations for fob {fob['id']}")
                for res in all_reservations:
                    try:
                        res_dt = datetime.fromisoformat(res['reserved_datetime'])
                        display_start = res_dt - timedelta(hours=res['display_hours_before'])
                        print(f"DEBUG: Reservation time: {res_dt}, Display start: {display_start}, Now: {now}")
                        if res_dt > now and display_start <= now:
                            reservation = res
                            print(f"DEBUG: Found active reservation!")
                            break
                    except Exception as e:
                        print(f"DEBUG: Error checking reservation: {e}")
                        pass
                
                print(f"DEBUG: Final reservation: {reservation}")
                
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
                        conn.close()
                        self.show_welcome()
                        return


  
                # Try to checkout
                try:
                    if not self.check_server_available():
                        raise Exception("Server offline")
                    conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                            (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                    conn.commit()
                    conn.close()
                    self.notify_server()
                
                except Exception as e:
                    # Server offline - write locally AND queue for sync
                    try:
                        conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                                (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(pytz.timezone('America/Chicago'))))
                        conn.commit()
                        print(f"✓ Written to local DB successfully")
                    except Exception as db_error:
                        print(f"✗ Failed to write to local DB: {db_error}")
                    finally:
                        conn.close()
                    
                    # Also queue for server sync
                    user_info = {
                        'card_id': self.current_user['card_id'],
                        'first_name': self.current_user['first_name'],
                        'last_name': self.current_user['last_name']
                    }
                    fob_info = {
                        'fob_id': fob['fob_id'],
                        'vehicle_name': fob['vehicle_name']
                    }
                    count = queue_transaction('checkout', user_info, fob_info, self.kiosk_id)
                    self.go_offline()
                    self.update_offline_count()
                    print(f"⚠️ Queued checkout offline ({count} pending): {e}")
                
                self.show_checkout_success(fob['vehicle_name'], fob['category'])
                self.current_user = None
            else:
                conn.close()
                
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
                
                self.instructions_label.config(text="Session will timeout after 30 seconds")
                
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
    
    def check_connectivity_loop(self):
        """Check if server is reachable and sync if needed"""
        def check():
            try:
                response = requests.get(
                    f'{SERVER_URL}/api/status',
                    auth=(KIOSK_USER, KIOSK_PASS),
                    timeout=2
                )
                if response.status_code == 200:
                    # Server is reachable
                    if self.offline_mode:
                        self.go_online()
                    return True
            except:
                pass
            
            # Server unreachable
            if not self.offline_mode:
                self.go_offline()
            return False
        
        # Check in background thread
        threading.Thread(target=check, daemon=True).start()
        
        # Check again in 30 seconds
        self.root.after(30000, self.check_connectivity_loop)
    
    def go_offline(self):
        """Switch to offline mode"""
        if not self.offline_mode:
            self.offline_mode = True
            self.pending_count = get_queue_count()
            print("⚠️ OFFLINE MODE ACTIVATED")
            self.show_offline_indicator()
    
    def go_online(self):
        """Switch back to online mode and sync queued transactions"""
        if self.offline_mode and not self.sync_in_progress:
            self.offline_mode = False
            self.hide_offline_indicator()
            print("✅ BACK ONLINE - Syncing...")
            
            # Sync queued transactions in background
            threading.Thread(target=self.sync_offline_queue, daemon=True).start()
    
    def show_offline_indicator(self):
        """Show offline mode banner"""
        if self.offline_indicator:
            return
        
        self.offline_indicator = tk.Label(
            self.root,
            text=f"⚠️ OFFLINE MODE - {self.pending_count} queued",
            font=font.Font(size=20, weight='bold'),
            bg='#FF9800',
            fg='white',
            pady=10
        )
        self.offline_indicator.pack(side='top', fill='x')
    
    def hide_offline_indicator(self):
        """Hide offline mode banner"""
        if self.offline_indicator:
            self.offline_indicator.pack_forget()
            self.offline_indicator = None
    
    def update_offline_count(self):
        """Update pending transaction count in offline indicator"""
        self.pending_count = get_queue_count()
        if self.offline_indicator:
            self.offline_indicator.config(text=f"⚠️ OFFLINE MODE - {self.pending_count} queued")
    
    def sync_offline_queue(self):
        """Sync all queued transactions to server"""
        self.sync_in_progress = True
        pending = get_pending_transactions()
        
        if not pending:
            self.sync_in_progress = False
            return
        
        synced_count = 0
        failed_count = 0
        
        for trans in pending:
            try:
                if trans['transaction_type'] == 'checkout':
                    data = {
                        'user_card_id': trans['user_card_id'],
                        'user_first_name': trans['user_first_name'],
                        'user_last_name': trans['user_last_name'],
                        'fob_id': trans['fob_id'],
                        'timestamp': trans['timestamp'],
                        'kiosk_id': trans['kiosk_id']
                    }
                    response = requests.post(
                        f'{SERVER_URL}/api/offline_sync/checkout',
                        json=data,
                        auth=(KIOSK_USER, KIOSK_PASS),
                        timeout=5
                    )
                    
                elif trans['transaction_type'] == 'checkin':
                    data = {
                        'fob_id': trans['fob_id'],
                        'timestamp': trans['timestamp'],
                        'kiosk_id': trans['kiosk_id']
                    }
                    response = requests.post(
                        f'{SERVER_URL}/api/offline_sync/checkin',
                        json=data,
                        auth=(KIOSK_USER, KIOSK_PASS),
                        timeout=5
                    )
                
                if response.status_code == 200:
                    mark_synced(trans['id'])
                    synced_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                print(f"Sync failed for transaction {trans['id']}: {e}")
                failed_count += 1
        
        print(f"✅ Synced {synced_count} transactions ({failed_count} failed)")
        self.sync_in_progress = False
        self.pending_count = get_queue_count()


    def run(self):
        """Start the GUI"""
        self.root.mainloop()

    def start_note_mode(self):
        """Start note addition mode"""
        print("DEBUG: Starting note mode")
        self.note_mode = True
        print(f"DEBUG: note_mode is now {self.note_mode}")
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
        
        # Set timeout
        self.last_scan_time = datetime.now()
    def show_note_input(self, fob):
        """Show text input for note or prompt to replace/delete existing"""
        from tkinter import Toplevel, Label, Text, Button
        
        # Check if note already exists
        conn = get_db()
        existing_note = conn.execute('SELECT * FROM notes WHERE fob_id = ?', (fob['id'],)).fetchone()
        conn.close()
        
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
                  wraplength=600, justify='center').pack(pady=(0, 30))
            
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
                conn = get_db()
                conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob['id'],))
                conn.commit()
                conn.close()
                
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
        result = [None]
        
        def on_submit():
            result[0] = text_widget.get("1.0", "end-1c").strip()
            dialog.destroy()
        
        def on_cancel():
            result[0] = None
            dialog.destroy()
        
        dialog = Toplevel(self.root)
        dialog.title("Add Note")
        dialog.geometry("700x500")
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
        
        button_frame = tk.Frame(dialog, bg='white')
        button_frame.pack(pady=20)
        
        Button(button_frame, text="Submit", command=on_submit, 
               font=font.Font(size=16), bg='#4CAF50', fg='white', 
               width=12, height=2).pack(side='left', padx=10)
        
        Button(button_frame, text="Cancel", command=on_cancel, 
               font=font.Font(size=16), bg='#666', fg='white', 
               width=12, height=2).pack(side='left', padx=10)
        
        dialog.wait_window()
        
        if result[0]:
            # Save note
            chicago_tz = pytz.timezone('America/Chicago')
            conn = get_db()
            
            # Delete existing note for this fob (one note at a time)
            conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob['id'],))
            
            # Insert new note
            conn.execute('''
                INSERT INTO notes (fob_id, note_text, created_at, created_by)
                VALUES (?, ?, ?, ?)
            ''', (fob['id'], result[0], datetime.now(chicago_tz).isoformat(), 'kiosk'))
            
            conn.commit()
            conn.close()
            
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
    kiosk = KioskGUI()
    kiosk.run()
