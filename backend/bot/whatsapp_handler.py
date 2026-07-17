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


def send_main_menu(to: str):
    """Send the interactive list menu when a new user starts a conversation."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "LawAdvise Consulting"
                },
                "body": {
                    "text": "Welcome to LawAdvise Consulting! ⚖️\n\nHow can we assist you today? Please select a service below:"
                },
                "footer": {
                    "text": "Our legal team is here to help you."
                },
                "action": {
                    "button": "View Services",
                    "sections": [
                        {
                            "title": "Legal Services",
                            "rows": [
                                {
                                    "id": "online_nikah",
                                    "title": "Online Marriage / Nikah",
                                    "description": "Get guidance on online Nikah procedure"
                                },
                                {
                                    "id": "court_marriage",
                                    "title": "Court Marriage",
                                    "description": "Learn about court marriage process"
                                },
                                {
                                    "id": "divorce_khula",
                                    "title": "Divorce / Khula",
                                    "description": "Divorce and Khula legal guidance"
                                },
                                {
                                    "id": "child_custody",
                                    "title": "Child Custody / Guardianship",
                                    "description": "Child custody and guardianship matters"
                                },
                                {
                                    "id": "maintenance",
                                    "title": "Maintenance / Dowery",
                                    "description": "Nafaqa and dowery legal matters"
                                }
                            ]
                        },
                        {
                            "title": "More Services",
                            "rows": [
                                {
                                    "id": "property_law",
                                    "title": "Property Law",
                                    "description": "Property disputes and documentation"
                                },
                                {
                                    "id": "inheritance",
                                    "title": "Inheritance",
                                    "description": "Inheritance and succession matters"
                                },
                                {
                                    "id": "corporate_law",
                                    "title": "Corporate Law",
                                    "description": "Business and corporate legal matters"
                                },
                                {
                                    "id": "legal_docs",
                                    "title": "Legal Documentation",
                                    "description": "Document drafting and verification"
                                },
                                {
                                    "id": "contact_us",
                                    "title": "Contact Us / Book Consultation",
                                    "description": "Speak directly with our legal team"
                                }
                            ]
                        }
                    ]
                }
            }
        }

        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            print(f"Main menu sent to {to}")
            return True, msg_id

        print(f"Failed to send menu: {res.status_code} {res.text}")
        return False, None

    except Exception as e:
        print(f"send_main_menu error: {e}")
        return False, None


def send_service_menu(to: str, service_id: str):
    """Send a follow-up button menu based on which service was selected."""
    menus = {
        "online_nikah": {
            "header": "🕌 Online Marriage / Nikah",
            "body": "What would you like to know about Online Nikah?",
            "buttons": [
                {"id": "nikah_procedure", "title": "📋 Procedure"},
                {"id": "nikah_documents", "title": "📄 Documents"},
                {"id": "nikah_consult", "title": "💬 Talk to Lawyer"},
            ]
        },
        "court_marriage": {
            "header": "💍 Court Marriage",
            "body": "What would you like to know about Court Marriage?",
            "buttons": [
                {"id": "court_procedure", "title": "📋 Procedure"},
                {"id": "court_documents", "title": "📄 Documents"},
                {"id": "court_consult", "title": "💬 Book Consultation"},
            ]
        },
        "divorce_khula": {
            "header": "📄 Divorce / Khula",
            "body": "What would you like to know about Divorce or Khula?",
            "buttons": [
                {"id": "divorce_procedure", "title": "📋 Procedure"},
                {"id": "divorce_timeline", "title": "⏳ Timeline"},
                {"id": "divorce_consult", "title": "💬 Book Consultation"},
            ]
        },
        "child_custody": {
            "header": "👶 Child Custody / Guardianship",
            "body": "What would you like to know?",
            "buttons": [
                {"id": "custody_procedure", "title": "📋 Procedure"},
                {"id": "custody_timeline", "title": "⏳ Timeline"},
                {"id": "custody_consult", "title": "💬 Talk to Expert"},
            ]
        },
        "maintenance": {
            "header": "💰 Maintenance / Dowery",
            "body": "What would you like to know?",
            "buttons": [
                {"id": "maintenance_procedure", "title": "📋 Procedure"},
                {"id": "maintenance_timeline", "title": "⏳ Timeline"},
                {"id": "maintenance_consult", "title": "💬 Talk to Expert"},
            ]
        },
        "property_law": {
            "header": "🏠 Property Law",
            "body": "What would you like to know about Property Law?",
            "buttons": [
                {"id": "property_procedure", "title": "📋 Procedure"},
                {"id": "property_timeline", "title": "⏳ Timeline"},
                {"id": "property_consult", "title": "💬 Book Consultation"},
            ]
        },
        "inheritance": {
            "header": "📜 Inheritance",
            "body": "What would you like to know about Inheritance?",
            "buttons": [
                {"id": "inheritance_procedure", "title": "📋 Procedure"},
                {"id": "inheritance_timeline", "title": "⏳ Timeline"},
                {"id": "inheritance_consult", "title": "💬 Talk to Expert"},
            ]
        },
        "corporate_law": {
            "header": "🤝 Corporate Law",
            "body": "What would you like to know about Corporate Law?",
            "buttons": [
                {"id": "corporate_procedure", "title": "📋 Procedure"},
                {"id": "corporate_timeline", "title": "⏳ Timeline"},
                {"id": "corporate_consult", "title": "💬 Talk to Expert"},
            ]
        },
        "legal_docs": {
            "header": "📑 Legal Documentation",
            "body": "What would you like to know about Legal Documentation?",
            "buttons": [
                {"id": "docs_procedure", "title": "📋 Procedure"},
                {"id": "docs_timeline", "title": "⏳ Timeline"},
                {"id": "docs_consult", "title": "💬 Book Consultation"},
            ]
        },
    }

    menu = menus.get(service_id)
    if not menu:
        return False, None

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": menu["header"]
                },
                "body": {
                    "text": menu["body"]
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": btn["id"],
                                "title": btn["title"]
                            }
                        }
                        for btn in menu["buttons"]
                    ]
                }
            }
        }

        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            print(f"Service menu sent to {to} for {service_id}")
            return True, msg_id

        print(f"Failed to send service menu: {res.status_code} {res.text}")
        return False, None

    except Exception as e:
        print(f"send_service_menu error: {e}")
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