import sqlite3
import os
import shutil
import hashlib
import json
from datetime import datetime, timedelta

# Handle serverless / read-only filesystem environments (e.g. Vercel, AWS Lambda)
if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
    TMP_DB = '/tmp/civiceye.db'
    bundled_db = os.path.join(os.path.dirname(__file__), 'civiceye.db')
    if not os.path.exists(TMP_DB) and os.path.exists(bundled_db):
        try:
            shutil.copy2(bundled_db, TMP_DB)
        except Exception:
            pass
    DB_PATH = TMP_DB
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), 'civiceye.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if tables already exist so we don't wipe on every serverless cold start
    check = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if check:
        # Ensure phone and city columns exist
        cursor.execute("PRAGMA table_info(users)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'phone' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        if 'city' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN city TEXT DEFAULT ''")
        conn.commit()
        conn.close()
        return

    # Drop existing tables to refresh with enhanced Water & Priority Engine schema
    cursor.execute('DROP TABLE IF EXISTS reviews')
    cursor.execute('DROP TABLE IF EXISTS timeline_events')
    cursor.execute('DROP TABLE IF EXISTS upvotes')
    cursor.execute('DROP TABLE IF EXISTS complaints')
    cursor.execute('DROP TABLE IF EXISTS wards')
    cursor.execute('DROP TABLE IF EXISTS users')

    # Users table
    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'citizen',
            department TEXT DEFAULT 'Resident',
            phone TEXT DEFAULT '',
            city TEXT DEFAULT '',
            karma_score INTEGER DEFAULT 100,
            badges TEXT DEFAULT '["Active Citizen", "Water Scout"]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3D Urban Flood Management Sectors Table
    cursor.execute('DROP TABLE IF EXISTS sectors')
    cursor.execute('''
        CREATE TABLE sectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            code TEXT NOT NULL,
            status TEXT NOT NULL,
            water_level_cm REAL NOT NULL,
            rainfall_mm REAL NOT NULL,
            risk_tier TEXT NOT NULL,
            elevation_m REAL NOT NULL,
            water_volume_m3 REAL NOT NULL,
            avg_water_loss_liters REAL NOT NULL,
            x_coord REAL NOT NULL,
            z_coord REAL NOT NULL,
            image_url TEXT NOT NULL,
            timeline_json TEXT NOT NULL,
            elevation_profile_json TEXT NOT NULL
        )
    ''')

    # Wards table
    cursor.execute('''
        CREATE TABLE wards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            zone TEXT NOT NULL,
            active_issues_count INTEGER DEFAULT 0,
            resolved_issues_count INTEGER DEFAULT 0,
            water_loss_liters REAL DEFAULT 0,
            water_saved_liters REAL DEFAULT 0,
            is_model_ward INTEGER DEFAULT 0,
            hotspot_severity TEXT DEFAULT 'Normal'
        )
    ''')

    # Complaints table
    cursor.execute('''
        CREATE TABLE complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            citizen_name TEXT,
            citizen_contact TEXT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            original_audio_lang TEXT DEFAULT 'en',
            image_url TEXT,
            resolution_image_url TEXT,
            video_url TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            address TEXT,
            landmark TEXT,
            ward TEXT DEFAULT 'Ward 4 - Central Zone',
            
            -- Water Loss & Impact Metrics
            estimated_water_loss_liters REAL DEFAULT 0,
            water_flow_rate_lph REAL DEFAULT 0,
            people_affected INTEGER DEFAULT 15,
            duplicate_reports_count INTEGER DEFAULT 0,
            duplicate_of_id INTEGER,
            
            -- AI Vision & Priority Engine
            ai_detected_category TEXT,
            ai_severity_score REAL DEFAULT 5.0,
            ai_confidence REAL DEFAULT 0.88,
            ai_analysis_notes TEXT,
            priority_score REAL DEFAULT 50.0,
            priority TEXT DEFAULT 'Medium',
            
            -- Municipal Triage & SLA
            status TEXT DEFAULT 'Submitted',
            assigned_department TEXT DEFAULT 'Water Supply & Sewerage Board',
            assigned_officer TEXT,
            sla_hours INTEGER DEFAULT 24,
            sla_deadline TIMESTAMP,
            upvotes_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Upvotes table
    cursor.execute('''
        CREATE TABLE upvotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            user_identifier TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(complaint_id, user_identifier),
            FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE
        )
    ''')

    # Reviews and Community Discussion table
    cursor.execute('''
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            user_role TEXT DEFAULT 'citizen',
            rating INTEGER DEFAULT 5,
            comment TEXT NOT NULL,
            is_verification_proof INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE
        )
    ''')

    # Timeline Audit events table
    cursor.execute('''
        CREATE TABLE timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (complaint_id) REFERENCES complaints (id) ON DELETE CASCADE
        )
    ''')

    conn.commit()

    seed_users(cursor)
    seed_wards(cursor)
    seed_sectors(cursor)
    seed_complaints(cursor)

    conn.commit()
    conn.close()

def seed_users(cursor):
    users = [
        ('Aarav Sharma', 'citizen@civic.org', hash_password('citizen123'), 'citizen', 'Resident', 340, '["Water Guardian Gold", "Neighborhood Hero"]'),
        ('Priya Patel (Director)', 'admin@civic.org', hash_password('admin123'), 'admin', 'Municipal Administration', 490, '["Chief Triage Officer", "Civic Leader"]'),
        ('Rajesh Kumar (Field Officer)', 'worker@civic.org', hash_password('worker123'), 'worker', 'Water Supply & Infrastructure', 310, '["Rapid Response Crew", "Leak Fixer Pro"]'),
        ('Sunita Rao', 'sunita@example.com', hash_password('pass123'), 'citizen', 'Resident', 215, '["Pothole Patrol", "Active Auditor"]'),
        ('Vikram Malhotra', 'vikram@example.com', hash_password('pass123'), 'citizen', 'Resident', 160, '["Eco Scout"]')
    ]
    cursor.executemany('''
        INSERT INTO users (name, email, password_hash, role, department, karma_score, badges)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', users)

def seed_wards(cursor):
    wards = [
        ('Ward 4 - Central Zone', 'Central Zone', 4, 8, 142000, 380000, 0, 'Critical Hotspot'),
        ('Ward 12 - Model Green Town', 'North Zone', 0, 14, 0, 520000, 1, 'Zero Issues - Model'),
        ('Ward 7 - South Corridor', 'South Zone', 2, 9, 36000, 240000, 0, 'Moderate'),
        ('Ward 9 - Industrial East', 'East Zone', 3, 5, 84000, 190000, 0, 'High Urgency'),
        ('Ward 2 - West Metro Belt', 'West Zone', 1, 11, 12000, 310000, 0, 'Low')
    ]
    cursor.executemany('''
        INSERT INTO wards (name, zone, active_issues_count, resolved_issues_count, water_loss_liters, water_saved_liters, is_model_ward, hotspot_severity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', wards)

def seed_sectors(cursor):
    sectors = [
        (
            'Sector 18', 'SEC-18', 'Severe Waterlogging', 42.0, 56.0, 'Severe', 14.2, 84000.0, 128000.0,
            -2.5, 1.2,
            'https://images.unsplash.com/photo-1547683905-f686c993aae5?auto=format&fit=crop&w=400&q=80',
            json.dumps([
                {"time": "Now", "level": "42 cm", "color": "red"},
                {"time": "+1 hr", "level": "46 cm", "color": "red"},
                {"time": "+3 hr", "level": "38 cm", "color": "orange"},
                {"time": "+6 hr", "level": "22 cm", "color": "yellow"},
                {"time": "+12 hr", "level": "<10 cm", "color": "green"}
            ]),
            json.dumps({"left_elev": "Higher Area (Safe) ~32m", "basin_elev": "Low-Lying Zone (Waterlogging Prone) ~14m", "right_elev": "Higher Area (Safe) ~29m", "flood_depth_cm": 42})
        ),
        (
            'Sector 21', 'SEC-21', 'Moderate', 18.0, 42.0, 'Moderate', 18.5, 28000.0, 34000.0,
            3.2, -1.8,
            'https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?auto=format&fit=crop&w=400&q=80',
            json.dumps([
                {"time": "Now", "level": "18 cm", "color": "orange"},
                {"time": "+1 hr", "level": "22 cm", "color": "orange"},
                {"time": "+3 hr", "level": "15 cm", "color": "yellow"},
                {"time": "+6 hr", "level": "8 cm", "color": "green"},
                {"time": "+12 hr", "level": "0 cm", "color": "green"}
            ]),
            json.dumps({"left_elev": "Mid Ridge ~24m", "basin_elev": "Intermediate Basin ~18m", "right_elev": "Higher Area ~28m", "flood_depth_cm": 18})
        ),
        (
            'Sector 25', 'SEC-25', 'Clear', 0.0, 18.0, 'Clear', 26.0, 0.0, 0.0,
            4.8, 3.2,
            'https://images.unsplash.com/photo-1517457373958-b7bdd4587205?auto=format&fit=crop&w=400&q=80',
            json.dumps([
                {"time": "Now", "level": "0 cm", "color": "green"},
                {"time": "+1 hr", "level": "2 cm", "color": "green"},
                {"time": "+3 hr", "level": "0 cm", "color": "green"},
                {"time": "+6 hr", "level": "0 cm", "color": "green"},
                {"time": "+12 hr", "level": "0 cm", "color": "green"}
            ]),
            json.dumps({"left_elev": "Plateau Ridge ~27m", "basin_elev": "Elevated Zone ~26m", "right_elev": "High Ridge ~30m", "flood_depth_cm": 0})
        ),
        (
            'Sector 20', 'SEC-20', 'Moderate', 24.0, 48.0, 'Moderate', 16.8, 38000.0, 45000.0,
            -5.0, 2.5,
            'https://images.unsplash.com/photo-1541888946425-d0fbb186f5f7?auto=format&fit=crop&w=400&q=80',
            json.dumps([
                {"time": "Now", "level": "24 cm", "color": "orange"},
                {"time": "+1 hr", "level": "28 cm", "color": "orange"},
                {"time": "+3 hr", "level": "20 cm", "color": "yellow"},
                {"time": "+6 hr", "level": "11 cm", "color": "yellow"},
                {"time": "+12 hr", "level": "<5 cm", "color": "green"}
            ]),
            json.dumps({"left_elev": "Safe Sector ~25m", "basin_elev": "Low Channel ~16m", "right_elev": "Safe Sector ~24m", "flood_depth_cm": 24})
        ),
        (
            'Sector 22', 'SEC-22', 'Low', 8.0, 24.0, 'Low', 22.4, 8000.0, 11000.0,
            -1.5, -4.2,
            'https://images.unsplash.com/photo-1605600659908-0ef719419d41?auto=format&fit=crop&w=400&q=80',
            json.dumps([
                {"time": "Now", "level": "8 cm", "color": "yellow"},
                {"time": "+1 hr", "level": "10 cm", "color": "yellow"},
                {"time": "+3 hr", "level": "6 cm", "color": "green"},
                {"time": "+6 hr", "level": "2 cm", "color": "green"},
                {"time": "+12 hr", "level": "0 cm", "color": "green"}
            ]),
            json.dumps({"left_elev": "High Area ~26m", "basin_elev": "Gentle Slope ~22m", "right_elev": "Safe Ridge ~25m", "flood_depth_cm": 8})
        )
    ]
    cursor.executemany('''
        INSERT INTO sectors (
            name, code, status, water_level_cm, rainfall_mm, risk_tier,
            elevation_m, water_volume_m3, avg_water_loss_liters,
            x_coord, z_coord, image_url, timeline_json, elevation_profile_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', sectors)

def seed_complaints(cursor):
    now = datetime.now()
    sample_complaints = [
        (
            'CIVIC-2026-9044', 1, 'Aarav Sharma', '+91 98765 43210',
            'Water Leakage & Rupture',
            'Massive 150mm Main Water Pipeline Burst Gushing onto Road',
            'Pressurized potable drinking water shooting 4 feet high from an underground municipal conduit rupture. Thousands of liters wasting every hour, flooding the junction and eroding road sub-base.',
            'hi',
            'https://images.unsplash.com/photo-1541888946425-d0fbb186f5f7?auto=format&fit=crop&w=800&q=80',
            None, None,
            28.6289, 77.2020,
            'Kasturba Marg junction, near Pillar 42', 'Opposite City Water Booster Station #3', 'Ward 4 - Central Zone',
            128000.0, 4800.0, 450, 4, None,
            'Water Leakage & Rupture', 9.6, 0.98,
            '{"damage_type": "Pressurized Distribution Pipe Rupture", "flow_rate_lph": 4800, "estimated_loss": "128,000 Liters", "structural_hazard": "Severe Road Cavity & Soil Erosion"}',
            96.8, 'Critical', 'In Progress', 'Water Supply & Sewerage Board', 'Rajesh Kumar (Field Officer)',
            6, (now + timedelta(hours=2)).isoformat(),
            88, (now - timedelta(hours=6)).isoformat(), (now - timedelta(hours=1)).isoformat()
        ),
        (
            'CIVIC-2026-9041', 4, 'Sunita Rao', '+91 98111 22334',
            'Water-Logged Pothole & Road Hazard',
            'Deep 2-Foot Pothole Submerged in Murky Stagnant Water',
            'Water accumulation from cracked gutter has submerged a 2-foot road crater outside school gate. Bikes are skidding into hidden trench; stagnant water is breeding mosquitoes.',
            'en',
            'https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?auto=format&fit=crop&w=800&q=80',
            None, None,
            28.6139, 77.2090,
            'Outer Ring Road near St. Xavier School', 'Near Pillar 18 Gate', 'Ward 4 - Central Zone',
            14500.0, 320.0, 210, 2, None,
            'Water-Logged Pothole & Road Hazard', 8.8, 0.94,
            '{"damage_type": "Submerged Cavity + Drainage Infiltration", "puddle_depth": "24cm", "hazard": "High Two-Wheeler Rollover Risk"}',
            86.4, 'Critical', 'In Progress', 'Roads & Infrastructure', 'Rajesh Kumar (Field Officer)',
            12, (now + timedelta(hours=7)).isoformat(),
            64, (now - timedelta(hours=10)).isoformat(), (now - timedelta(hours=2)).isoformat()
        ),
        (
            'CIVIC-2026-9047', 1, 'Aarav Sharma', '+91 98765 43210',
            'Drainage Clogging & Sewage Backflow',
            'Blocked Storm Drain Causing Toxic Wastewater Inundation',
            'Plastic and construction rubble has completely choked the storm drain culvert. Black foul-smelling sewage is flowing back onto residential street and entering ground-floor compounds.',
            'en',
            'https://images.unsplash.com/photo-1605600659908-0ef719419d41?auto=format&fit=crop&w=800&q=80',
            None, None,
            28.6219, 77.2140,
            'Sector 4 Market Lane, Connaught Area', 'Near Mother Dairy Booth', 'Ward 4 - Central Zone',
            45000.0, 1200.0, 320, 1, None,
            'Drainage Clogging & Sewage Backflow', 8.5, 0.92,
            '{"damage_type": "Culvert Blockage & Sanitary Sewage Surcharge", "biohazard": "High Pathogen Contamination Risk"}',
            89.2, 'Critical', 'Verified', 'Sanitation & Health', 'Priya Patel (Director)',
            8, (now + timedelta(hours=4)).isoformat(),
            52, (now - timedelta(hours=8)).isoformat(), (now - timedelta(hours=3)).isoformat()
        ),
        (
            'CIVIC-2026-9049', 5, 'Vikram Malhotra', '+91 98222 33445',
            'Water Leakage & Rupture',
            'Overhead Municipal Feeder Valve Leaking Constantly',
            'High-elevation pressure relief valve has been spraying clean water over the sidewalk 24/7. Water pooled on walking track.',
            'en',
            'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=800&q=80',
            None, None,
            28.6080, 77.2250,
            'Metro Station Road, Gate 2', 'Behind Central Park Footpath', 'Ward 7 - South Corridor',
            22000.0, 650.0, 85, 0, None,
            'Water Leakage & Rupture', 7.2, 0.89,
            '{"damage_type": "Defective Pressure Relief Valve", "flow_rate_lph": 650, "loss": "22,000 Liters"}',
            71.5, 'High', 'Verified', 'Water Supply & Sewerage Board', 'Rajesh Kumar (Field Officer)',
            24, (now + timedelta(hours=18)).isoformat(),
            28, (now - timedelta(hours=14)).isoformat(), (now - timedelta(hours=5)).isoformat()
        ),
        (
            'CIVIC-2026-9048', 1, 'Aarav Sharma', '+91 98765 43210',
            'Water Leakage & Rupture',
            'Ruptured 100mm Sub-Main Repaired & Water Saved! (Model Fix)',
            'Clean water leakage was flooding Sector 12 crossway. Municipal crew dispatched within 3 hours. Pipe welded, valve restored, and asphalt resurfaced.',
            'en',
            'https://images.unsplash.com/photo-1541888946425-d0fbb186f5f7?auto=format&fit=crop&w=800&q=80',
            'https://images.unsplash.com/photo-1517457373958-b7bdd4587205?auto=format&fit=crop&w=800&q=80',
            None,
            28.6180, 77.2320,
            'Civil Lines Avenue, Block B', 'Near Police Booth', 'Ward 12 - Model Green Town',
            0.0, 0.0, 500, 5, None,
            'Water Leakage & Rupture', 9.1, 0.96,
            '{"repair_status": "Successful Pipeline Trench Patch & Pressure Test Passed", "water_saved_daily": "95,000 Liters/day"}',
            94.0, 'Critical', 'Resolved', 'Water Supply & Sewerage Board', 'Rajesh Kumar (Field Officer)',
            6, (now - timedelta(hours=8)).isoformat(),
            115, (now - timedelta(days=2)).isoformat(), (now - timedelta(hours=4)).isoformat()
        ),
        (
            'CIVIC-2026-9043', 4, 'Sunita Rao', '+91 98111 22334',
            'Streetlight & Power',
            'Submerged Streetlight Junction Box Posing Electrocution Risk',
            'Rainwater puddle submerged an open electrical junction box for 4 streetlights. Sparks observed during vehicle transit.',
            'hi',
            'https://images.unsplash.com/photo-1508873535684-277a3cbcc4e8?auto=format&fit=crop&w=800&q=80',
            None, None,
            28.6110, 77.2180,
            'Greenway Cycle Track, Ward 7', 'Opposite Botanical Garden', 'Ward 7 - South Corridor',
            0.0, 0.0, 140, 0, None,
            'Streetlight & Power', 8.9, 0.92,
            '{"damage_type": "Submerged Live Electrical Terminal", "hazard": "Immediate Public Electrocution Hazard"}',
            88.5, 'Critical', 'In Progress', 'Electrical & Public Works', 'Vikram Singh',
            12, (now + timedelta(hours=5)).isoformat(),
            43, (now - timedelta(hours=9)).isoformat(), (now - timedelta(hours=2)).isoformat()
        )
    ]

    for c in sample_complaints:
        cursor.execute('''
            INSERT INTO complaints (
                tracking_id, user_id, citizen_name, citizen_contact,
                category, title, description, original_audio_lang,
                image_url, resolution_image_url, video_url, latitude, longitude,
                address, landmark, ward, estimated_water_loss_liters, water_flow_rate_lph,
                people_affected, duplicate_reports_count, duplicate_of_id,
                ai_detected_category, ai_severity_score, ai_confidence, ai_analysis_notes,
                priority_score, priority, status, assigned_department, assigned_officer,
                sla_hours, sla_deadline, upvotes_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', c)
        cid = cursor.lastrowid

        # Timeline Events
        cursor.execute('''
            INSERT INTO timeline_events (complaint_id, status, title, description, actor_name, created_at)
            VALUES (?, 'Submitted', 'Grievance Registered', 'Complaint logged with GPS coordinates and AI water-loss telemetry.', ?, ?)
        ''', (cid, c[2], c[33]))

        if c[27] in ('Verified', 'In Progress', 'Resolved'):
            cursor.execute('''
                INSERT INTO timeline_events (complaint_id, status, title, description, actor_name, created_at)
                VALUES (?, 'Verified', 'AI Priority Engine Calculation', ?, 'AI Priority Engine', ?)
            ''', (cid, f"Priority score {c[25]}/100 assigned. Water impact: {c[16]:,.0f} Liters. Fast SLA activated ({c[30]}h).", (now - timedelta(hours=4)).isoformat()))

        if c[27] in ('In Progress', 'Resolved'):
            cursor.execute('''
                INSERT INTO timeline_events (complaint_id, status, title, description, actor_name, created_at)
                VALUES (?, 'In Progress', 'Field Response Team Dispatched', ?, ?, ?)
            ''', (cid, f"Field crew deployed under {c[29]}. Heavy excavators & isolation valve operators on site.", c[29], (now - timedelta(hours=2)).isoformat()))

        if c[27] == 'Resolved':
            cursor.execute('''
                INSERT INTO timeline_events (complaint_id, status, title, description, actor_name, created_at)
                VALUES (?, 'Resolved', 'Repaired & Water Loss Halted', 'Leak plugged, pipe sleeve welded, road surface restored. Inspected by Municipal Engineer.', ?, ?)
            ''', (cid, c[29], c[34]))

            # Reviews for resolved case
            cursor.execute('''
                INSERT INTO reviews (complaint_id, user_name, user_role, rating, comment, is_verification_proof, created_at)
                VALUES (?, 'Aarav Sharma', 'citizen', 5, 'Verified! The massive water leak has completely stopped. Water pressure in our taps has also recovered. Outstanding response time!', 1, ?)
            ''', (cid, (now - timedelta(hours=3)).isoformat()))
            cursor.execute('''
                INSERT INTO reviews (complaint_id, user_name, user_role, rating, comment, is_verification_proof, created_at)
                VALUES (?, 'Sunita Rao', 'citizen', 5, 'Can confirm road is paved and dry now. Clean water is no longer going into the drain.', 1, ?)
            ''', (cid, (now - timedelta(hours=2)).isoformat()))
        else:
            cursor.execute('''
                INSERT INTO reviews (complaint_id, user_name, user_role, rating, comment, is_verification_proof, created_at)
                VALUES (?, 'Local Resident (+1)', 'citizen', 5, 'Upvoted! I live 200m away and our supply pressure dropped to zero because of this burst.', 0, ?)
            ''', (cid, (now - timedelta(hours=3)).isoformat()))
