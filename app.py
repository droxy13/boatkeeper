"""
BoatKeeper — Marina Caretaker Management System
Complete vessel inspection, maintenance, and owner communication platform.
"""
import os
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import json

# Determine database type: PostgreSQL on Render, SQLite locally
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith('postgres')

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'boatkeeper-secret-key-change-in-production')
if not USE_POSTGRES:
    app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boatkeeper.db')

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access BoatKeeper.'

# ── Database Helpers ──────────────────────────────────────────────────

def get_db():
    """Get a database connection (PostgreSQL or SQLite)."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        # Wrap execute to use RealDictCursor by default
        original_execute = conn.cursor
        def wrapped_cursor(*args, **kwargs):
            if 'cursor_factory' not in kwargs:
                kwargs['cursor_factory'] = psycopg2.extras.RealDictCursor
            return original_execute(*args, **kwargs)
        conn.cursor = wrapped_cursor
        # Create a execute method that uses the wrapped cursor
        def wrapped_execute(sql, params=None):
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur
        conn.execute = wrapped_execute
        return conn
    else:
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

def get_cursor(db):
    """Get a cursor with dict-like row support."""
    if USE_POSTGRES:
        return db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return db.cursor()

def close_db(conn):
    """Close a database connection."""
    if conn:
        conn.close()

def row_to_dict(row):
    """Convert a row from either PostgreSQL or SQLite to a dict."""
    if hasattr(row, 'keys'):
        return dict(row)
    return row

def _get_columns(db, table):
    """Get column names for a table (works for both PostgreSQL and SQLite)."""
    if USE_POSTGRES:
        cols = db.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = %s
        """, (table,)).fetchall()
        return [c[0] for c in cols]
    else:
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        return [row['name'] for row in info]

def _add_column_if_missing(db, table, column, col_def):
    """Add a column to a table only if it doesn't already exist."""
    try:
        columns = _get_columns(db, table)
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            db.commit()
            print(f"Added column {column} to {table}")
    except Exception as e:
        print(f"Migration warning for {table}.{column}: {e}")

def _table_exists(db, table):
    """Check if a table exists (works for both PostgreSQL and SQLite)."""
    try:
        if USE_POSTGRES:
            result = db.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table,)).fetchone()
            return result[0]
        else:
            result = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            return result is not None
    except Exception:
        return False

def _create_tables_sqlite(db):
    """Create all tables using SQLite syntax."""
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            full_name TEXT,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS boats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            hull_number TEXT DEFAULT '',
            length_m REAL DEFAULT 0,
            type TEXT DEFAULT '',
            mooring_position TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            owner_name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            maintenance_type TEXT DEFAULT 'General',
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'Needed',
            priority TEXT DEFAULT 'Normal',
            due_date TEXT,
            started_date TEXT,
            completed_date TEXT,
            notes TEXT DEFAULT '',
            cost REAL DEFAULT 0.0,
            engine_hours REAL DEFAULT 0,
            fluid_level TEXT DEFAULT '',
            filter_condition TEXT DEFAULT '',
            battery_status TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS planning_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            boat_id INTEGER,
            planned_start TEXT,
            planned_end TEXT,
            status TEXT DEFAULT 'Draft',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            inspection_date TEXT NOT NULL,
            inspector_id INTEGER,
            weather TEXT DEFAULT '',
            overall_status TEXT DEFAULT 'Pass',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (inspector_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS inspection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            item_name TEXT NOT NULL,
            item_description TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            notes TEXT DEFAULT '',
            photo_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            incident_type TEXT DEFAULT 'Damage',
            severity TEXT DEFAULT 'Low',
            description TEXT NOT NULL,
            incident_date TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            notes TEXT DEFAULT '',
            photo_path TEXT DEFAULT '',
            cost REAL DEFAULT 0.0,
            reported_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (reported_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            cert_type TEXT NOT NULL,
            cert_name TEXT NOT NULL,
            issue_date TEXT,
            expiry_date TEXT,
            status TEXT DEFAULT 'Valid',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            alert_type TEXT DEFAULT 'Maintenance',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            alert_date TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            related_id INTEGER,
            related_table TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            report_type TEXT DEFAULT 'Status',
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            report_date TEXT NOT NULL,
            sent_to_owner INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS engine_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            total_hours REAL NOT NULL,
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
    ''')

def _create_tables_postgres(db):
    """Create all tables using PostgreSQL syntax."""
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'employee',
            full_name VARCHAR(255),
            email VARCHAR(255) DEFAULT '',
            phone VARCHAR(50) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS boats (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            model VARCHAR(255) DEFAULT '',
            brand VARCHAR(255) DEFAULT '',
            year INTEGER DEFAULT 0,
            hull_number VARCHAR(100) DEFAULT '',
            length_m REAL DEFAULT 0,
            type VARCHAR(100) DEFAULT '',
            mooring_position VARCHAR(100) DEFAULT '',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS owners (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            owner_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) DEFAULT '',
            phone VARCHAR(50) DEFAULT '',
            address TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS maintenance (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            maintenance_type VARCHAR(100) DEFAULT 'General',
            category VARCHAR(100) DEFAULT '',
            status VARCHAR(50) DEFAULT 'Needed',
            priority VARCHAR(50) DEFAULT 'Normal',
            due_date VARCHAR(50),
            started_date VARCHAR(50),
            completed_date VARCHAR(50),
            notes TEXT DEFAULT '',
            cost REAL DEFAULT 0.0,
            engine_hours REAL DEFAULT 0,
            fluid_level VARCHAR(255) DEFAULT '',
            filter_condition VARCHAR(255) DEFAULT '',
            battery_status VARCHAR(255) DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS planning_docs (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            boat_id INTEGER,
            planned_start VARCHAR(50),
            planned_end VARCHAR(50),
            status VARCHAR(50) DEFAULT 'Draft',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS inspections (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            inspection_date VARCHAR(50) NOT NULL,
            inspector_id INTEGER,
            weather VARCHAR(255) DEFAULT '',
            overall_status VARCHAR(50) DEFAULT 'Pass',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (inspector_id) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS inspection_items (
            id SERIAL PRIMARY KEY,
            inspection_id INTEGER NOT NULL,
            category VARCHAR(255) NOT NULL,
            item_name VARCHAR(255) NOT NULL,
            item_description TEXT DEFAULT '',
            status VARCHAR(50) DEFAULT 'Pending',
            notes TEXT DEFAULT '',
            photo_path VARCHAR(255) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            incident_type VARCHAR(100) DEFAULT 'Damage',
            severity VARCHAR(50) DEFAULT 'Low',
            description TEXT NOT NULL,
            incident_date VARCHAR(50) NOT NULL,
            status VARCHAR(50) DEFAULT 'Open',
            notes TEXT DEFAULT '',
            photo_path VARCHAR(255) DEFAULT '',
            cost REAL DEFAULT 0.0,
            reported_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (reported_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS certificates (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            cert_type VARCHAR(100) NOT NULL,
            cert_name VARCHAR(255) NOT NULL,
            issue_date VARCHAR(50),
            expiry_date VARCHAR(50),
            status VARCHAR(50) DEFAULT 'Valid',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            alert_type VARCHAR(100) DEFAULT 'Maintenance',
            title VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            alert_date VARCHAR(50) NOT NULL,
            is_read INTEGER DEFAULT 0,
            related_id INTEGER,
            related_table VARCHAR(100) DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            report_type VARCHAR(100) DEFAULT 'Status',
            title VARCHAR(255) NOT NULL,
            content TEXT DEFAULT '',
            report_date VARCHAR(50) NOT NULL,
            sent_to_owner INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()
    db.execute('''
        CREATE TABLE IF NOT EXISTS engine_logs (
            id SERIAL PRIMARY KEY,
            boat_id INTEGER NOT NULL,
            log_date VARCHAR(50) NOT NULL,
            total_hours REAL NOT NULL,
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (boat_id) REFERENCES boats(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    '''); db.commit()

def init_db():
    """Initialize the database with all tables and default admin user."""
    db = get_db()
    
    # Create tables using the appropriate syntax
    if USE_POSTGRES:
        _create_tables_postgres(db)
    else:
        _create_tables_sqlite(db)
    
    # Schema migration: add missing columns
    _add_column_if_missing(db, 'boats', 'model', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'brand', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'year', "INTEGER DEFAULT 0")
    _add_column_if_missing(db, 'boats', 'hull_number', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'length_m', "REAL DEFAULT 0")
    _add_column_if_missing(db, 'boats', 'type', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'mooring_position', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'notes', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'boats', 'created_by', 'INTEGER')

    _add_column_if_missing(db, 'maintenance', 'maintenance_type', "TEXT DEFAULT 'General'")
    _add_column_if_missing(db, 'maintenance', 'category', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'maintenance', 'priority', "TEXT DEFAULT 'Normal'")
    _add_column_if_missing(db, 'maintenance', 'started_date', 'TEXT')
    _add_column_if_missing(db, 'maintenance', 'completed_date', 'TEXT')
    _add_column_if_missing(db, 'maintenance', 'cost', "REAL DEFAULT 0.0")
    _add_column_if_missing(db, 'maintenance', 'engine_hours', "REAL DEFAULT 0")
    _add_column_if_missing(db, 'maintenance', 'fluid_level', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'maintenance', 'filter_condition', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'maintenance', 'battery_status', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'maintenance', 'created_by', 'INTEGER')
    _add_column_if_missing(db, 'maintenance', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    _add_column_if_missing(db, 'inspections', 'inspector_id', 'INTEGER')
    _add_column_if_missing(db, 'inspections', 'weather', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'inspections', 'overall_status', "TEXT DEFAULT 'Pass'")

    _add_column_if_missing(db, 'incidents', 'incident_type', "TEXT DEFAULT 'Damage'")
    _add_column_if_missing(db, 'incidents', 'severity', "TEXT DEFAULT 'Low'")
    _add_column_if_missing(db, 'incidents', 'photo_path', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'incidents', 'cost', "REAL DEFAULT 0.0")
    _add_column_if_missing(db, 'incidents', 'reported_by', 'INTEGER')
    _add_column_if_missing(db, 'incidents', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    _add_column_if_missing(db, 'certificates', 'issue_date', 'TEXT')
    _add_column_if_missing(db, 'certificates', 'created_by', 'INTEGER')
    _add_column_if_missing(db, 'certificates', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    _add_column_if_missing(db, 'users', 'email', "TEXT DEFAULT ''")
    _add_column_if_missing(db, 'users', 'phone', "TEXT DEFAULT ''")

    _add_column_if_missing(db, 'planning_docs', 'boat_id', 'INTEGER')
    _add_column_if_missing(db, 'planning_docs', 'created_by', 'INTEGER')
    _add_column_if_missing(db, 'planning_docs', 'updated_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    _add_column_if_missing(db, 'reports', 'sent_to_owner', "INTEGER DEFAULT 0")
    _add_column_if_missing(db, 'reports', 'created_by', 'INTEGER')

    _add_column_if_missing(db, 'engine_logs', 'created_by', 'INTEGER')

    db.commit()

    # Create default admin user if not exists
    try:
        row = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not row:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                ('admin', generate_password_hash('admin123'), 'admin', 'Administrator')
            )
            print("Default admin created: username='admin', password='admin123'")
            print("Please change the password after first login!")
    except Exception:
        pass

    db.commit()
    db.close()

# ── Inspection Checklist Definitions ──────────────────────────────────

INSPECTION_CATEGORIES = {
    'Exterior & Hull': [
        ('Hull & Topsides', 'Check for damage or osmosis'),
        ('Hull & Underwater Gear', 'Annual inspection of bottom paint condition (antifouling)'),
        ('Anodes', 'Inspect zincs'),
        ('Seacocks', 'Verify closed/secured (and periodic opening/closing to prevent seizing)'),
        ('Bilges', 'Check pumps and dry compartments'),
    ],
    'Mooring, Deck & Rigging': [
        ('Mooring & Deck', 'Check lines, fenders, tension, and placement'),
        ('Anchor & Windlass', 'Inspect chain, breakers, lubricate, and test motor/remote control'),
        ('Hatches', 'Ensure watertight seals'),
        ('Deck Gear', 'Inspect cleats and rails'),
        ('Rigging & Deck (Sailing)', 'Visual inspection of standing/running rigging (shrouds, stays, spreaders, cotter pins) and checking sheets/halyards for wear or chafing'),
    ],
    'Engine & Mechanical': [
        ('Engine & Mechanical', 'Check engine oil dipstick level, coolant expansion tank, raw water strainer, belts, and fuel filter sediment bowl'),
        ('Engine Hours', 'Record operating hours'),
    ],
    'Electrical & Electronics': [
        ('Electrical', 'Check shore power cables, inlets, battery voltage, terminals, and set proper main breaker OFF/ON states'),
        ('Navigation & Electronics', 'Verify GPS/plotter, AIS operation, chart updates, magnetic compass deviation/alignment, and test navigation lights (masthead, port, starboard, stern)'),
    ],
    'Interior, Safety & Documentation': [
        ('Interior & Safety', 'Check galley/fridge cleanliness, water tank levels, head valves, and verify fire extinguisher pressure/tags'),
        ('Spare Parts & Certificates', 'Track onboard spare parts inventory and monitor expiration dates for certificates, safety equipment (liferaft, EPIRB, flare packs, fire extinguishers)'),
        ('Wi-Fi & Connectivity', 'Check onboard router/modem power, data SIM card status, and marine antenna connections'),
        ('Lighting & Bulbs', 'Test interior cabin lights, reading lamps, and deck courtesy lights'),
        ('Gas System', 'Verify propane/LPG locker drain, cylinder valve shut-off status, and leak detector function'),
        ('Dinghy & Outboard', 'Check tender inflation, fuel level, outboard motor run-status, and security/towing lines'),
        ('Emergency Steering', 'Inspect emergency tiller placement, steering quadrant, and autopilot backup connections'),
        ('Ventilation & Moisture', 'Check for dampness, run solar vents or dehumidifiers, and ensure no musty odor buildup in closed cabins'),
    ],
}

# ── User Model ────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username, role, full_name, email='', phone=''):
        self.id = id
        self.username = username
        self.role = role
        self.full_name = full_name
        self.email = email
        self.phone = phone

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if row:
        d = dict(row)
        return User(d['id'], d['username'], d['role'], d['full_name'], d.get('email', ''), d.get('phone', ''))
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ── Auth Routes ───────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        db.close()

        if row and check_password_hash(row['password_hash'], password):
            d = dict(row)
            user = User(d['id'], d['username'], d['role'], d['full_name'], d.get('email', ''), d.get('phone', ''))
            login_user(user)
            flash(f"Welcome back, {d['full_name'] or username}!", 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ── Admin Routes ──────────────────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    stats = {
        'boats': db.execute("SELECT COUNT(*) as c FROM boats").fetchone()['c'],
        'owners': db.execute("SELECT COUNT(*) as c FROM owners").fetchone()['c'],
        'maintenance': db.execute("SELECT COUNT(*) as c FROM maintenance").fetchone()['c'],
        'inspections': db.execute("SELECT COUNT(*) as c FROM inspections").fetchone()['c'],
        'incidents': db.execute("SELECT COUNT(*) as c FROM incidents").fetchone()['c'],
        'planning': db.execute("SELECT COUNT(*) as c FROM planning_docs").fetchone()['c'],
        'certificates': db.execute("SELECT COUNT(*) as c FROM certificates").fetchone()['c'],
    }
    db.close()
    return render_template('admin.html', users=users, stats=stats)

@app.route('/admin/user/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'employee')
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()

    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('admin_panel'))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email, phone) VALUES (?, ?, ?, ?, ?, ?)",
            (username, generate_password_hash(password), role, full_name, email, phone)
        )
        db.commit()
        flash(f"User '{username}' created successfully.", 'success')
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            flash('Username already exists.', 'error')
        else:
            flash(f'Error creating user: {e}', 'error')
    db.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_panel'))

    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    flash('User deleted.', 'success')
    return redirect(url_for('admin_panel'))

# ── Main Dashboard ────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    maintenance = db.execute(
        "SELECT m.*, b.name as boat_name FROM maintenance m "
        "LEFT JOIN boats b ON m.boat_id = b.id "
        "ORDER BY CASE m.priority WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 WHEN 'Normal' THEN 3 WHEN 'Low' THEN 4 END, "
        "m.due_date ASC"
    ).fetchall()
    alerts = db.execute(
        "SELECT a.*, b.name as boat_name FROM alerts a "
        "LEFT JOIN boats b ON a.boat_id = b.id "
        "WHERE a.is_read = 0 ORDER BY a.alert_date ASC"
    ).fetchall()
    incidents = db.execute(
        "SELECT i.*, b.name as boat_name FROM incidents i "
        "LEFT JOIN boats b ON i.boat_id = b.id "
        "WHERE i.status = 'Open' ORDER BY i.incident_date DESC"
    ).fetchall()
    expiring_certs = db.execute(
        "SELECT c.*, b.name as boat_name FROM certificates c "
        "LEFT JOIN boats b ON c.boat_id = b.id "
        "WHERE c.expiry_date IS NOT NULL AND c.expiry_date != '' "
        "AND c.expiry_date <= date('now', '+30 days') "
        "ORDER BY c.expiry_date ASC"
    ).fetchall()
    db.close()

    # Stats
    needed = sum(1 for m in maintenance if m['status'] == 'Needed')
    in_progress = sum(1 for m in maintenance if m['status'] == 'In Progress')
    done = sum(1 for m in maintenance if m['status'] == 'Done')
    urgent = sum(1 for m in maintenance if m['priority'] == 'Urgent' and m['status'] != 'Done')
    unread_alerts = len(alerts)
    open_incidents = len(incidents)

    return render_template('index.html',
                          boats=boats, maintenance=maintenance, alerts=alerts,
                          incidents=incidents, expiring_certs=expiring_certs,
                          needed=needed, in_progress=in_progress, done=done,
                          urgent=urgent, unread_alerts=unread_alerts,
                          open_incidents=open_incidents,
                          inspection_categories=INSPECTION_CATEGORIES)

# ── Boat Routes ───────────────────────────────────────────────────────

@app.route('/boats', methods=['GET', 'POST'])
@login_required
def boats():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Boat name is required.', 'error')
            return redirect(url_for('boats'))

        db = get_db()
        boat_id = db.execute(
            "INSERT INTO boats (name, model, brand, year, hull_number, length_m, type, mooring_position, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, request.form.get('model', ''), request.form.get('brand', ''),
             int(request.form.get('year', 0) or 0), request.form.get('hull_number', ''),
             float(request.form.get('length_m', 0) or 0), request.form.get('type', ''),
             request.form.get('mooring_position', ''), request.form.get('notes', ''),
             current_user.id)
        ).lastrowid
        db.commit()

        # If owner info provided, create owner record
        owner_name = request.form.get('owner_name', '').strip()
        if owner_name:
            db.execute(
                "INSERT INTO owners (boat_id, owner_name, email, phone, address, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (boat_id, owner_name, request.form.get('owner_email', ''),
                 request.form.get('owner_phone', ''), request.form.get('owner_address', ''),
                 request.form.get('owner_notes', ''))
            )
        db.commit()
        db.close()
        flash(f"Boat '{name}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT b.*, o.owner_name, o.email as owner_email, o.phone as owner_phone "
                       "FROM boats b LEFT JOIN owners o ON b.id = o.boat_id ORDER BY b.name").fetchall()
    db.close()
    return render_template('boats.html', boats=boats)

@app.route('/boats/<int:boat_id>/edit', methods=['POST'])
@login_required
def edit_boat(boat_id):
    name = request.form.get('name', '').strip()
    if not name:
        flash('Boat name is required.', 'error')
        return redirect(url_for('boats'))

    db = get_db()
    db.execute(
        "UPDATE boats SET name=?, model=?, brand=?, year=?, hull_number=?, length_m=?, type=?, mooring_position=?, notes=? WHERE id=?",
        (name, request.form.get('model', ''), request.form.get('brand', ''),
         int(request.form.get('year', 0) or 0), request.form.get('hull_number', ''),
         float(request.form.get('length_m', 0) or 0), request.form.get('type', ''),
         request.form.get('mooring_position', ''), request.form.get('notes', ''), boat_id)
    )

    # Update or create owner
    owner_name = request.form.get('owner_name', '').strip()
    if owner_name:
        existing = db.execute("SELECT id FROM owners WHERE boat_id = ?", (boat_id,)).fetchone()
        if existing:
            db.execute(
                "UPDATE owners SET owner_name=?, email=?, phone=?, address=?, notes=? WHERE boat_id=?",
                (owner_name, request.form.get('owner_email', ''), request.form.get('owner_phone', ''),
                 request.form.get('owner_address', ''), request.form.get('owner_notes', ''), boat_id)
            )
        else:
            db.execute(
                "INSERT INTO owners (boat_id, owner_name, email, phone, address, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (boat_id, owner_name, request.form.get('owner_email', ''),
                 request.form.get('owner_phone', ''), request.form.get('owner_address', ''),
                 request.form.get('owner_notes', ''))
            )
    db.commit()
    db.close()
    flash(f"Boat '{name}' updated.", 'success')
    return redirect(url_for('index'))

@app.route('/boats/<int:boat_id>/delete', methods=['POST'])
@login_required
def delete_boat(boat_id):
    db = get_db()
    boat = db.execute("SELECT name FROM boats WHERE id = ?", (boat_id,)).fetchone()
    if boat:
        db.execute("DELETE FROM boats WHERE id = ?", (boat_id,))
        db.commit()
        flash(f"Boat '{boat['name']}' deleted.", 'success')
    db.close()
    return redirect(url_for('index'))

# ── Maintenance Routes ────────────────────────────────────────────────

@app.route('/maintenance', methods=['GET', 'POST'])
@login_required
def maintenance():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('maintenance'))

        description = request.form.get('description', '').strip()
        if not description:
            flash('Description is required.', 'error')
            return redirect(url_for('maintenance'))

        due_date = request.form.get('due_date', '') or None
        cost_str = request.form.get('cost', '0')
        try:
            cost = float(cost_str) if cost_str else 0.0
        except ValueError:
            cost = 0.0
        engine_hours_str = request.form.get('engine_hours', '0')
        try:
            engine_hours = float(engine_hours_str) if engine_hours_str else 0.0
        except ValueError:
            engine_hours = 0.0

        db = get_db()
        db.execute(
            "INSERT INTO maintenance (boat_id, description, maintenance_type, category, status, priority, "
            "due_date, notes, cost, engine_hours, fluid_level, filter_condition, battery_status, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(boat_id), description, request.form.get('maintenance_type', 'General'),
             request.form.get('category', ''), 'Needed', request.form.get('priority', 'Normal'),
             due_date, request.form.get('notes', ''), cost, engine_hours,
             request.form.get('fluid_level', ''), request.form.get('filter_condition', ''),
             request.form.get('battery_status', ''), current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Task '{description}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    maintenance = db.execute(
        "SELECT m.*, b.name as boat_name FROM maintenance m "
        "LEFT JOIN boats b ON m.boat_id = b.id ORDER BY m.due_date ASC"
    ).fetchall()
    db.close()
    return render_template('maintenance.html', boats=boats, maintenance=maintenance)

@app.route('/maintenance/<int:task_id>/edit', methods=['POST'])
@login_required
def edit_maintenance(task_id):
    due_date = request.form.get('due_date', '') or None
    cost_str = request.form.get('cost', '0')
    try:
        cost = float(cost_str) if cost_str else 0.0
    except ValueError:
        cost = 0.0
    engine_hours_str = request.form.get('engine_hours', '0')
    try:
        engine_hours = float(engine_hours_str) if engine_hours_str else 0.0
    except ValueError:
        engine_hours = 0.0

    status = request.form.get('status', 'Needed')
    started_date = request.form.get('started_date', '') or None
    completed_date = request.form.get('completed_date', '') or None

    if status == 'In Progress' and not started_date:
        started_date = datetime.now().strftime('%Y-%m-%d')
    if status == 'Done' and not completed_date:
        completed_date = datetime.now().strftime('%Y-%m-%d')
        if not started_date:
            started_date = datetime.now().strftime('%Y-%m-%d')

    db = get_db()
    db.execute(
        "UPDATE maintenance SET boat_id=?, description=?, maintenance_type=?, category=?, status=?, "
        "priority=?, due_date=?, started_date=?, completed_date=?, notes=?, cost=?, "
        "engine_hours=?, fluid_level=?, filter_condition=?, battery_status=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (int(request.form.get('boat_id', 0)), request.form.get('description', ''),
         request.form.get('maintenance_type', 'General'), request.form.get('category', ''),
         status, request.form.get('priority', 'Normal'), due_date, started_date,
         completed_date, request.form.get('notes', ''), cost, engine_hours,
         request.form.get('fluid_level', ''), request.form.get('filter_condition', ''),
         request.form.get('battery_status', ''), task_id)
    )
    db.commit()
    db.close()
    flash('Task updated.', 'success')
    return redirect(url_for('index'))

@app.route('/maintenance/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_maintenance(task_id):
    db = get_db()
    db.execute("DELETE FROM maintenance WHERE id = ?", (task_id,))
    db.commit()
    db.close()
    flash('Task deleted.', 'success')
    return redirect(url_for('index'))

# ── Inspection Routes ─────────────────────────────────────────────────

@app.route('/inspections', methods=['GET', 'POST'])
@login_required
def inspections():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('inspections'))

        inspection_date = request.form.get('inspection_date', datetime.now().strftime('%Y-%m-%d'))
        weather = request.form.get('weather', '')
        notes = request.form.get('notes', '')

        db = get_db()
        inspection_id = db.execute(
            "INSERT INTO inspections (boat_id, inspection_date, inspector_id, weather, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(boat_id), inspection_date, current_user.id, weather, notes)
        ).lastrowid

        # Create checklist items from form data
        for category, items in INSPECTION_CATEGORIES.items():
            for item_name, item_desc in items:
                field_prefix = f"item_{category.replace(' ', '_').replace('&', '_').replace('(', '').replace(')', '').replace(',', '')}_{item_name.replace(' ', '_').replace('(', '').replace(')', '').replace(',', '')}"
                # Simplified field name
                safe_cat = category.replace(' ', '_').replace('&', '').replace('(', '').replace(')', '').replace(',', '')
                safe_item = item_name.replace(' ', '_').replace('(', '').replace(')', '').replace(',', '').replace('/', '_')
                status_key = f"{safe_cat}_{safe_item}_status"
                notes_key = f"{safe_cat}_{safe_item}_notes"

                status = request.form.get(status_key, 'Pending')
                item_notes = request.form.get(notes_key, '')

                if status != '':
                    db.execute(
                        "INSERT INTO inspection_items (inspection_id, category, item_name, item_description, status, notes) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (inspection_id, category, item_name, item_desc, status, item_notes)
                    )

        # Determine overall status
        failed_items = db.execute(
            "SELECT COUNT(*) as c FROM inspection_items WHERE inspection_id = ? AND status = 'Fail'",
            (inspection_id,)
        ).fetchone()['c']
        overall = 'Fail' if failed_items > 0 else 'Pass'

        db.execute("UPDATE inspections SET overall_status = ? WHERE id = ?", (overall, inspection_id))
        db.commit()

        # Create alert for failed items
        if failed_items > 0:
            db.execute(
                "INSERT INTO alerts (boat_id, alert_type, title, description, alert_date, created_by) "
                "VALUES (?, 'Inspection', ?, ?, ?, ?)",
                (int(boat_id), f"Inspection failed for boat",
                 f"{failed_items} items failed inspection",
                 datetime.now().strftime('%Y-%m-%d'), current_user.id)
            )
            db.commit()

        db.close()
        flash('Inspection completed.', 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    inspection_list = db.execute(
        "SELECT i.*, b.name as boat_name, u.full_name as inspector_name FROM inspections i "
        "LEFT JOIN boats b ON i.boat_id = b.id "
        "LEFT JOIN users u ON i.inspector_id = u.id "
        "ORDER BY i.inspection_date DESC LIMIT 50"
    ).fetchall()
    db.close()
    return render_template('inspections.html', boats=boats, inspections=inspection_list,
                          categories=INSPECTION_CATEGORIES)

@app.route('/inspections/<int:inspection_id>')
@login_required
def inspection_detail(inspection_id):
    db = get_db()
    inspection = db.execute(
        "SELECT i.*, b.name as boat_name, u.full_name as inspector_name FROM inspections i "
        "LEFT JOIN boats b ON i.boat_id = b.id "
        "LEFT JOIN users u ON i.inspector_id = u.id "
        "WHERE i.id = ?", (inspection_id,)
    ).fetchone()

    items = db.execute(
        "SELECT * FROM inspection_items WHERE inspection_id = ? ORDER BY category, item_name",
        (inspection_id,)
    ).fetchall()
    db.close()

    if not inspection:
        flash('Inspection not found.', 'error')
        return redirect(url_for('inspections'))

    # Group items by category
    grouped = {}
    for item in items:
        cat = item['category']
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(dict(item))

    return render_template('inspection_detail.html', inspection=dict(inspection), items_by_category=grouped)

@app.route('/inspections/<int:inspection_id>/delete', methods=['POST'])
@login_required
def delete_inspection(inspection_id):
    db = get_db()
    db.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
    db.commit()
    db.close()
    flash('Inspection deleted.', 'success')
    return redirect(url_for('inspections'))

# ── Incident Routes ───────────────────────────────────────────────────

@app.route('/incidents', methods=['GET', 'POST'])
@login_required
def incidents():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('incidents'))

        description = request.form.get('description', '').strip()
        if not description:
            flash('Description is required.', 'error')
            return redirect(url_for('incidents'))

        incident_date = request.form.get('incident_date', datetime.now().strftime('%Y-%m-%d'))
        cost_str = request.form.get('cost', '0')
        try:
            cost = float(cost_str) if cost_str else 0.0
        except ValueError:
            cost = 0.0

        db = get_db()
        db.execute(
            "INSERT INTO incidents (boat_id, incident_type, severity, description, incident_date, notes, cost, reported_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(boat_id), request.form.get('incident_type', 'Damage'),
             request.form.get('severity', 'Low'), description, incident_date,
             request.form.get('notes', ''), cost, current_user.id)
        )
        db.commit()
        db.close()
        flash('Incident reported.', 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    incident_list = db.execute(
        "SELECT i.*, b.name as boat_name, u.full_name as reporter_name FROM incidents i "
        "LEFT JOIN boats b ON i.boat_id = b.id "
        "LEFT JOIN users u ON i.reported_by = u.id "
        "ORDER BY i.incident_date DESC"
    ).fetchall()
    db.close()
    return render_template('incidents.html', boats=boats, incidents=incident_list)

@app.route('/incidents/<int:incident_id>/edit', methods=['POST'])
@login_required
def edit_incident(incident_id):
    cost_str = request.form.get('cost', '0')
    try:
        cost = float(cost_str) if cost_str else 0.0
    except ValueError:
        cost = 0.0

    db = get_db()
    db.execute(
        "UPDATE incidents SET incident_type=?, severity=?, description=?, incident_date=?, "
        "status=?, notes=?, cost=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (request.form.get('incident_type', 'Damage'), request.form.get('severity', 'Low'),
         request.form.get('description', ''), request.form.get('incident_date', ''),
         request.form.get('status', 'Open'), request.form.get('notes', ''), cost, incident_id)
    )
    db.commit()
    db.close()
    flash('Incident updated.', 'success')
    return redirect(url_for('incidents'))

@app.route('/incidents/<int:incident_id>/delete', methods=['POST'])
@login_required
def delete_incident(incident_id):
    db = get_db()
    db.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
    db.commit()
    db.close()
    flash('Incident deleted.', 'success')
    return redirect(url_for('incidents'))

# ── Certificates Routes ───────────────────────────────────────────────

@app.route('/certificates', methods=['GET', 'POST'])
@login_required
def certificates():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('certificates'))

        cert_name = request.form.get('cert_name', '').strip()
        if not cert_name:
            flash('Certificate name is required.', 'error')
            return redirect(url_for('certificates'))

        expiry_date = request.form.get('expiry_date', '') or None
        today = datetime.now().strftime('%Y-%m-%d')
        if expiry_date:
            status = 'Expired' if expiry_date < today else 'Expiring Soon' if expiry_date <= (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d') else 'Valid'
        else:
            status = 'Valid'

        db = get_db()
        db.execute(
            "INSERT INTO certificates (boat_id, cert_type, cert_name, issue_date, expiry_date, status, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(boat_id), request.form.get('cert_type', 'Safety'), cert_name,
             request.form.get('issue_date', '') or None, expiry_date, status,
             request.form.get('notes', ''), current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Certificate '{cert_name}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    cert_list = db.execute(
        "SELECT c.*, b.name as boat_name FROM certificates c "
        "LEFT JOIN boats b ON c.boat_id = b.id "
        "ORDER BY c.expiry_date ASC"
    ).fetchall()
    db.close()
    return render_template('certificates.html', boats=boats, certificates=cert_list)

@app.route('/certificates/<int:cert_id>/edit', methods=['POST'])
@login_required
def edit_certificate(cert_id):
    expiry_date = request.form.get('expiry_date', '') or None
    today = datetime.now().strftime('%Y-%m-%d')
    if expiry_date:
        status = 'Expired' if expiry_date < today else 'Expiring Soon' if expiry_date <= (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d') else 'Valid'
    else:
        status = 'Valid'

    db = get_db()
    db.execute(
        "UPDATE certificates SET cert_type=?, cert_name=?, issue_date=?, expiry_date=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (request.form.get('cert_type', 'Safety'), request.form.get('cert_name', ''),
         request.form.get('issue_date', '') or None, expiry_date, status,
         request.form.get('notes', ''), cert_id)
    )
    db.commit()
    db.close()
    flash('Certificate updated.', 'success')
    return redirect(url_for('certificates'))

@app.route('/certificates/<int:cert_id>/delete', methods=['POST'])
@login_required
def delete_certificate(cert_id):
    db = get_db()
    db.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
    db.commit()
    db.close()
    flash('Certificate deleted.', 'success')
    return redirect(url_for('certificates'))

# ── Reports Routes ────────────────────────────────────────────────────

@app.route('/reports', methods=['GET', 'POST'])
@login_required
def reports():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('reports'))

        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('reports'))

        report_date = request.form.get('report_date', datetime.now().strftime('%Y-%m-%d'))

        db = get_db()
        db.execute(
            "INSERT INTO reports (boat_id, report_type, title, content, report_date, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(boat_id), request.form.get('report_type', 'Status'), title,
             request.form.get('content', ''), report_date, current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Report '{title}' created.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    report_list = db.execute(
        "SELECT r.*, b.name as boat_name, u.full_name as author_name FROM reports r "
        "LEFT JOIN boats b ON r.boat_id = b.id "
        "LEFT JOIN users u ON r.created_by = u.id "
        "ORDER BY r.report_date DESC"
    ).fetchall()
    db.close()
    return render_template('reports.html', boats=boats, reports=report_list)

@app.route('/reports/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    db = get_db()
    db.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    db.commit()
    db.close()
    flash('Report deleted.', 'success')
    return redirect(url_for('reports'))

# ── Engine Logs Routes ────────────────────────────────────────────────

@app.route('/engine-logs', methods=['GET', 'POST'])
@login_required
def engine_logs():
    if request.method == 'POST':
        boat_id = request.form.get('boat_id', '0')
        if not boat_id:
            flash('Please select a boat.', 'error')
            return redirect(url_for('engine_logs'))

        total_hours_str = request.form.get('total_hours', '0')
        try:
            total_hours = float(total_hours_str) if total_hours_str else 0.0
        except ValueError:
            flash('Invalid hours value.', 'error')
            return redirect(url_for('engine_logs'))

        log_date = request.form.get('log_date', datetime.now().strftime('%Y-%m-%d'))

        db = get_db()
        db.execute(
            "INSERT INTO engine_logs (boat_id, log_date, total_hours, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(boat_id), log_date, total_hours, request.form.get('notes', ''), current_user.id)
        )
        db.commit()
        db.close()
        flash('Engine log added.', 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    log_list = db.execute(
        "SELECT e.*, b.name as boat_name FROM engine_logs e "
        "LEFT JOIN boats b ON e.boat_id = b.id "
        "ORDER BY e.log_date DESC"
    ).fetchall()
    db.close()
    return render_template('engine_logs.html', boats=boats, logs=log_list)

@app.route('/engine-logs/<int:log_id>/delete', methods=['POST'])
@login_required
def delete_engine_log(log_id):
    db = get_db()
    db.execute("DELETE FROM engine_logs WHERE id = ?", (log_id,))
    db.commit()
    db.close()
    flash('Engine log deleted.', 'success')
    return redirect(url_for('engine_logs'))

# ── Alerts Routes ─────────────────────────────────────────────────────

@app.route('/alerts/mark-read/<int:alert_id>', methods=['POST'])
@login_required
def mark_alert_read(alert_id):
    db = get_db()
    db.execute("UPDATE alerts SET is_read = 1 WHERE id = ?", (alert_id,))
    db.commit()
    db.close()
    return redirect(url_for('index'))

@app.route('/alerts/mark-all-read', methods=['POST'])
@login_required
def mark_all_alerts_read():
    db = get_db()
    db.execute("UPDATE alerts SET is_read = 1 WHERE is_read = 0")
    db.commit()
    db.close()
    flash('All alerts marked as read.', 'success')
    return redirect(url_for('index'))

# ── Planning Routes ───────────────────────────────────────────────────

@app.route('/planning', methods=['GET', 'POST'])
@login_required
def planning():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('planning'))

        db = get_db()
        db.execute(
            "INSERT INTO planning_docs (title, description, boat_id, planned_start, planned_end, status, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, request.form.get('description', ''), request.form.get('boat_id', None) or None,
             request.form.get('planned_start', '') or None,
             request.form.get('planned_end', '') or None,
             request.form.get('status', 'Draft'), request.form.get('notes', ''), current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Plan '{title}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    planning_docs = db.execute(
        "SELECT p.*, b.name as boat_name FROM planning_docs p "
        "LEFT JOIN boats b ON p.boat_id = b.id "
        "ORDER BY p.planned_start ASC"
    ).fetchall()
    db.close()
    return render_template('planning.html', boats=boats, planning_docs=planning_docs)

@app.route('/planning/<int:doc_id>/edit', methods=['POST'])
@login_required
def edit_planning(doc_id):
    db = get_db()
    db.execute(
        "UPDATE planning_docs SET title=?, description=?, boat_id=?, planned_start=?, "
        "planned_end=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (request.form.get('title', ''), request.form.get('description', ''),
         request.form.get('boat_id', None) or None, request.form.get('planned_start', '') or None,
         request.form.get('planned_end', '') or None, request.form.get('status', 'Draft'),
         request.form.get('notes', ''), doc_id)
    )
    db.commit()
    db.close()
    flash('Plan updated.', 'success')
    return redirect(url_for('index'))

@app.route('/planning/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_planning(doc_id):
    db = get_db()
    db.execute("DELETE FROM planning_docs WHERE id = ?", (doc_id,))
    db.commit()
    db.close()
    flash('Plan deleted.', 'success')
    return redirect(url_for('index'))

# ── Yard Map Route ────────────────────────────────────────────────────

@app.route('/yard-map')
@login_required
def yard_map():
    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY mooring_position, name").fetchall()
    
    # Get maintenance and incident counts per boat
    boat_ids = [b['id'] for b in boats]
    boat_data = []
    for boat in boats:
        if boat['id'] in boat_ids:
            maint_needed = db.execute(
                "SELECT COUNT(*) as c FROM maintenance WHERE boat_id = ? AND status = 'Needed'",
                (boat['id'],)
            ).fetchone()['c']
            maint_progress = db.execute(
                "SELECT COUNT(*) as c FROM maintenance WHERE boat_id = ? AND status = 'In Progress'",
                (boat['id'],)
            ).fetchone()['c']
            incidents_open = db.execute(
                "SELECT COUNT(*) as c FROM incidents WHERE boat_id = ? AND status = 'Open'",
                (boat['id'],)
            ).fetchone()['c']
            
            # Determine status color
            if incidents_open > 0:
                status = 'critical'
            elif maint_needed > 0:
                status = 'warning'
            else:
                status = 'ok'
            
            boat_data.append({
                'boat': dict(boat),
                'maint_needed': maint_needed,
                'maint_progress': maint_progress,
                'incidents_open': incidents_open,
                'status': status
            })
    
    db.close()
    return render_template('yard_map.html', boats=boat_data)

# ── Statistics Route ──────────────────────────────────────────────────

@app.route('/statistics')
@login_required
def statistics():
    db = get_db()
    
    # Maintenance by status
    maint_status = [dict(r) for r in db.execute(
        "SELECT status, COUNT(*) as count FROM maintenance GROUP BY status"
    ).fetchall()]
    
    # Maintenance by type
    maint_type = [dict(r) for r in db.execute(
        "SELECT maintenance_type, COUNT(*) as count FROM maintenance GROUP BY maintenance_type"
    ).fetchall()]
    
    # Inspections over time (last 6 months)
    if USE_POSTGRES:
        inspections_monthly = [dict(r) for r in db.execute(
            "SELECT TO_CHAR(inspection_date::date, 'YYYY-MM') as month, COUNT(*) as count "
            "FROM inspections WHERE inspection_date::date >= CURRENT_DATE - INTERVAL '6 months' "
            "GROUP BY month ORDER BY month"
        ).fetchall()]
    else:
        inspections_monthly = [dict(r) for r in db.execute(
            "SELECT strftime('%Y-%m', inspection_date) as month, COUNT(*) as count "
            "FROM inspections WHERE inspection_date >= date('now', '-6 months') "
            "GROUP BY month ORDER BY month"
        ).fetchall()]
    
    # Incidents by severity
    incidents_severity = [dict(r) for r in db.execute(
        "SELECT severity, COUNT(*) as count FROM incidents GROUP BY severity"
    ).fetchall()]
    
    # Total costs
    total_maint_cost = db.execute(
        "SELECT COALESCE(SUM(cost), 0) as total FROM maintenance"
    ).fetchone()['total']
    total_incident_cost = db.execute(
        "SELECT COALESCE(SUM(cost), 0) as total FROM incidents"
    ).fetchone()['total']
    
    # Vessel types
    vessel_types = [dict(r) for r in db.execute(
        "SELECT type, COUNT(*) as count FROM boats WHERE type != '' GROUP BY type"
    ).fetchall()]
    
    # Certificates by status
    cert_status = [dict(r) for r in db.execute(
        "SELECT status, COUNT(*) as count FROM certificates GROUP BY status"
    ).fetchall()]
    
    db.close()
    
    # Pre-extract lists for JSON serialization in template
    data = {
        'maint_status_labels': [r['status'] for r in maint_status],
        'maint_status_values': [r['count'] for r in maint_status],
        'maint_type_labels': [r['maintenance_type'] for r in maint_type],
        'maint_type_values': [r['count'] for r in maint_type],
        'inspections_labels': [r['month'] for r in inspections_monthly],
        'inspections_values': [r['count'] for r in inspections_monthly],
        'incidents_labels': [r['severity'] for r in incidents_severity],
        'incidents_values': [r['count'] for r in incidents_severity],
        'vessel_labels': [r['type'] for r in vessel_types],
        'vessel_values': [r['count'] for r in vessel_types],
        'cert_labels': [r['status'] for r in cert_status],
        'cert_values': [r['count'] for r in cert_status],
    }
    
    return render_template('statistics.html',
                          total_maint_cost=total_maint_cost,
                          total_incident_cost=total_incident_cost,
                          maint_status=maint_status,
                          cert_status=cert_status,
                          **data)

# ── Export Routes ─────────────────────────────────────────────────────

@app.route('/export/json')
@login_required
def export_json():
    """Export all data as JSON for backup."""
    db = get_db()
    data = {
        'boats': [dict(r) for r in db.execute("SELECT * FROM boats").fetchall()],
        'owners': [dict(r) for r in db.execute("SELECT * FROM owners").fetchall()],
        'maintenance': [dict(r) for r in db.execute("SELECT * FROM maintenance").fetchall()],
        'inspections': [dict(r) for r in db.execute("SELECT * FROM inspections").fetchall()],
        'inspection_items': [dict(r) for r in db.execute("SELECT * FROM inspection_items").fetchall()],
        'incidents': [dict(r) for r in db.execute("SELECT * FROM incidents").fetchall()],
        'certificates': [dict(r) for r in db.execute("SELECT * FROM certificates").fetchall()],
        'engine_logs': [dict(r) for r in db.execute("SELECT * FROM engine_logs").fetchall()],
        'reports': [dict(r) for r in db.execute("SELECT * FROM reports").fetchall()],
        'planning_docs': [dict(r) for r in db.execute("SELECT * FROM planning_docs").fetchall()],
        'alerts': [dict(r) for r in db.execute("SELECT * FROM alerts").fetchall()],
    }
    db.close()
    
    response = make_response(json.dumps(data, indent=2, default=str))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename=boatkeeper_backup_{datetime.now().strftime("%Y%m%d")}.json'
    return response

@app.route('/export/csv/<string:table_name>')
@login_required
def export_csv(table_name):
    """Export a specific table as CSV."""
    allowed_tables = ['boats', 'owners', 'maintenance', 'inspections', 'inspection_items',
                      'incidents', 'certificates', 'engine_logs', 'reports', 'planning_docs']
    
    if table_name not in allowed_tables:
        flash('Invalid table name.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"SELECT * FROM {table_name}")
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        db.commit()
    else:
        cur = db.execute(f"SELECT * FROM {table_name}")
        columns = [description[0] for description in cur.description]
        rows = cur.fetchall()
    db.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(list(row))
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=boatkeeper_{table_name}_{datetime.now().strftime("%Y%m%d")}.csv'
    return response

# ── API Routes (for AJAX) ─────────────────────────────────────────────

@app.route('/api/boats')
@login_required
def api_boats():
    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    db.close()
    return jsonify([dict(b) for b in boats])

@app.route('/api/alerts/unread')
@login_required
def api_unread_alerts():
    db = get_db()
    alerts = db.execute(
        "SELECT a.*, b.name as boat_name FROM alerts a "
        "LEFT JOIN boats b ON a.boat_id = b.id "
        "WHERE a.is_read = 0 ORDER BY a.alert_date DESC"
    ).fetchall()
    db.close()
    return jsonify([dict(a) for a in alerts])

@app.route('/api/alerts/count')
@login_required
def api_alerts_count():
    """Get count of unread alerts for the bell badge."""
    db = get_db()
    
    # Count unread alerts
    unread = db.execute("SELECT COUNT(*) as c FROM alerts WHERE is_read = 0").fetchone()['c']
    
    # Count expiring certificates (within 30 days)
    expiring = db.execute(
        "SELECT COUNT(*) as c FROM certificates WHERE expiry_date IS NOT NULL "
        "AND expiry_date != '' AND expiry_date <= date('now', '+30 days')"
    ).fetchone()['c']
    
    # Count open incidents
    open_incidents = db.execute(
        "SELECT COUNT(*) as c FROM incidents WHERE status = 'Open'"
    ).fetchone()['c']
    
    db.close()
    return jsonify({'unread': unread, 'expiring': expiring, 'open_incidents': open_incidents, 'total': unread + expiring + open_incidents})

# ── Initialize and Run ────────────────────────────────────────────────

init_db()

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  BoatKeeper — Marina Caretaker System")
    print("=" * 50)
    print("  Local:   http://localhost:5000")
    print("  Network: http://<your-ip>:5000")
    print("  Admin:   username='admin', password='admin123'")
    print("  (Change password after first login!)")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)

# For production deployment (Gunicorn entry point)
application = app
