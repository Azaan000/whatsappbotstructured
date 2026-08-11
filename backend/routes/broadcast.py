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

    Recipients are stored one row per person in broadcast_recipients
    (not as a JSON blob on this row) — see set_recipient_status for why
    that matters once a broadcast has real volume.

    If scheduled_at is given the broadcast is created in 'scheduled'
    status and nothing is sent yet — the background scheduler thread
    picks it up once it's due."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = _now()
        status = "scheduled" if scheduled_at else "in_progress"
        cursor.execute(
            """INSERT INTO broadcasts
               (message, file_name, media_path, media_type, total, sent, failed,
                status, recipients, created_by, scheduled_at, min_delay_ms, max_delay_ms,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, '[]', ?, ?, ?, ?, ?, ?)""",
            (
                message, file_name, media_path, media_type, len(recipients),
                status, created_by, scheduled_at or "",
                min_delay_ms, max_delay_ms, now, now,
            ),
        )
        broadcast_id = cursor.lastrowid

        cursor.executemany(
            """INSERT INTO broadcast_recipients (broadcast_id, phone, name, status)
               VALUES (?, ?, ?, 'pending')""",
            [(broadcast_id, r.get("phone", ""), r.get("name", "")) for r in recipients],
        )
        conn.commit()
        return broadcast_id
    finally:
        conn.close()


def set_recipient_status(broadcast_id, phone, status):
    """Marks one recipient sent/failed and keeps the sent/failed
    counters in sync, including the case where a retry flips a
    previously-failed recipient over to sent.

    O(1) — a single indexed UPDATE on broadcast_recipients plus a
    counter increment on the broadcasts row. This used to read the
    ENTIRE recipients JSON array off the broadcasts row, parse it, scan
    it for this phone, and write the WHOLE array back — for every
    recipient, on every send. A 5,000-person broadcast did that 5,000
    times, so total work (and total bytes written to disk) grew as
    O(n^2) with the broadcast size, on top of the natural per-recipient
    send delay. Recipients now live one-row-each in
    broadcast_recipients with a unique index on (broadcast_id, phone),
    so this is a single point lookup + point update regardless of how
    many people are in the broadcast."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT status FROM broadcast_recipients WHERE broadcast_id=? AND phone=?",
            (broadcast_id, phone),
        )
        row = cursor.fetchone()
        if not row:
            return False

        prev = row["status"]
        if prev == status:
            return True  # already in this state — nothing to update or recount

        cursor.execute(
            "UPDATE broadcast_recipients SET status=? WHERE broadcast_id=? AND phone=?",
            (status, broadcast_id, phone),
        )

        sent_delta = (1 if status == "sent" else 0) - (1 if prev == "sent" else 0)
        failed_delta = (1 if status == "failed" else 0) - (1 if prev == "failed" else 0)
        cursor.execute(
            "UPDATE broadcasts SET sent = sent + ?, failed = failed + ?, updated_at=? WHERE id=?",
            (sent_delta, failed_delta, _now(), broadcast_id),
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


def _fetch_recipients(cursor, broadcast_id):
    cursor.execute(
        """SELECT phone, name, status FROM broadcast_recipients
           WHERE broadcast_id=? ORDER BY id""",
        (broadcast_id,),
    )
    return [
        {"phone": r["phone"], "name": r["name"] or "", "status": r["status"] or "pending"}
        for r in cursor.fetchall()
    ]


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
        d["recipients"] = _fetch_recipients(cursor, broadcast_id)
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
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["recipients"] = _fetch_recipients(cursor, d["id"])
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
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["recipients"] = _fetch_recipients(cursor, d["id"])
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