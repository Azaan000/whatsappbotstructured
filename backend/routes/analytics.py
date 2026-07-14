import time
from datetime import datetime
from flask import Blueprint, jsonify
from models.database import get_db
from utils.auth import require_auth

analytics_bp = Blueprint("analytics", __name__)

_analytics_cache = {}
_cache_time = 0
CACHE_TTL = 30  # seconds


@analytics_bp.route("/analytics", methods=["GET"])
@require_auth
def get_analytics():
    global _analytics_cache, _cache_time

    # Return cached result if fresh
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

        # Store in cache
        _analytics_cache = result
        _cache_time = time.time()

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@analytics_bp.route("/reload-knowledge", methods=["POST"])
@require_auth
def reload_knowledge():
    from bot.ai_client import reload_knowledge as _reload
    knowledge = _reload()
    # Invalidate analytics cache too
    global _cache_time
    _cache_time = 0
    return jsonify({"success": True, "length": len(knowledge)})