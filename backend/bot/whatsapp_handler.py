import os
import mimetypes
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_BASE = f"https://graph.facebook.com/v18.0"


def _headers():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def send_text(to: str, message: str):
    """Send a plain text message. Returns (success, whatsapp_message_id)."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("WhatsApp credentials missing")
        return False, None

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            print(f"Sent to {to}: {message[:50]}... (id={msg_id})")
            return True, msg_id

        print(f"WhatsApp error {res.status_code}: {res.text}")
        return False, None

    except Exception as e:
        print(f"send_text error: {e}")
        return False, None


def send_media(to: str, file_path: str, media_type: str, caption: str = ""):
    """Upload file to WhatsApp then send it. Returns (success, whatsapp_message_id)."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None

    media_id = _upload_media(file_path, media_type)
    if not media_id:
        return False, None

    try:
        media_payload = {"id": media_id}
        if caption:
            media_payload["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            return True, msg_id

        print(f"Failed to send media: {res.text}")
        return False, None

    except Exception as e:
        print(f"send_media error: {e}")
        return False, None


def _upload_media(file_path: str, media_type: str):
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = {
                "image": "image/jpeg",
                "audio": "audio/mpeg",
                "video": "video/mp4",
            }.get(media_type, "application/octet-stream")

        with open(file_path, "rb") as f:
            res = requests.post(
                f"{WA_BASE}/{PHONE_NUMBER_ID}/media",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                files={"file": (os.path.basename(file_path), f, mime_type)},
                data={"messaging_product": "whatsapp", "type": media_type},
            )

        if res.status_code == 200:
            media_id = res.json().get("id")
            print(f"Media uploaded: {media_id}")
            return media_id

        print(f"Upload failed: {res.text}")
        return None

    except Exception as e:
        print(f"_upload_media error: {e}")
        return None


def resolve_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image"
    if ext in {"mp3", "wav", "ogg"}:
        return "audio"
    if ext in {"mp4", "mov", "avi"}:
        return "video"
    return "document"
