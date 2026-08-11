import json
from datetime import datetime, timezone
from models.database import get_db


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_broadcast(
    message, recipients, file_name="", media_path="", media_type="",
    created_by=None, scheduled_at=None, min_delay_ms=400, max_delay_ms=900,
):
    """recipients: list of {phone, name}. Every recipient starts out
    'pending' — the dashboard (or, for scheduled sends, the background
    scheduler) flips each one to 'sent'/'failed' as the send loop works
    through the list, so a broadcast that's interrupted part-way still
    has a durable record of exactly who's left.

    If scheduled_at is given the broadcast is created in 'scheduled'
    status and nothing is sent yet — the background scheduler thread
    picks it up once it's due."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = _now()
        recipients_json = json.dumps([
            {"phone": r.get("phone", ""), "name": r.get("name", ""), "status": "pending"}
            for r in recipients
        ])
        status = "scheduled" if scheduled_at else "in_progress"
        cursor.execute(
            """INSERT INTO broadcasts
               (message, file_name, media_path, media_type, total, sent, failed,
                status, recipients, created_by, scheduled_at, min_delay_ms, max_delay_ms,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message, file_name, media_path, media_type, len(recipients),
                status, recipients_json, created_by, scheduled_at or "",
                min_delay_ms, max_delay_ms, now, now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def set_recipient_status(broadcast_id, phone, status):
    """Marks one recipient sent/failed and keeps the sent/failed
    counters in sync, including the case where a retry flips a
    previously-failed recipient over to sent."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT recipients, sent, failed FROM broadcasts WHERE id=?", (broadcast_id,))
        row = cursor.fetchone()
        if not row:
            return False
        recipients = json.loads(row["recipients"] or "[]")
        sent, failed = row["sent"] or 0, row["failed"] or 0
        for r in recipients:
            if r["phone"] == phone:
                prev = r.get("status")
                if prev != status:
                    if prev == "sent":
                        sent -= 1
                    elif prev == "failed":
                        failed -= 1
                    if status == "sent":
                        sent += 1
                    elif status == "failed":
                        failed += 1
                r["status"] = status
                break
        cursor.execute(
            "UPDATE broadcasts SET recipients=?, sent=?, failed=?, updated_at=? WHERE id=?",
            (json.dumps(recipients), sent, failed, _now(), broadcast_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def finish_broadcast(broadcast_id, status="completed"):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE broadcasts SET status=?, updated_at=? WHERE id=?",
            (status, _now(), broadcast_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_broadcast_sending(broadcast_id):
    """Flips a due 'scheduled' broadcast to 'in_progress' right before
    the scheduler starts working through it."""
    return finish_broadcast(broadcast_id, status="in_progress")


def get_broadcast(broadcast_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT b.*, d.display_name AS created_by_name
               FROM broadcasts b LEFT JOIN dashboard_users d ON d.id = b.created_by
               WHERE b.id=?""",
            (broadcast_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["recipients"] = json.loads(d.get("recipients") or "[]")
        return d
    finally:
        conn.close()


def list_broadcasts(limit=50):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT b.*, d.display_name AS created_by_name
               FROM broadcasts b LEFT JOIN dashboard_users d ON d.id = b.created_by
               ORDER BY b.created_at DESC LIMIT ?""",
            (limit,),
        )
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            d["recipients"] = json.loads(d.get("recipients") or "[]")
            result.append(d)
        return result
    finally:
        conn.close()


def get_due_scheduled_broadcasts():
    """Scheduled broadcasts whose send time has arrived (or passed —
    e.g. the server was down when it was due)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = _now()
        cursor.execute(
            """SELECT * FROM broadcasts
               WHERE status='scheduled' AND scheduled_at != '' AND scheduled_at <= ?
               ORDER BY scheduled_at ASC""",
            (now,),
        )
        result = []
        for row in cursor.fetchall():
            d = dict(row)
            d["recipients"] = json.loads(d.get("recipients") or "[]")
            result.append(d)
        return result
    finally:
        conn.close()


# ── Templates ────────────────────────────────────────────────────────────

def create_template(name, message, created_by=None):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO broadcast_templates (name, message, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, message, created_by, _now()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def list_templates():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM broadcast_templates ORDER BY created_at DESC")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def delete_template(template_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM broadcast_templates WHERE id=?", (template_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()