import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from models.broadcast import (
    create_broadcast,
    set_recipient_status,
    finish_broadcast,
    get_broadcast,
    list_broadcasts,
    create_template,
    list_templates,
    delete_template,
)
from models.message import save_message
from bot.whatsapp_handler import resolve_media_type, send_media
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


def _socketio():
    return current_app.extensions["socketio"]


# ── Broadcasts ───────────────────────────────────────────────────────────

@broadcast_bp.route("/broadcasts", methods=["GET"])
@require_auth
def broadcasts_list():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(list_broadcasts(limit=limit))


@broadcast_bp.route("/broadcasts/upload", methods=["POST"])
@require_auth
def broadcasts_upload():
    """Stores an attachment for a broadcast (immediate or scheduled) and
    returns a reference to it. Kept separate from /send-file since a
    broadcast attachment needs to persist and be reused for every
    recipient, rather than being sent once."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    original_name = file.filename
    safe_name = secure_filename(
        f"broadcast_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{original_name}"
    )
    filepath = os.path.join(MEDIA_FOLDER, safe_name)
    file.save(filepath)

    return jsonify({
        "file_name": original_name,
        "media_path": filepath,
        "media_type": resolve_media_type(original_name),
    }), 201


@broadcast_bp.route("/broadcasts/send-media", methods=["POST"])
@require_auth
def broadcasts_send_media():
    """Sends an already-uploaded broadcast attachment (from /broadcasts/upload)
    to one recipient, reusing the single stored file instead of saving a
    fresh copy to disk per recipient — /send-file re-uploads and re-saves
    the file every time it's called, which for a broadcast means one
    duplicate file per recipient (and, since its filenames are only
    timestamped to the second, recipients sent within the same second can
    even overwrite each other's copy)."""
    data = request.json or {}
    phone = data.get("phone")
    media_path = data.get("media_path")
    media_type = data.get("media_type", "document")
    caption = data.get("caption", "")

    if not phone or not media_path:
        return jsonify({"error": "phone and media_path required"}), 400

    # Only allow files actually inside our media folder — prevents this
    # endpoint being used to make the bot send an arbitrary file from disk.
    real_media_folder = os.path.realpath(MEDIA_FOLDER)
    real_path = os.path.realpath(media_path)
    if os.path.commonpath([real_media_folder, real_path]) != real_media_folder:
        return jsonify({"error": "Invalid media_path"}), 400
    if not os.path.exists(real_path):
        return jsonify({"error": "File not found"}), 404

    success, wa_id = send_media(phone, real_path, media_type, caption)
    if success:
        save_message(phone, caption, "bot", _socketio(),
                     message_type=media_type, file_name=os.path.basename(real_path),
                     media_path=real_path, whatsapp_message_id=wa_id)
        return jsonify({"success": True, "message_id": wa_id})
    return jsonify({"error": "Failed to send file"}), 500


@broadcast_bp.route("/broadcasts", methods=["POST"])
@require_auth
def broadcasts_create():
    data = request.json or {}
    message = data.get("message", "")
    recipients = data.get("recipients") or []
    file_name = data.get("file_name", "")
    media_path = data.get("media_path", "")
    media_type = data.get("media_type", "")
    scheduled_at = data.get("scheduled_at") or None
    min_delay_ms = data.get("min_delay_ms", 400)
    max_delay_ms = data.get("max_delay_ms", 900)

    if not recipients:
        return jsonify({"error": "recipients required"}), 400
    if not message and not file_name:
        return jsonify({"error": "message or file required"}), 400

    broadcast_id = create_broadcast(
        message, recipients, file_name=file_name,
        media_path=media_path, media_type=media_type,
        created_by=getattr(request, "dashboard_user_id", None),
        scheduled_at=scheduled_at,
        min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms,
    )
    return jsonify({"id": broadcast_id}), 201


@broadcast_bp.route("/broadcasts/<int:broadcast_id>", methods=["GET"])
@require_auth
def broadcasts_get(broadcast_id):
    row = get_broadcast(broadcast_id)
    if not row:
        return jsonify({"error": "Broadcast not found"}), 404
    return jsonify(row)


@broadcast_bp.route("/broadcasts/<int:broadcast_id>/recipient", methods=["PATCH"])
@require_auth
def broadcasts_update_recipient(broadcast_id):
    data = request.json or {}
    phone = data.get("phone")
    status = data.get("status")
    if not phone or status not in ("sent", "failed", "pending"):
        return jsonify({"error": "phone and valid status required"}), 400
    ok = set_recipient_status(broadcast_id, phone, status)
    if not ok:
        return jsonify({"error": "Broadcast not found"}), 404
    return jsonify({"success": True})


@broadcast_bp.route("/broadcasts/<int:broadcast_id>", methods=["PATCH"])
@require_auth
def broadcasts_finish(broadcast_id):
    data = request.json or {}
    status = data.get("status", "completed")
    if status not in ("completed", "stopped", "in_progress", "scheduled"):
        return jsonify({"error": "invalid status"}), 400
    ok = finish_broadcast(broadcast_id, status=status)
    if not ok:
        return jsonify({"error": "Broadcast not found"}), 404
    return jsonify({"success": True})


# ── Templates ────────────────────────────────────────────────────────────

@broadcast_bp.route("/broadcast-templates", methods=["GET"])
@require_auth
def templates_list():
    return jsonify(list_templates())


@broadcast_bp.route("/broadcast-templates", methods=["POST"])
@require_auth
def templates_create():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()
    if not name or not message:
        return jsonify({"error": "name and message required"}), 400
    template_id = create_template(
        name, message, created_by=getattr(request, "dashboard_user_id", None)
    )
    return jsonify({"id": template_id}), 201


@broadcast_bp.route("/broadcast-templates/<int:template_id>", methods=["DELETE"])
@require_auth
def templates_delete(template_id):
    ok = delete_template(template_id)
    if not ok:
        return jsonify({"error": "Template not found"}), 404
    return jsonify({"success": True})