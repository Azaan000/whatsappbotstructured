import os
import hmac
import hashlib
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, current_app

from models.user import save_user, get_user_mode
from models.message import save_message, update_message_status
from models.database import get_db
from bot.ai_client import ask_ai
from bot.whatsapp_handler import send_text

webhook_bp = Blueprint("webhook", __name__)

_executor = ThreadPoolExecutor(max_workers=10)
_processed_ids = set()


def _get_socketio():
    return current_app.extensions["socketio"]


def _already_processed(msg_id):
    if not msg_id:
        return False
    if msg_id in _processed_ids:
        return True
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM messages WHERE whatsapp_message_id=?", (msg_id,)
        )
        exists = cursor.fetchone() is not None
        if exists:
            _processed_ids.add(msg_id)
        return exists
    finally:
        conn.close()


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify the request actually came from Meta."""
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return True  # Skip verification if secret not configured
    try:
        expected = "sha256=" + hmac.new(
            app_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


@webhook_bp.route("/webhook", methods=["GET"])
def verify():
    verify_token = os.getenv("VERIFY_TOKEN")
    incoming = request.args.get("hub.verify_token")
    print(f"[Webhook verify] incoming='{incoming}' expected='{verify_token}'")
    if incoming and incoming == verify_token:
        return request.args.get("hub.challenge")
    return "Forbidden", 403


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        print("Invalid webhook signature — request rejected")
        return "Forbidden", 403

    data = request.get_json()
    socketio = _get_socketio()

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Extract contact names
                contacts = {}
                for contact in value.get("contacts", []):
                    phone = contact.get("wa_id", "")
                    name = contact.get("profile", {}).get("name", "")
                    if phone and name:
                        contacts[phone] = name

                for status_update in value.get("statuses", []):
                    msg_id = status_update.get("id")
                    status = status_update.get("status")
                    if msg_id and status:
                        update_message_status(msg_id, status, socketio)

                for msg in value.get("messages", []):
                    msg_id = msg.get("id")

                    if _already_processed(msg_id):
                        print(f"[Webhook] Duplicate skipped: {msg_id}")
                        continue

                    if msg_id:
                        _processed_ids.add(msg_id)

                    # Cap processed_ids set size to prevent memory growth
                    if len(_processed_ids) > 10000:
                        _processed_ids.clear()

                    phone = msg["from"]
                    name = contacts.get(phone, "")
                    _handle_message(msg, socketio, name=name)

    except Exception as e:
        print(f"Webhook error: {e}")

    return "OK", 200


def _handle_message(msg, socketio, name=""):
    phone = msg["from"]
    msg_type = msg.get("type", "text")
    msg_id = msg.get("id")

    save_user(phone, socketio, name=name)

    if msg_type == "text":
        text = msg["text"]["body"]

        # Emit typing indicator to dashboard
        socketio.emit("user_typing", {"phone": phone, "typing": True})

        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)

        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)
        else:
            print(f"Human mode active for {phone} — AI skipped")

    elif msg_type in ("image", "audio", "document", "video"):
        media_info = msg.get(msg_type, {})
        caption = media_info.get("caption", "") or f"Sent a {msg_type}"
        save_message(phone, caption, "user", socketio,
                     message_type=msg_type, whatsapp_message_id=msg_id)

    elif msg_type == "button":
        text = msg["button"]["text"]
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if "list_reply" in interactive:
            text = interactive["list_reply"]["title"]
            save_message(phone, text, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)


def _process_ai_reply(phone, text, socketio):
    try:
        reply = ask_ai(text)
        success, wa_msg_id = send_text(phone, reply)
        status = "sent" if success else "failed"
        save_message(phone, reply, "bot", socketio,
                     status=status, whatsapp_message_id=wa_msg_id, source="ai")
    except Exception as e:
        print(f"AI reply error for {phone}: {e}")