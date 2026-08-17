import sqlite3
import os
from datetime import datetime

DATABASE = os.getenv('DB_PATH', 'key_checkout.db')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with our tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            is_available BOOLEAN DEFAULT 1,
            make TEXT,
            model TEXT,
            year TEXT
        )
    ''')
    
    # Key fobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS key_fobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id TEXT UNIQUE NOT NULL,
            vehicle_name TEXT NOT NULL,
	    category TEXT DEFAULT 'Vehicle',	
            location TEXT DEFAULT 'Station',
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            is_available BOOLEAN DEFAULT 1,
            make TEXT,
            model TEXT,
            year TEXT
        )
    ''')
    
    # Checkouts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checkouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fob_id INTEGER NOT NULL,
            checked_out_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checked_in_at TIMESTAMP NULL,
            kiosk_id TEXT DEFAULT 'kiosk1',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (fob_id) REFERENCES key_fobs(id)
        )
    ''')
    
    # Admin users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Create reservations table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL,
            user_id INTEGER,
            reserved_for_name TEXT,
            reserved_datetime TEXT NOT NULL,
            display_hours_before INTEGER DEFAULT 24,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            end_datetime TEXT,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Create notes table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL UNIQUE,
            note_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL,
            inspector TEXT NOT NULL,
            inspected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            mileage TEXT,
            fuel_level TEXT,
            exterior_damage INTEGER DEFAULT 0,
            exterior_damage_notes TEXT,
            radio_present INTEGER DEFAULT 1,
            laptop_present INTEGER DEFAULT 1,
            lights_working INTEGER DEFAULT 1,
            overall_status TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vehicle_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fob_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            shift TEXT NOT NULL,
            FOREIGN KEY (fob_id) REFERENCES key_fobs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

def run_migrations():
    """Run any pending database migrations"""
    conn = get_db()
    
    # Create migrations table if it doesn't exist
    conn.execute('''
        CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    # Define all migrations in order
    migrations = [
        ('001_add_is_available_to_key_fobs', 
         'ALTER TABLE key_fobs ADD COLUMN is_available BOOLEAN DEFAULT 1'),
        ('002_add_make_model_year_to_key_fobs', [
            'ALTER TABLE key_fobs ADD COLUMN make TEXT',
            'ALTER TABLE key_fobs ADD COLUMN model TEXT',
            'ALTER TABLE key_fobs ADD COLUMN year TEXT',
        ]),
        ('003_add_end_datetime_to_reservations',
         'ALTER TABLE reservations ADD COLUMN end_datetime TEXT'),
        ('004_add_created_by_to_notes',
         'ALTER TABLE notes ADD COLUMN created_by TEXT'),
        ('005_create_vehicle_assignments', '''
            CREATE TABLE IF NOT EXISTS vehicle_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fob_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                shift TEXT NOT NULL,
                FOREIGN KEY (fob_id) REFERENCES key_fobs (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        '''),
        ('006_drop_old_inspections',
         'DROP TABLE IF EXISTS inspections'),
        ('007_create_cleanliness_inspections', '''
            CREATE TABLE IF NOT EXISTS cleanliness_inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fob_id INTEGER NOT NULL,
                inspector TEXT NOT NULL,
                inspected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                exterior_clean INTEGER DEFAULT 0,
                interior_vacuumed INTEGER DEFAULT 0,
                wiped_dashboard INTEGER DEFAULT 0,
                wiped_center_console INTEGER DEFAULT 0,
                wiped_windows INTEGER DEFAULT 0,
                wiped_interior_doors INTEGER DEFAULT 0,
                wiped_backseats INTEGER DEFAULT 0,
                wiped_keyboard_mdc INTEGER DEFAULT 0,
                comments TEXT,
                FOREIGN KEY (fob_id) REFERENCES key_fobs (id)
            )
        '''),
        ('008_create_quarterly_inspections', '''
            CREATE TABLE IF NOT EXISTS quarterly_inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fob_id INTEGER NOT NULL,
                inspector TEXT NOT NULL,
                inspected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                registration_current INTEGER DEFAULT 0,
                tires_inflated INTEGER DEFAULT 0,
                compartment_clean INTEGER DEFAULT 0,
                light_bar_working INTEGER DEFAULT 0,
                mdc_working INTEGER DEFAULT 0,
                radio_working INTEGER DEFAULT 0,
                radar_working INTEGER DEFAULT 0,
                scanner_working INTEGER DEFAULT 0,
                axon_camera_working INTEGER DEFAULT 0,
                spotlight_working INTEGER DEFAULT 0,
                seatbelts_working INTEGER DEFAULT 0,
                headlights_working INTEGER DEFAULT 0,
                trunk_clean INTEGER DEFAULT 0,
                spare_tire_inflated INTEGER DEFAULT 0,
                ar15_present INTEGER DEFAULT 0,
                backpack_present INTEGER DEFAULT 0,
                phone_charger_present INTEGER DEFAULT 0,
                evidence_bag_present INTEGER DEFAULT 0,
                aed_present INTEGER DEFAULT 0,
                tuning_forks_present INTEGER DEFAULT 0,
                ice_scraper_present INTEGER DEFAULT 0,
                firstaid_large_gloves INTEGER DEFAULT 0,
                firstaid_cloth_tape INTEGER DEFAULT 0,
                firstaid_trauma_shears INTEGER DEFAULT 0,
                firstaid_bandaids INTEGER DEFAULT 0,
                firstaid_gauze INTEGER DEFAULT 0,
                firstaid_alcohol_prep INTEGER DEFAULT 0,
                firstaid_tourniquets INTEGER DEFAULT 0,
                firstaid_chest_seals INTEGER DEFAULT 0,
                firstaid_sroll_gauze INTEGER DEFAULT 0,
                bio_hazard_kit INTEGER DEFAULT 0,
                printer_paper INTEGER DEFAULT 0,
                tape_measure INTEGER DEFAULT 0,
                emergency_blanket INTEGER DEFAULT 0,
                fire_extinguisher INTEGER DEFAULT 0,
                traffic_vest INTEGER DEFAULT 0,
                ripp_restraint INTEGER DEFAULT 0,
                red_cone INTEGER DEFAULT 0,
                barrier_tape INTEGER DEFAULT 0,
                pet_carrier INTEGER DEFAULT 0,
                red_paint INTEGER DEFAULT 0,
                code100_mask INTEGER DEFAULT 0,
                riot_baton INTEGER DEFAULT 0,
                sani_wipes INTEGER DEFAULT 0,
                sharps_container INTEGER DEFAULT 0,
                stop_sticks INTEGER DEFAULT 0,
                water_rescue_bag INTEGER DEFAULT 0,
                window_punch INTEGER DEFAULT 0,
                spit_hood INTEGER DEFAULT 0,
                citation_book INTEGER DEFAULT 0,
                parking_ticket_book INTEGER DEFAULT 0,
                comments TEXT,
                FOREIGN KEY (fob_id) REFERENCES key_fobs (id)
            )
        '''),
    ]
    
    for name, sql in migrations:
        # Check if already applied
        already_done = conn.execute(
            'SELECT id FROM migrations WHERE name = ?', (name,)
        ).fetchone()
        
        if not already_done:
            try:
                if isinstance(sql, list):
                    for s in sql:
                        try:
                            conn.execute(s)
                        except Exception as e:
                            print(f"  Step failed (may already exist): {e}")
                else:
                    try:
                        conn.execute(sql)
                    except Exception as e:
                        print(f"  Failed (may already exist): {e}")
                conn.commit()
                conn.execute('INSERT INTO migrations (name) VALUES (?)', (name,))
                conn.commit()
                print(f"Migration applied: {name}")
            except Exception as e:
                print(f"Migration {name} error: {e}")
        
    conn.close()

if __name__ == '__main__':
    init_db()
    run_migrations()
