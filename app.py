"""
BoatKeeper Online — Shared web app with database.
"""
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'boatkeeper-secret-key-change-in-production')
app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boatkeeper.db')

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access BoatKeeper.'

# ── Database Helpers ──────────────────────────────────────────────────

def get_db():
    """Get a database connection."""
    import sqlite3
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initialize the database with tables and default admin user."""
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS boats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            hull_number TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boat_name TEXT NOT NULL,
            description TEXT NOT NULL,
            maintenance_type TEXT DEFAULT 'General',
            status TEXT DEFAULT 'Needed',
            priority TEXT DEFAULT 'Normal',
            due_date TEXT,
            started_date TEXT,
            completed_date TEXT,
            notes TEXT DEFAULT '',
            cost REAL DEFAULT 0.0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS planning_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            boat_name TEXT DEFAULT '',
            planned_start TEXT,
            planned_end TEXT,
            status TEXT DEFAULT 'Draft',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );
    ''')

    # Create default admin user if not exists
    try:
        db.execute("SELECT id FROM users WHERE username = 'admin'")
        if not db.fetchone():
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

# ── User Model ────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username, role, full_name):
        self.id = id
        self.username = username
        self.role = role
        self.full_name = full_name

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if row:
        return User(row['id'], row['username'], row['role'], row['full_name'])
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
            user = User(row['id'], row['username'], row['role'], row['full_name'])
            login_user(user)
            flash(f"Welcome back, {row['full_name'] or username}!", 'success')
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
        'maintenance': db.execute("SELECT COUNT(*) as c FROM maintenance").fetchone()['c'],
        'planning': db.execute("SELECT COUNT(*) as c FROM planning_docs").fetchone()['c'],
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

    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('admin_panel'))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), role, full_name)
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

# ── Main Index ────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    maintenance = db.execute(
        "SELECT * FROM maintenance ORDER BY "
        "CASE priority WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 WHEN 'Normal' THEN 3 WHEN 'Low' THEN 4 END, "
        "due_date ASC"
    ).fetchall()
    planning = db.execute("SELECT * FROM planning_docs ORDER BY planned_start ASC").fetchall()
    db.close()

    # Stats
    needed = sum(1 for m in maintenance if m['status'] == 'Needed')
    in_progress = sum(1 for m in maintenance if m['status'] == 'In Progress')
    done = sum(1 for m in maintenance if m['status'] == 'Done')
    urgent = sum(1 for m in maintenance if m['priority'] == 'Urgent' and m['status'] != 'Done')

    return render_template('index.html',
                          boats=boats, maintenance=maintenance, planning=planning,
                          needed=needed, in_progress=in_progress, done=done, urgent=urgent)

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
        db.execute(
            "INSERT INTO boats (name, model, brand, year, hull_number, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (name, request.form.get('model', ''), request.form.get('brand', ''),
             int(request.form.get('year', 0) or 0), request.form.get('hull_number', ''),
             current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Boat '{name}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
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
    old_boat = db.execute("SELECT name FROM boats WHERE id = ?", (boat_id,)).fetchone()
    db.execute(
        "UPDATE boats SET name=?, model=?, brand=?, year=?, hull_number=? WHERE id=?",
        (name, request.form.get('model', ''), request.form.get('brand', ''),
         int(request.form.get('year', 0) or 0), request.form.get('hull_number', ''), boat_id)
    )

    # Update maintenance records if boat name changed
    if old_boat and old_boat['name'] != name:
        db.execute("UPDATE maintenance SET boat_name=? WHERE boat_name=?", (name, old_boat['name']))
        db.execute("UPDATE planning_docs SET boat_name=? WHERE boat_name=?", (name, old_boat['name']))

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
        boat_name = request.form.get('boat_name', '').strip()
        description = request.form.get('description', '').strip()
        if not boat_name or not description:
            flash('Boat name and description are required.', 'error')
            return redirect(url_for('maintenance'))

        due_date = request.form.get('due_date', '') or None
        cost_str = request.form.get('cost', '0')
        try:
            cost = float(cost_str) if cost_str else 0.0
        except ValueError:
            cost = 0.0

        db = get_db()
        db.execute(
            "INSERT INTO maintenance (boat_name, description, maintenance_type, status, priority, due_date, notes, cost, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (boat_name, description, request.form.get('maintenance_type', 'General'),
             'Needed', request.form.get('priority', 'Normal'),
             due_date, request.form.get('notes', ''), cost, current_user.id)
        )
        db.commit()
        db.close()
        flash(f"Task '{description}' added.", 'success')
        return redirect(url_for('index'))

    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    maintenance = db.execute("SELECT * FROM maintenance ORDER BY due_date ASC").fetchall()
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

    status = request.form.get('status', 'Needed')
    started_date = None
    completed_date = None

    if status == 'In Progress' and not request.form.get('started_date'):
        started_date = datetime.now().strftime('%Y-%m-%d')
    elif status == 'Done':
        completed_date = datetime.now().strftime('%Y-%m-%d')
        if not request.form.get('started_date'):
            started_date = datetime.now().strftime('%Y-%m-%d')
    else:
        started_date = request.form.get('started_date', '') or None
        completed_date = request.form.get('completed_date', '') or None

    db = get_db()
    db.execute(
        "UPDATE maintenance SET boat_name=?, description=?, maintenance_type=?, status=?, "
        "priority=?, due_date=?, started_date=?, completed_date=?, notes=?, cost=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (request.form.get('boat_name', ''), request.form.get('description', ''),
         request.form.get('maintenance_type', 'General'), status,
         request.form.get('priority', 'Normal'), due_date, started_date,
         completed_date, request.form.get('notes', ''), cost, task_id)
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
            "INSERT INTO planning_docs (title, description, boat_name, planned_start, planned_end, status, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, request.form.get('description', ''), request.form.get('boat_name', ''),
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
    planning_docs = db.execute("SELECT * FROM planning_docs ORDER BY planned_start ASC").fetchall()
    db.close()
    return render_template('planning.html', boats=boats, planning_docs=planning_docs)

@app.route('/planning/<int:doc_id>/edit', methods=['POST'])
@login_required
def edit_planning(doc_id):
    db = get_db()
    db.execute(
        "UPDATE planning_docs SET title=?, description=?, boat_name=?, planned_start=?, "
        "planned_end=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (request.form.get('title', ''), request.form.get('description', ''),
         request.form.get('boat_name', ''), request.form.get('planned_start', '') or None,
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

# ── API Routes (for AJAX) ─────────────────────────────────────────────

@app.route('/api/boats')
@login_required
def api_boats():
    db = get_db()
    boats = db.execute("SELECT * FROM boats ORDER BY name").fetchall()
    db.close()
    return jsonify([dict(b) for b in boats])

@app.route('/api/maintenance')
@login_required
def api_maintenance():
    db = get_db()
    maintenance = db.execute("SELECT * FROM maintenance ORDER BY due_date ASC").fetchall()
    db.close()
    return jsonify([dict(m) for m in maintenance])

# ── Initialize and Run ────────────────────────────────────────────────

init_db()

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  BoatKeeper Online Server")
    print("=" * 50)
    print("  Local:   http://localhost:5000")
    print("  Network: http://<your-ip>:5000")
    print("  Admin:   username='admin', password='admin123'")
    print("  (Change password after first login!)")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)

# For production deployment (Gunicorn entry point)
application = app
