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
        self.barns_scan_mode = False
        self.bulk_checkout_mode = False
        self.bulk_items = []

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
 
        # Instructions
        self.entry.focus_set()
        self.instructions_label.config(text="")
        self.instructions_label.config(text="Press F11 for fullscreen")
        
    
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
            text="Bulk Checkout Mode\n\nScan your keycard",
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
        header_label = tk.Label(
            self.message_frame,
            text=f"🛒 Bulk Checkout - {self.current_user['first_name']} {self.current_user['last_name']}",
            font=font.Font(size=20, weight='bold'),
            fg='#4CAF50',
            bg='black'
        )
        header_label.pack(pady=(20, 10))
        
        instruction_label = tk.Label(
            self.message_frame,
            text="Scan items to check out",
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
        
        self.instructions_label.config(text=f"{len(self.bulk_items)} item(s) scanned • Timeout in 30 seconds")

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
        if not self.bulk_items:
            self.show_error("No items to check out")
            return
        
        chicago_tz = pytz.timezone('America/Chicago')
        conn = get_db()
        
        checked_out_items = []
        failed_items = []
        
        for fob in self.bulk_items:
            try:
                # Check if already checked out
                existing = conn.execute('''
                    SELECT c.*, u.first_name, u.last_name 
                    FROM checkouts c
                    JOIN users u ON c.user_id = u.id
                    WHERE c.fob_id = ? AND c.checked_in_at IS NULL
                ''', (fob['id'],)).fetchone()
                
                if existing:
                    # Handoff transfer
                    if existing['user_id'] != self.current_user['id']:
                        conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                                    (datetime.now(chicago_tz), existing['id']))
                        conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                                    (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(chicago_tz)))
                        checked_out_items.append(fob['vehicle_name'])
                    # else: already checked out to this user, skip
                else:
                    # Normal checkout
                    conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                                (self.current_user['id'], fob['id'], self.kiosk_id, datetime.now(chicago_tz)))
                    checked_out_items.append(fob['vehicle_name'])
                    
            except Exception as e:
                print(f"Failed to checkout {fob['vehicle_name']}: {e}")
                failed_items.append(fob['vehicle_name'])
        
        conn.commit()
        conn.close()
        
        # Notify server
        try:
            self.notify_server()
        except:
            pass
        
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
        
        # Rest of existing barns_transfer code stays here...
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
        self.perform_barns_transfer(vehicle)


    def perform_barns_transfer(self, vehicle):
        """Actually perform the barns transfer for a given vehicle"""
        from tkinter import Label
        conn = get_db()
        chicago_tz = pytz.timezone('America/Chicago')
        
        # Get "The Barns" user
        barns_user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)).fetchone()
        
        if not barns_user:
            # Create The Barns user if doesn't exist
            conn.execute('INSERT INTO users (card_id, first_name, last_name, is_active) VALUES (?, ?, ?, ?)',
                        ('BARNS', 'The', 'Barns', 1))
            conn.commit()
            barns_user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE', ('BARNS',)).fetchone()
        
        # Get full vehicle info with checkout status
        vehicle_full = conn.execute('''
            SELECT kf.*, c.id as checkout_id
            FROM key_fobs kf
            LEFT JOIN checkouts c ON kf.id = c.fob_id AND c.checked_in_at IS NULL
            WHERE kf.id = ?
        ''', (vehicle['id'],)).fetchone()
        
        try:
            # If currently checked out, check it in first
            if vehicle_full['checkout_id']:
                conn.execute('UPDATE checkouts SET checked_in_at = ? WHERE id = ?',
                            (datetime.now(chicago_tz), vehicle_full['checkout_id']))
            
            # Check out to The Barns
            conn.execute('INSERT INTO checkouts (user_id, fob_id, kiosk_id, checked_out_at) VALUES (?, ?, ?, ?)',
                        (barns_user['id'], vehicle['id'], self.kiosk_id, datetime.now(chicago_tz)))
            conn.commit()
            conn.close()
            
            print("🔔 About to call notify_server...")
            self.notify_server()
            print("✅ notify_server completed")
            
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
            # **NEW: Check if in bulk checkout mode**
            if self.bulk_checkout_mode and not self.current_user:
                conn = get_db()
                user = conn.execute('SELECT * FROM users WHERE card_id = ? COLLATE NOCASE AND is_active = 1', 
                               (card_id,)).fetchone()
                conn.close()
        
                if not user:
                    self.show_error("Unknown card. Please register at the admin panel.")
                    return
        
            self.current_user = dict(user)
            self.show_bulk_scanning()
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

        # Check if in bulk checkout mode
        if self.bulk_checkout_mode and self.current_user:
            conn = get_db()
            fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE AND is_active = 1', 
                          (fob_id,)).fetchone()
            conn.close()
            if fob:
                self.add_bulk_item(dict(fob))
            else:
                self.show_error("Unknown fob")
            return

        # Check if in Barns scan mode
        if self.barns_scan_mode:
            fob = conn.execute('SELECT * FROM key_fobs WHERE fob_id = ? COLLATE NOCASE AND is_active = 1', (fob_id,)).fetchone()
            conn.close()
            
            if not fob:
                self.show_error("Equipment not found")
                return
            
            # Perform barns transfer with this fob
            self.barns_scan_mode = False
            self.perform_barns_transfer(fob)
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
            categories = ["Squad Cars", "Specialized Services Vehicles", "CID Vehicles", "Other Vehicles", "Equipment", "Key Rings"]
            
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
        
        conn = get_db()
        
        # Get all active equipment and vehicles
        all_items = conn.execute('''
            SELECT * FROM key_fobs
            WHERE is_active = 1
            ORDER BY category, vehicle_name
        ''').fetchall()
        
        conn.close()
        
        if not all_items:
            self.show_error("No equipment found")
            return
        
        # Create selection dialog
        result = [None]
        
        def on_select():
            selection = listbox.curselection()
            if selection and selection[0] in item_indices:
                actual_index = item_indices[selection[0]]
                result[0] = all_items[actual_index]
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
                  wraplength=600, justify='center').pack(pady=(0, 10))
            
            # Show expiration if set
            if existing_note['expires_at']:
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
                        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
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
        
        Label(expiration_frame, text="Date (YYYY-MM-DD):", 
              font=font.Font(size=12), bg='white').pack(side='left', padx=5)
        
        # Default to tomorrow
        chicago_tz = pytz.timezone('America/Chicago')
        tomorrow = datetime.now(chicago_tz) + timedelta(days=1)
        
        date_entry = Entry(expiration_frame, font=font.Font(size=14), width=12)
        date_entry.insert(0, tomorrow.strftime('%Y-%m-%d'))
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
                date_entry.insert(0, exp_dt.strftime('%Y-%m-%d'))
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
            conn = get_db()
            
            # Delete existing note for this fob (one note at a time)
            conn.execute('DELETE FROM notes WHERE fob_id = ?', (fob['id'],))
            
            # Insert new note
            conn.execute('''
                INSERT INTO notes (fob_id, note_text, created_at, created_by, expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (fob['id'], result['note'], datetime.now(chicago_tz).isoformat(), 'kiosk', result['expires_at']))
            
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
    import sys

    # Check for --kiosk-id argument
    kiosk_id = 'station' #default
    if '--kiosk-id' in sys.argv:
        idx = sys.argv.index('--kiosk-id')
        if idx + 1 < len(sys.argv):
            kiosk_id = sys.argv[idx + 1]

    kiosk = KioskGUI(kiosk_id=kiosk_id)
    kiosk.root.mainloop()
