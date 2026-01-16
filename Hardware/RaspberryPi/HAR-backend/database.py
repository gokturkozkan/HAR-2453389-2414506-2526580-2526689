import sqlite3
import os
import io
from pathlib import Path

db_path = os.getenv('DB_PATH', './har.db')
db_connection = None

def get_database():
    global db_connection
    if db_connection is None:
        raise Exception('Database not initialized')
    return db_connection

def init_database():
    global db_connection
    db_connection = sqlite3.connect(db_path, check_same_thread=False)
    db_connection.row_factory = sqlite3.Row
    
    cursor = db_connection.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create ESP devices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esp_devices (
            id INTEGER PRIMARY KEY,
            is_connected BOOLEAN DEFAULT 0
        )
    ''')
    
    db_connection.commit()
    
    # Seed mock data
    seed_mock_unity_images()
    seed_labels_table()

def seed_mock_unity_images():
    images_dir = Path(__file__).parent / 'mock-Unity'
    files = ['jumping.png', 'sitting.png', 'standing.png']
    
    cursor = get_database().cursor()
    
    # Create table if missing
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unity_images (
            name TEXT PRIMARY KEY,
            data BLOB NOT NULL
        )
    ''')
    get_database().commit()
    
    for file in files:
        file_path = images_dir / file
        if not file_path.exists():
            continue
        
        # Check if already exists
        cursor.execute('SELECT name FROM unity_images WHERE name = ?', (file,))
        if cursor.fetchone():
            continue
        
        # Read and insert file
        with open(file_path, 'rb') as f:
            data = f.read()
        cursor.execute('INSERT INTO unity_images (name, data) VALUES (?, ?)', (file, data))
    
    get_database().commit()

def seed_labels_table():
    cursor = get_database().cursor()
    
    # Create table if missing
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    # Check if empty
    cursor.execute('SELECT name FROM labels LIMIT 1')
    if not cursor.fetchone():
        cursor.execute('INSERT INTO labels (name) VALUES (?)', ('sitting',))
    
    get_database().commit()

# Database query helpers
def db_run(sql, params=None):
    if params is None:
        params = []
    cursor = get_database().cursor()
    cursor.execute(sql, params)
    get_database().commit()
    return {'lastID': cursor.lastrowid, 'changes': cursor.rowcount}

def db_get(sql, params=None):
    if params is None:
        params = []
    cursor = get_database().cursor()
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return dict(row) if row else None

def db_all(sql, params=None):
    if params is None:
        params = []
    cursor = get_database().cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

def close_database():
    global db_connection
    if db_connection:
        db_connection.close()
        db_connection = None
