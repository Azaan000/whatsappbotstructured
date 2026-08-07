from datetime import datetime, timezone, timedelta
from models.database import get_db

VALID_STATUSES = {"new", "contacted", "scheduled", "completed", "no_show"}
VALID_STAGES = {"requested", "booked"}

# A "new" consultation is flagged stale once it's sat untouched this long
# — the one place a delay directly costs a client, per the feature ask.
STALE_AFTER_HOURS = 24

# Sentinel so update_consultation can tell "assigned_to wasn't passed"
# apart from "assigned_to was explicitly set to None" (unassign).
_UNSET = object()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def create_lead(phone, service_id="", service_label="", brand=""):
    """Called the moment someone is put into the Name/Mobile/Time (or
    callback-choice) flow — captures which service they were looking at
    right then, before that context is lost. Returns the new row's id."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = _now()
        cursor.execute(
            """INSERT INTO consultations
               (phone, service_id, service_label, brand, stage, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'requested', 'new', ?, ?)""",
            (phone, service_id, service_label, brand, now, now),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def mark_booked(consultation_id, name, mobile, best_time, scheduled_at=None):
    """Upgrades a requested lead to a real booking once Name/Mobile/Best
    Time have all been collected."""
    if not consultation_id:
        return False
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """UPDATE consultations
               SET name=?, mobile=?, best_time=?, scheduled_at=?,
                   stage='booked', updated_at=?
               WHERE id=?""",
            (name, mobile, best_time, scheduled_at or "", _now(), consultation_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_consultation(consultation_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT c.*, d.display_name AS assigned_name
               FROM consultations c
               LEFT JOIN dashboard_users d ON d.id = c.assigned_to
               WHERE c.id=?""",
            (consultation_id,),
        )
        row = cursor.fetchone()
        return _serialize(row) if row else None
    finally:
        conn.close()


def list_consultations(
    stage="booked", status=None, service_id=None, brand=None,
    assigned_to=None, unassigned_only=False, search=None,
    date_from=None, date_to=None, sort="-created_at",
):
    """stage: 'booked' (default — the actionable queue), 'requested'
    (only the ones that never finished booking), or 'all'."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        clauses, params = [], []

        if stage and stage != "all":
            clauses.append("c.stage=?")
            params.append(stage)
        if status:
            clauses.append("c.status=?")
            params.append(status)
        if service_id:
            clauses.append("c.service_id=?")
            params.append(service_id)
        if brand:
            clauses.append("c.brand=?")
            params.append(brand)
        if unassigned_only:
            clauses.append("c.assigned_to IS NULL")
        elif assigned_to is not None:
            clauses.append("c.assigned_to=?")
            params.append(assigned_to)
        if date_from:
            clauses.append("c.created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("c.created_at <= ?")
            params.append(date_to)
        if search:
            clauses.append("(c.name LIKE ? OR c.phone LIKE ? OR c.mobile LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        sort_columns = {
            "created_at": "c.created_at", "updated_at": "c.updated_at",
            "name": "c.name", "status": "c.status", "service": "c.service_label",
        }
        sort_key = (sort or "-created_at").lstrip("-")
        sort_col = sort_columns.get(sort_key, "c.created_at")
        direction = "DESC" if (sort or "").startswith("-") or not sort else "ASC"

        cursor.execute(
            f"""SELECT c.*, d.display_name AS assigned_name
                FROM consultations c
                LEFT JOIN dashboard_users d ON d.id = c.assigned_to
                {where}
                ORDER BY {sort_col} {direction}""",
            params,
        )
        return [_serialize(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_consultation(consultation_id, status=None, assigned_to=_UNSET, scheduled_at=None):
    if status is not None and status not in VALID_STATUSES:
        return False, f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}"

    sets, params = [], []
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if assigned_to is not _UNSET:
        sets.append("assigned_to=?")
        params.append(assigned_to)
    if scheduled_at is not None:
        sets.append("scheduled_at=?")
        params.append(scheduled_at)

    if not sets:
        return False, "Nothing to update"

    sets.append("updated_at=?")
    params.append(_now())
    params.append(consultation_id)

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE consultations SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
        if cursor.rowcount == 0:
            return False, "Consultation not found"
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def funnel_stats(brand=None):
    """Per-service requested -> booked -> completed counts, for the
    'which services actually convert' question."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        clauses, params = ["service_label != ''"], []
        if brand:
            clauses.append("brand=?")
            params.append(brand)
        where = f"WHERE {' AND '.join(clauses)}"

        cursor.execute(
            f"""SELECT
                    service_label,
                    brand,
                    COUNT(*) AS requested,
                    SUM(CASE WHEN stage='booked' THEN 1 ELSE 0 END) AS booked,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
                FROM consultations
                {where}
                GROUP BY service_label, brand
                ORDER BY requested DESC""",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _serialize(row):
    d = dict(row)
    d["is_stale"] = False
    if d.get("status") == "new" and d.get("stage") == "booked":
        created = _parse_ts(d.get("created_at"))
        if created and (datetime.now(timezone.utc) - created) > timedelta(hours=STALE_AFTER_HOURS):
            d["is_stale"] = True
    return d