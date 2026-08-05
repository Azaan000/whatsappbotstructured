import re
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from models.database import get_db

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")
MIN_PASSWORD_LEN = 8


def validate_credentials(username, password):
    """Shared validation for registration. Returns an error string, or
    None if the username/password are acceptable. Kept separate from
    the DB call so the route can return a 400 before ever touching the
    database."""
    if not username or not USERNAME_RE.match(username):
        return "Username must be 3-32 characters (letters, numbers, underscore, dot only)"
    if not password or len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    return None


def dashboard_user_count():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS c FROM dashboard_users")
        return cursor.fetchone()["c"]
    finally:
        conn.close()


def dashboard_admin_count():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS c FROM dashboard_users WHERE is_admin=1")
        return cursor.fetchone()["c"]
    finally:
        conn.close()


def create_dashboard_user(username, password, display_name="", is_admin=None):
    """Create a new dashboard login (self-registration or admin-created).

    is_admin: if left as None, the very first account created on a
    fresh install is automatically made an admin (so there's always at
    least one admin able to manage the rest of the users) — every
    account after that defaults to a regular, non-admin user.

    Returns (user_dict, error_message). Exactly one of these is set.
    """
    error = validate_credentials(username, password)
    if error:
        return None, error

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM dashboard_users WHERE username=?", (username,))
        if cursor.fetchone():
            return None, "That username is already taken"

        if is_admin is None:
            cursor.execute("SELECT COUNT(*) AS c FROM dashboard_users")
            is_admin = cursor.fetchone()["c"] == 0

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            """INSERT INTO dashboard_users
               (username, password_hash, display_name, is_admin, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (username, generate_password_hash(password), display_name or username, int(bool(is_admin)), now),
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {
            "id": user_id,
            "username": username,
            "display_name": display_name or username,
            "is_admin": bool(is_admin),
        }, None
    except Exception as e:
        print(f"create_dashboard_user error: {e}")
        return None, "Could not create account"
    finally:
        conn.close()


def verify_dashboard_login(username, password):
    """Returns the user dict if username/password are correct, else None.

    check_password_hash internally does a constant-time comparison of
    the hash (via hmac.compare_digest under the hood), so this doesn't
    leak timing information about how close a guessed password was —
    same property as the old DASHBOARD_SECRET check, just per-user now.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, username, password_hash, display_name, is_admin FROM dashboard_users WHERE username=?",
            (username,),
        )
        row = cursor.fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return None

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE dashboard_users SET last_login=? WHERE id=?",
            (now, row["id"]),
        )
        conn.commit()

        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "is_admin": bool(row["is_admin"]),
        }
    except Exception as e:
        print(f"verify_dashboard_login error: {e}")
        return None
    finally:
        conn.close()


def get_dashboard_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, username, display_name, is_admin, created_at, last_login FROM dashboard_users WHERE id=?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        user = dict(row)
        user["is_admin"] = bool(user["is_admin"])
        return user
    finally:
        conn.close()


def list_dashboard_users():
    """Admin-facing list of every dashboard account (no password hashes)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, username, display_name, is_admin, created_at, last_login "
            "FROM dashboard_users ORDER BY created_at ASC"
        )
        rows = cursor.fetchall()
        users = []
        for row in rows:
            u = dict(row)
            u["is_admin"] = bool(u["is_admin"])
            users.append(u)
        return users
    finally:
        conn.close()


def update_user_admin_status(target_user_id, new_is_admin):
    """Promote or demote a dashboard user. An admin cannot demote the
    last remaining admin (so the system always has at least one admin).

    Returns (success, error_message). One of these is set to None.
    """
    target = get_dashboard_user(target_user_id)
    if not target:
        return False, "User not found"

    # Prevent removing the last admin
    if target.get("is_admin") and not new_is_admin:
        if dashboard_admin_count() <= 1:
            return False, "Cannot demote the last remaining admin"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE dashboard_users SET is_admin=? WHERE id=?",
            (int(bool(new_is_admin)), target_user_id),
        )
        conn.commit()
        return True, None
    except Exception as e:
        print(f"update_user_admin_status error: {e}")
        return False, "Could not update user"
    finally:
        conn.close()


def verify_dashboard_password(user_id, password):
    """Used to re-confirm a password before a destructive action like
    account deletion, even though the user already has a valid token."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT password_hash FROM dashboard_users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        return check_password_hash(row["password_hash"], password or "")
    finally:
        conn.close()


def delete_dashboard_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dashboard_users WHERE id=?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"delete_dashboard_user error: {e}")
        return False
    finally:
        conn.close()