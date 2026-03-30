import sqlite3
import os
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esp_devices (
            id INTEGER PRIMARY KEY,
            is_connected BOOLEAN DEFAULT 0,
            transport TEXT,
            state TEXT DEFAULT 'disconnected',
            last_seen_ms INTEGER,
            last_seen_at TEXT,
            last_seq INTEGER DEFAULT 0,
            missed_packets INTEGER DEFAULT 0,
            boot_id INTEGER,
            firmware_version INTEGER,
            last_error TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unity_images (
            name TEXT PRIMARY KEY,
            data BLOB NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS relabels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER,
            original_label TEXT,
            new_label TEXT NOT NULL,
            sensor_data TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS label_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            image BLOB
        )
                   ''')

    db_connection.commit()

    ensure_labels_sensor_columns()
    ensure_relabels_data_columns()
    ensure_esp_device_columns()

    seed_mock_unity_images()
    seed_labels_table()


def ensure_labels_sensor_columns():
    cursor = get_database().cursor()
    cursor.execute("PRAGMA table_info(labels)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for idx in range(1, 8):
        column_name = f"esp{idx}"
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE labels ADD COLUMN {column_name} TEXT")

    get_database().commit()


def ensure_relabels_data_columns():
    cursor = get_database().cursor()
    cursor.execute("PRAGMA table_info(relabels)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if "esp_data" not in existing_columns:
        cursor.execute("ALTER TABLE relabels ADD COLUMN esp_data TEXT")

    get_database().commit()


def ensure_esp_device_columns():
    cursor = get_database().cursor()
    cursor.execute("PRAGMA table_info(esp_devices)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    expected_columns = {
        "transport": "TEXT",
        "state": "TEXT DEFAULT 'disconnected'",
        "last_seen_ms": "INTEGER",
        "last_seen_at": "TEXT",
        "last_seq": "INTEGER DEFAULT 0",
        "missed_packets": "INTEGER DEFAULT 0",
        "boot_id": "INTEGER",
        "firmware_version": "INTEGER",
        "last_error": "TEXT",
    }

    for column_name, column_type in expected_columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE esp_devices ADD COLUMN {column_name} {column_type}")

    get_database().commit()


def seed_mock_unity_images():
    images_dir = Path(__file__).parent / 'label_images'
    files = ['standing.png', 'walking.png', 'sitting.png', 'lying.png']

    if not images_dir.exists():
        return

    cursor = get_database().cursor()

    for file in files:
        file_path = images_dir / file
        if not file_path.exists():
            continue

        cursor.execute('SELECT name FROM unity_images WHERE name = ?', (file,))
        if cursor.fetchone():
            continue

        with open(file_path, 'rb') as f:
            data = f.read()
        cursor.execute('INSERT INTO unity_images (name, data) VALUES (?, ?)', (file, data))

    get_database().commit()


def seed_labels_table():
    cursor = get_database().cursor()
    cursor.execute('SELECT id, name FROM labels WHERE id = 1')
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute('INSERT INTO labels (id, name) VALUES (?, ?)', (1, 'sitting'))

    get_database().commit()


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
