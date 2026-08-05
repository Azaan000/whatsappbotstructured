import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "database.db")


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
            total_messages INTEGER DEFAULT 0,
            last_message   TEXT DEFAULT '',
            last_read_message_id INTEGER DEFAULT 0
        )
    """)

    # Created before the migrations/backfills below, since some of them
    # (e.g. the last_message backfill) query this table — on a genuinely
    # fresh install, `messages` wouldn't exist yet otherwise and those
    # queries would fail.
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

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        # Expected on every run after the first — the column already
        # exists. A bare `except: pass` here would also silently swallow
        # genuine problems (disk full, corrupt db, locked file, etc.),
        # so only ignore the specific "duplicate column" case.
        if "duplicate column name" not in str(e).lower():
            print(f"init_db migration warning: {e}")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_message TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"init_db migration warning: {e}")

    # 'source' records which ad campaign brought this user in — 'biz',
    # 'law', or '' if they came in organically (direct message, no ad
    # referral, or an ad we couldn't classify by keyword). Set once on
    # first contact and reused on every later "menu" request so the
    # user keeps seeing the menu that matches the ad they clicked.
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN source TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"init_db migration warning: {e}")

    # Track whether this column is being added for the very first time —
    # the one-time backfill below must only run in that case. If it ran
    # on every startup instead (matching on last_read_message_id == 0),
    # it would keep resetting genuinely-unread conversations to "read"
    # every time the server restarts, which is the exact bug this
    # migration exists to fix, just from the other direction.
    just_added_last_read_column = False
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_read_message_id INTEGER DEFAULT 0")
        just_added_last_read_column = True
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"init_db migration warning: {e}")

    # Backfill last_message for any existing rows created before this
    # column existed (a fresh install has no users yet, so this is a
    # no-op; on an upgrade it runs once and self-heals the data).
    cursor.execute("""
        UPDATE users
        SET last_message = (
            SELECT message FROM messages m
            WHERE m.phone = users.phone
            ORDER BY m.id DESC LIMIT 1
        )
        WHERE (last_message IS NULL OR last_message = '')
          AND EXISTS (SELECT 1 FROM messages m WHERE m.phone = users.phone)
    """)

    # Backfill last_read_message_id (one-time only, see comment above) —
    # marks everything as "read up to now" so existing conversations
    # don't all show as unread the moment this feature ships.
    if just_added_last_read_column:
        cursor.execute("""
            UPDATE users
            SET last_read_message_id = COALESCE(
                (SELECT MAX(m.id) FROM messages m WHERE m.phone = users.phone), 0
            )
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name  TEXT DEFAULT '',
            is_admin      INTEGER DEFAULT 0,
            created_at    TEXT,
            last_login    TEXT
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
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dashboard_users_username
        ON dashboard_users (username)
    """)

    conn.commit()
    conn.close()
    print("Database ready")