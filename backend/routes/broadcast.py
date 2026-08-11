import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from models import broadcast as broadcast_model
from utils.auth import require_auth

broadcast_bp = Blueprint("broadcast", __name__)

MEDIA_FOLDER = os.getenv("MEDIA_FOLDER", "media_files")
os.makedirs(MEDIA_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "doc", "docx", "txt",
    "mp3", "wav", "ogg",
    "mp4", "mov",
}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _resolve_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image"
    if ext in {"mp3", "wav", "ogg"}:
        return "audio"
    if ext in {"mp4", "mov"}:
        return "video"
    return "document"


def _socketio():
    return current_app.extensions["socketio"]


# ── Broadcasts ─────────────────────────────────────────────────────────────

@broadcast_bp.route("/broadcasts", methods=["GET"])
@require_auth
def list_broadcasts():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(broadcast_model.list_broadcasts(limit=limit))


@broadcast_bp.route("/broadcasts/<int:broadcast_id>", methods=["GET"])
@require_auth
def get_broadcast(broadcast_id):
    b = broadcast_model.get_broadcast(broadcast_id)
    if not b:
        return jsonify({"error": "Broadcast not found"}), 404
    return jsonify(b)


@broadcast_bp.route("/broadcasts", methods=["POST"])
@require_auth
def create_broadcast():
    """Accepts either JSON (no media) or multipart/form-data (with a
    file attachment). recipients is expected as a list of
    {phone, name} — passed as JSON in either case (a form field named
    'recipients' holding a JSON string, for the multipart path)."""
    import json as _json

    file_name = ""
    media_path = ""
    media_type = ""

    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.form
        message = data.get("message", "")
        try:
            recipients = _json.loads(data.get("recipients", "[]"))
        except ValueError:
            return jsonify({"error": "recipients must be valid JSON"}), 400
        created_by = getattr(request, "dashboard_user_id", None)
        scheduled_at = data.get("scheduled_at") or None
        min_delay_ms = data.get("min_delay_ms", 400, type=int) if hasattr(data, "get") else 400
        max_delay_ms = data.get("max_delay_ms", 900, type=int) if hasattr(data, "get") else 900

        file = request.files.get("file")
        if file and file.filename:
            if not _allowed(file.filename):
                return jsonify({"error": "File type not allowed"}), 400
            original_name = file.filename
            safe_name = secure_filename(
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{original_name}"
            )
            filepath = os.path.join(MEDIA_FOLDER, safe_name)
            file.save(filepath)
            file_name = original_name
            media_path = filepath
            media_type = _resolve_media_type(original_name)
    else:
        data = request.json or {}
        message = data.get("message", "")
        recipients = data.get("recipients", [])
        created_by = getattr(request, "dashboard_user_id", None)
        scheduled_at = data.get("scheduled_at") or None
        min_delay_ms = data.get("min_delay_ms", 400)
        max_delay_ms = data.get("max_delay_ms", 900)

    if not message and not media_path:
        return jsonify({"error": "message or file required"}), 400
    if not recipients:
        return jsonify({"error": "recipients required"}), 400

    broadcast_id = broadcast_model.create_broadcast(
        message=message,
        recipients=recipients,
        file_name=file_name,
        media_path=media_path,
        media_type=media_type,
        created_by=created_by,
        scheduled_at=scheduled_at,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
    )
    b = broadcast_model.get_broadcast(broadcast_id)
    _socketio().emit("broadcast_created", b)
    return jsonify(b), 201


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/recipients/<phone>/status", methods=["POST"])
@require_auth
def update_recipient_status(broadcast_id, phone):
    """Called by the dashboard as it works through an immediate (not
    scheduled) broadcast send loop client-side, to persist each
    recipient's outcome and keep the sent/failed counters accurate."""
    data = request.json or {}
    status = data.get("status")
    if status not in ("pending", "sent", "failed"):
        return jsonify({"error": "status must be one of: pending, sent, failed"}), 400

    ok = broadcast_model.set_recipient_status(broadcast_id, phone, status)
    if not ok:
        return jsonify({"error": "Recipient not found"}), 404

    b = broadcast_model.get_broadcast(broadcast_id)
    _socketio().emit("broadcast_progress", {
        "broadcast_id": broadcast_id,
        "phone": phone,
        "status": status,
        "sent": b["sent"],
        "failed": b["failed"],
        "total": b["total"],
    })
    return jsonify({"success": True})


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/finish", methods=["POST"])
@require_auth
def finish_broadcast(broadcast_id):
    data = request.json or {}
    status = data.get("status", "completed")
    ok = broadcast_model.finish_broadcast(broadcast_id, status=status)
    if not ok:
        return jsonify({"error": "Broadcast not found"}), 404
    b = broadcast_model.get_broadcast(broadcast_id)
    _socketio().emit("broadcast_finished", b)
    return jsonify(b)


# ── Templates ────────────────────────────────────────────────────────────

@broadcast_bp.route("/broadcast-templates", methods=["GET"])
@require_auth
def list_templates():
    return jsonify(broadcast_model.list_templates())


@broadcast_bp.route("/broadcast-templates", methods=["POST"])
@require_auth
def create_template():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    message = data.get("message", "")
    if not name or not message:
        return jsonify({"error": "name and message required"}), 400
    created_by = getattr(request, "dashboard_user_id", None)
    template_id = broadcast_model.create_template(name, message, created_by=created_by)
    return jsonify({"id": template_id, "name": name, "message": message}), 201


@broadcast_bp.route("/broadcast-templates/<int:template_id>", methods=["DELETE"])
@require_auth
def delete_template(template_id):
    ok = broadcast_model.delete_template(template_id)
    if not ok:
        return jsonify({"error": "Template not found"}), 404
    return jsonify({"success": True})