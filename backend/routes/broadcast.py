import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from models import broadcast as broadcast_model
from models.message import save_message
from bot.whatsapp_handler import send_media
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


def _safe_media_path(candidate: str) -> str:
    """Collapse a client-supplied media_path down to its basename and
    rejoin it under MEDIA_FOLDER — same defensive pattern as chat.py's
    /media/<path:filename> route — so a broadcast/send-media call can't
    be used to read an arbitrary path off the server."""
    return os.path.join(MEDIA_FOLDER, os.path.basename(candidate or ""))


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
    """Accepts either JSON (no media, or media already uploaded via
    /broadcasts/upload and referenced by file_name/media_path/media_type)
    or multipart/form-data (uploading a file as part of creation).
    recipients is expected as a list of {phone, name} — passed as JSON
    in either case (a form field named 'recipients' holding a JSON
    string, for the multipart path)."""
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
        # Media already uploaded via /broadcasts/upload — the dashboard's
        # "new broadcast" flow uploads the file first (so it can reuse
        # the single stored copy across every recipient send) and then
        # passes these three fields back in when creating the broadcast
        # row itself. Previously this branch silently dropped them,
        # which meant any broadcast with an attachment was created with
        # no media_path at all.
        file_name = data.get("file_name", "")
        media_path = data.get("media_path", "")
        media_type = data.get("media_type", "")

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


@broadcast_bp.route("/broadcasts/upload", methods=["POST"])
@require_auth
def upload_broadcast_media():
    """Uploads a file for an upcoming broadcast and returns a reference
    to it (file_name/media_path/media_type), WITHOUT sending anything or
    creating a broadcast row yet. The dashboard calls this once up front,
    then reuses the returned media_path for every recipient via
    /broadcasts/send-media — instead of re-uploading and re-saving a
    fresh copy to disk on every single send, which is what happens with
    the one-off /send-file endpoint."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    original_name = file.filename
    safe_name = secure_filename(
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{original_name}"
    )
    filepath = os.path.join(MEDIA_FOLDER, safe_name)
    file.save(filepath)

    return jsonify({
        "file_name": original_name,
        "media_path": filepath,
        "media_type": _resolve_media_type(original_name),
    }), 201


@broadcast_bp.route("/broadcasts/send-media", methods=["POST"])
@require_auth
def send_broadcast_media():
    """Sends a file already stored via /broadcasts/upload to one
    recipient, reusing that single stored copy — the per-recipient send
    step of an in-progress broadcast with an attachment."""
    data = request.json or {}
    phone = data.get("phone")
    media_path = data.get("media_path")
    media_type = data.get("media_type") or "document"
    caption = data.get("caption", "")

    if not phone or not media_path:
        return jsonify({"error": "phone and media_path required"}), 400

    safe_path = _safe_media_path(media_path)
    if not os.path.exists(safe_path):
        return jsonify({"error": "Media file not found"}), 404

    success, wa_id = send_media(phone, safe_path, media_type, caption)
    status = "sent" if success else "failed"

    save_message(
        phone, caption or f"Sent: {os.path.basename(safe_path)}", "bot", _socketio(),
        status=status, message_type=media_type, file_name=os.path.basename(safe_path),
        media_path=safe_path, whatsapp_message_id=wa_id,
    )

    if success:
        return jsonify({"success": True, "message_id": wa_id})
    return jsonify({"error": "Failed to send media"}), 500


def _update_recipient_status(broadcast_id, phone, status):
    if status not in ("pending", "sent", "failed"):
        return None, (jsonify({"error": "status must be one of: pending, sent, failed"}), 400)

    ok = broadcast_model.set_recipient_status(broadcast_id, phone, status)
    if not ok:
        return None, (jsonify({"error": "Recipient not found"}), 404)

    b = broadcast_model.get_broadcast(broadcast_id)
    _socketio().emit("broadcast_progress", {
        "broadcast_id": broadcast_id,
        "phone": phone,
        "status": status,
        "sent": b["sent"],
        "failed": b["failed"],
        "total": b["total"],
    })
    return b, None


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/recipients/<phone>/status", methods=["POST"])
@require_auth
def update_recipient_status(broadcast_id, phone):
    data = request.json or {}
    _, err = _update_recipient_status(broadcast_id, phone, data.get("status"))
    if err:
        return err
    return jsonify({"success": True})


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/recipient", methods=["PATCH"])
@require_auth
def update_recipient_status_patch(broadcast_id):
    """Same as the POST .../recipients/<phone>/status route above, just
    addressed the way the dashboard's broadcast send loop actually calls
    it: phone in the body instead of the URL, PATCH instead of POST."""
    data = request.json or {}
    phone = data.get("phone")
    if not phone:
        return jsonify({"error": "phone required"}), 400
    _, err = _update_recipient_status(broadcast_id, phone, data.get("status"))
    if err:
        return err
    return jsonify({"success": True})


def _finish_broadcast(broadcast_id, status):
    ok = broadcast_model.finish_broadcast(broadcast_id, status=status)
    if not ok:
        return None, (jsonify({"error": "Broadcast not found"}), 404)
    b = broadcast_model.get_broadcast(broadcast_id)
    _socketio().emit("broadcast_finished", b)
    return b, None


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/finish", methods=["POST"])
@require_auth
def finish_broadcast(broadcast_id):
    data = request.json or {}
    b, err = _finish_broadcast(broadcast_id, data.get("status", "completed"))
    if err:
        return err
    return jsonify(b)


@broadcast_bp.route("/broadcasts/<int:broadcast_id>", methods=["PATCH"])
@require_auth
def finish_broadcast_patch(broadcast_id):
    """Same as POST .../finish above, addressed the way the dashboard's
    broadcast send loop actually calls it (PATCH the broadcast itself)."""
    data = request.json or {}
    b, err = _finish_broadcast(broadcast_id, data.get("status", "completed"))
    if err:
        return err
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