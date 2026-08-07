import time
from datetime import datetime
from flask import Blueprint, jsonify, request
from models.database import get_db
from models import consultation as consultation_model
from utils.auth import require_auth

analytics_bp = Blueprint("analytics", __name__)

_analytics_cache = {}
_cache_time = 0
CACHE_TTL = 30


@analytics_bp.route("/analytics", methods=["GET"])
@require_auth
def get_analytics():
    global _analytics_cache, _cache_time

    if time.time() - _cache_time < CACHE_TTL and _analytics_cache:
        return jsonify(_analytics_cache)

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM messages")
        total_messages = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE human_mode=0")
        ai_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE human_mode=1")
        human_users = c.fetchone()[0]

        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM messages WHERE timestamp LIKE ?", (f"{today}%",))
        messages_today = c.fetchone()[0]

        c.execute("""
            SELECT message_type, COUNT(*) as count
            FROM messages GROUP BY message_type
        """)
        message_types = [{"type": r[0] or "text", "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT phone, total_messages, last_seen
            FROM users ORDER BY total_messages DESC LIMIT 10
        """)
        top_users = [{"phone": r[0], "messages": r[1], "last_seen": r[2]}
                     for r in c.fetchall()]

        c.execute("""
            SELECT AVG(
                (julianday(b.timestamp) - julianday(u.timestamp)) * 24 * 60
            ) AS avg_minutes
            FROM messages u
            JOIN messages b ON b.phone = u.phone
            WHERE u.direction = 'user'
              AND b.direction = 'bot'
              AND b.id > u.id
              AND b.id = (
                  SELECT MIN(id) FROM messages
                  WHERE phone = u.phone AND direction = 'bot' AND id > u.id
              )
        """)
        avg_response = c.fetchone()[0] or 0

        c.execute("""
            SELECT message, COUNT(*) as count
            FROM messages
            WHERE direction='user' AND message_type='text' AND message != ''
            GROUP BY message ORDER BY count DESC LIMIT 10
        """)
        top_questions = [{"question": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM messages
            WHERE DATE(timestamp) >= DATE('now', '-7 days')
            GROUP BY DATE(timestamp) ORDER BY date
        """)
        daily_activity = [{"date": r[0], "messages": r[1]} for r in c.fetchall()]

        result = {
            "total_users": total_users,
            "total_messages": total_messages,
            "ai_users": ai_users,
            "human_users": human_users,
            "messages_today": messages_today,
            "avg_response_time": round(avg_response, 2),
            "message_types": message_types,
            "top_users": top_users,
            "top_questions": top_questions,
            "daily_activity": daily_activity,
        }

        _analytics_cache = result
        _cache_time = time.time()

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@analytics_bp.route("/consultations", methods=["GET"])
@require_auth
def get_consultations():
    """Return the consultation queue, filterable via query params:
    stage ('booked' default | 'requested' | 'all'), status, service_id,
    brand, assigned_to (dashboard_user id, or 'me', or 'unassigned'),
    search, date_from, date_to, sort (e.g. '-created_at', 'name')."""
    try:
        assigned_to = request.args.get("assigned_to")
        unassigned_only = assigned_to == "unassigned"
        if assigned_to == "me":
            assigned_to = getattr(request, "dashboard_user_id", None)
        elif assigned_to not in (None, "unassigned"):
            try:
                assigned_to = int(assigned_to)
            except ValueError:
                assigned_to = None

        rows = consultation_model.list_consultations(
            stage=request.args.get("stage", "booked"),
            status=request.args.get("status"),
            service_id=request.args.get("service_id"),
            brand=request.args.get("brand"),
            assigned_to=None if unassigned_only else assigned_to,
            unassigned_only=unassigned_only,
            search=request.args.get("search"),
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
            sort=request.args.get("sort", "-created_at"),
        )
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route("/consultations/<int:consultation_id>", methods=["PATCH"])
@require_auth
def patch_consultation(consultation_id):
    """Update a consultation's status, assignment, and/or scheduled time.
    Body may include any subset of: status, assigned_to (dashboard_user
    id or null to unassign), scheduled_at (ISO datetime string)."""
    data = request.get_json(silent=True) or {}

    kwargs = {}
    if "status" in data:
        kwargs["status"] = data["status"]
    if "assigned_to" in data:
        kwargs["assigned_to"] = data["assigned_to"]
    if "scheduled_at" in data:
        kwargs["scheduled_at"] = data["scheduled_at"] or ""

    success, error = consultation_model.update_consultation(consultation_id, **kwargs)
    if not success:
        status_code = 404 if error == "Consultation not found" else 400
        return jsonify({"error": error}), status_code

    return jsonify(consultation_model.get_consultation(consultation_id))


@analytics_bp.route("/consultations/funnel", methods=["GET"])
@require_auth
def get_consultation_funnel():
    """Per-service requested -> booked -> completed conversion counts."""
    try:
        return jsonify(consultation_model.funnel_stats(brand=request.args.get("brand")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route("/reload-knowledge", methods=["POST"])
@require_auth
def reload_knowledge():
    from bot.ai_client import reload_knowledge as _reload
    global _cache_time
    knowledge = _reload()
    _cache_time = 0
    return jsonify({"success": True, "length": len(knowledge)})