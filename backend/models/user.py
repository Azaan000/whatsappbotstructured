from datetime import datetime
from models.database import get_db


def save_user(phone, socketio, name=""):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT phone FROM users WHERE phone=?", (phone,))
        is_new = cursor.fetchone() is None

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT OR IGNORE INTO users (phone, name, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (phone, name, now, now),
        )
        # Update name if provided
        if name:
            cursor.execute(
                "UPDATE users SET last_seen=?, name=? WHERE phone=?",
                (now, name, phone),
            )
        else:
            cursor.execute(
                "UPDATE users SET last_seen=? WHERE phone=?",
                (now, phone),
            )
        conn.commit()

        if is_new:
            socketio.emit("new_user", {
                "phone": phone,
                "name": name,
                "human_mode": 0,
                "total_messages": 0,
                "last": "New user",
            })
            print(f"New user: {name or phone} ({phone})")

    except Exception as e:
        print(f"save_user error: {e}")
    finally:
        conn.close()


def get_user_mode(phone) -> int:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT human_mode FROM users WHERE phone=?", (phone,))
        row = cursor.fetchone()
        return row["human_mode"] if row else 0
    except Exception as e:
        print(f"get_user_mode error: {e}")
        return 0
    finally:
        conn.close()


def toggle_user_mode(phone, socketio):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT human_mode FROM users WHERE phone=?", (phone,))
        row = cursor.fetchone()
        if not row:
            return None

        new_mode = 0 if row["human_mode"] == 1 else 1
        cursor.execute("UPDATE users SET human_mode=? WHERE phone=?", (new_mode, phone))
        conn.commit()

        socketio.emit("mode_changed", {"phone": phone, "human_mode": new_mode})
        print(f"User {phone} -> {'HUMAN' if new_mode else 'AI'} mode")
        return new_mode
    except Exception as e:
        print(f"toggle_user_mode error: {e}")
        return None
    finally:
        conn.close()


def update_user_meta(phone, tags, notes, socketio):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET tags=?, notes=? WHERE phone=?",
            (tags, notes, phone),
        )
        conn.commit()
        socketio.emit("user_updated", {"phone": phone, "tags": tags, "notes": notes})
    except Exception as e:
        print(f"update_user_meta error: {e}")
    finally:
        conn.close()


def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.phone, u.name, u.human_mode, u.tags, u.notes, u.total_messages, u.last_seen,
                   (SELECT message FROM messages m
                    WHERE m.phone = u.phone ORDER BY id DESC LIMIT 1) AS last_message
            FROM users u
            ORDER BY u.last_seen DESC
        """)
        rows = cursor.fetchall()
        return [
            {
                "phone": r["phone"],
                "name": r["name"] or "",
                "human_mode": r["human_mode"],
                "tags": r["tags"] or "",
                "notes": r["notes"] or "",
                "total_messages": r["total_messages"] or 0,
                "last_seen": r["last_seen"],
                "last": r["last_message"] or "No messages",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"get_all_users error: {e}")
        return []
    finally:
        conn.close()