import sqlite3
from datetime import datetime

DB_PATH = "database.db"


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")  # allows concurrent reads/writes
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone          TEXT PRIMARY KEY,
            name           TEXT DEFAULT '',
            first_seen     TEXT,
            last_seen      TEXT,
            human_mode     INTEGER DEFAULT 0,
            tags           TEXT DEFAULT '',
            notes          TEXT DEFAULT '',
            total_messages INTEGER DEFAULT 0
        )
    """)

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")
    except:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            phone                TEXT,
            message              TEXT,
            direction            TEXT,
            status               TEXT DEFAULT 'sent',
            timestamp            TEXT,
            message_type         TEXT DEFAULT 'text',
            media_path           TEXT,
            file_name            TEXT,
            whatsapp_message_id  TEXT
        )
    """)

    # Indexes for fast lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone
        ON messages (phone)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone_dir
        ON messages (phone, direction, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_wa_id
        ON messages (whatsapp_message_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_last_seen
        ON users (last_seen DESC)
    """)

    conn.commit()
    conn.close()
    print("Database ready")


# Run on import — ensures tables exist before any route touches the DB
init_db()