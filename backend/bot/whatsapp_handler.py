import os
import time
import mimetypes
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_BASE = "https://graph.facebook.com/v18.0"
MEDIA_FOLDER = "media_files"

# Shared socketio reference set by app.py after init
_socketio = None

# ── Shared HTTP session ───────────────────────────────────────────────
# Every send_text / send_main_menu / send_service_menu / send_media call
# used to call the bare `requests.post(...)` function, which opens a
# fresh TCP + TLS connection to graph.facebook.com from scratch every
# single time. Since every incoming customer message results in at
# least one outgoing call here, that's a brand-new handshake on every
# reply. A shared Session with a pooled HTTPAdapter reuses the
# connection (HTTP keep-alive) across calls instead, which noticeably
# cuts the time it takes for a reply to actually reach WhatsApp.
_session = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=10,
    max_retries=Retry(total=0, connect=1, backoff_factor=0.1),
)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def set_socketio(sio):
    global _socketio
    _socketio = sio


def _headers():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _handle_wa_error(status_code, response_text, context=""):
    """Central error handler — emits dashboard warning on 401."""
    if status_code == 401:
        msg = (
            "⚠️ WhatsApp token has expired or is invalid. "
            "Messages cannot be sent. Please update WHATSAPP_TOKEN in your .env and restart the server."
        )
        print(f"[WhatsApp 401] {context}: {response_text}")
        if _socketio:
            _socketio.emit("wa_token_error", {
                "message": msg,
                "context": context,
            })
    elif status_code == 429:
        print(f"[WhatsApp 429] Rate limited. {context}")
    else:
        print(f"[WhatsApp {status_code}] {context}: {response_text}")


def send_text(to: str, message: str):
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
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            return True, msg_id
        _handle_wa_error(res.status_code, res.text, f"send_text to {to}")
        return False, None
    except Exception as e:
        print(f"send_text error: {e}")
        return False, None


_BIZ_SECTION = {
    "title": "BizAdvise Services",
    "rows": [
        {"id": "biz_business", "title": "Business Consultancy",    "description": "Register your business / company"},
        {"id": "biz_ngo",      "title": "NGO / Charity",           "description": "Start a charity or NGO"},
        {"id": "biz_tax",      "title": "Taxation Services",        "description": "NTN, income tax, sales tax"},
        {"id": "biz_accounts", "title": "Accountancy",              "description": "Bookkeeping, audits, reports"},
        {"id": "biz_legal",    "title": "Corporate Legal",          "description": "Contracts, compliance, opinions"},
        {"id": "biz_digital",  "title": "Digital Marketing",        "description": "SEO, ads, website, social media"},
        {"id": "biz_urgent",   "title": "Urgent Help",              "description": "FBR notice, SECP, tax deadline"},
        {"id": "biz_consult",  "title": "Talk to an Expert",        "description": "Speak with our team directly"},
    ]
}

_LAW_SECTION = {
    "title": "LawAdvise Services",
    "rows": [
        {"id": "online_nikah",   "title": "Online Nikah",           "description": "Online marriage guidance"},
        {"id": "court_marriage", "title": "Court Marriage",          "description": "Court marriage process"},
        {"id": "divorce_khula",  "title": "Divorce / Khula",        "description": "Divorce and Khula guidance"},
        {"id": "child_custody",  "title": "Child Custody",          "description": "Custody and guardianship"},
        {"id": "legal_docs",     "title": "Legal Documentation",    "description": "Document drafting"},
        {"id": "contact_us",     "title": "Talk to an Expert",      "description": "Speak with our team directly"},
    ]
}

# Appended only to a single-brand section (see send_main_menu below) so
# an ad-sourced customer looking at just BizAdvise or just LawAdvise has
# a tappable way to reach the combined menu, instead of needing to
# already know a typed FULL_MENU_TRIGGERS phrase like "full menu". Not
# added when both sections are already shown together — there's nothing
# further to escape to at that point.
_SHOW_FULL_MENU_ROW = {
    "id": "show_full_menu",
    "title": "See All Services",
    "description": "View Business + Legal services together",
}


def send_main_menu(to: str, source: str = None):
    """source: 'biz' -> BizAdvise section only, 'law' -> LawAdvise section
    only, anything else (None / '' / unrecognized) -> both sections, same
    as the original combined menu."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None
    try:
        if source == "biz":
            header_text = "BizAdvise Consulting"
            sections = [{**_BIZ_SECTION, "rows": _BIZ_SECTION["rows"] + [_SHOW_FULL_MENU_ROW]}]
        elif source == "law":
            header_text = "LawAdvise Consulting"
            sections = [{**_LAW_SECTION, "rows": _LAW_SECTION["rows"] + [_SHOW_FULL_MENU_ROW]}]
        else:
            header_text = "BizAdvise & LawAdvise Consulting"
            sections = [_BIZ_SECTION, _LAW_SECTION]

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header_text},
                "body": {"text": "Welcome! How can we assist you today? Please select a service:"},
                "footer": {"text": "Our experts are here to help you."},
                "action": {
                    "button": "View Services",
                    "sections": sections,
                }
            }
        }
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            return True, msg_id
        _handle_wa_error(res.status_code, res.text, f"send_main_menu to {to}")
        return False, None
    except Exception as e:
        print(f"send_main_menu error: {e}")
        return False, None


def send_greeting_buttons(to: str, body_text: str):
    """Sends the plain-greeting reply as 3 tappable quick-reply buttons
    (Business Services / Legal Services / Full Menu) instead of relying
    on the customer to type bizservices / lawservices / menu out by
    hand. Same interactive 'button' payload shape as send_nav_buttons,
    just with no header and the greeting text as the body."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "greet_biz", "title": "Business Services"}},
                        {"type": "reply", "reply": {"id": "greet_law", "title": "Legal Services"}},
                        {"type": "reply", "reply": {"id": "greet_menu", "title": "Full Menu"}},
                    ]
                }
            }
        }
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_greeting_buttons to {to}")
        return False, None
    except Exception as e:
        print(f"send_greeting_buttons error: {e}")
        return False, None


# ── Category screens (tier 2 — one level below the main menu) ───────────
# Every category is a WhatsApp *list* message now, never a 3-button
# message, because a button message caps out at 3 buttons and every
# category needs room for nav rows on top of its own content:
#
#   LawAdvise categories (only 3 content items each) get BOTH a Back
#   row and a Main Menu row — 5 rows total, plenty of headroom under
#   the list format's 10-row cap. Back and Main Menu happen to lead to
#   the same place here (the category sits directly under the main
#   menu), but both are shown anyway so every screen in the whole tree
#   carries the same two nav options, with no exceptions to remember.
#
#   BizAdvise categories (up to 9 content items, e.g. Taxation) only
#   have room for ONE extra row, so they get a single "Back to Main
#   Menu" row instead of two — still exactly "home", just one tap.
#
# Leaf answers (Procedure, NTN Individual, etc.) are a separate, later
# screen — see send_nav_buttons — where Back and Main Menu genuinely
# differ (Back returns to this category list, Main Menu skips straight
# home), and that fits fine as a 2-button message.

_LAW_CATEGORY_HEADERS = {
    "online_nikah":   "Online Marriage / Nikah",
    "court_marriage": "Court Marriage",
    "divorce_khula":  "Divorce / Khula",
    "child_custody":  "Child Custody / Guardianship",
    "maintenance":    "Maintenance / Dowery",
    "property_law":   "Property Law",
    "inheritance":    "Inheritance",
    "corporate_law":  "Corporate Law",
    "legal_docs":     "Legal Documentation",
}

_LAW_CATEGORY_ITEMS = {
    "online_nikah": [
        {"id": "nikah_procedure", "title": "Procedure"},
        {"id": "nikah_documents", "title": "Documents"},
        {"id": "nikah_consult",   "title": "Talk to Lawyer"},
    ],
    "court_marriage": [
        {"id": "court_procedure", "title": "Procedure"},
        {"id": "court_documents", "title": "Documents"},
        {"id": "court_consult",   "title": "Book Consultation"},
    ],
    "divorce_khula": [
        {"id": "divorce_procedure", "title": "Procedure"},
        {"id": "divorce_timeline",  "title": "Timeline"},
        {"id": "divorce_consult",   "title": "Book Consultation"},
    ],
    "child_custody": [
        {"id": "custody_procedure", "title": "Procedure"},
        {"id": "custody_timeline",  "title": "Timeline"},
        {"id": "custody_consult",   "title": "Talk to Expert"},
    ],
    "maintenance": [
        {"id": "maintenance_procedure", "title": "Procedure"},
        {"id": "maintenance_timeline",  "title": "Timeline"},
        {"id": "maintenance_consult",   "title": "Talk to Expert"},
    ],
    "property_law": [
        {"id": "property_procedure", "title": "Procedure"},
        {"id": "property_timeline",  "title": "Timeline"},
        {"id": "property_consult",   "title": "Book Consultation"},
    ],
    "inheritance": [
        {"id": "inheritance_procedure", "title": "Procedure"},
        {"id": "inheritance_timeline",  "title": "Timeline"},
        {"id": "inheritance_consult",   "title": "Talk to Expert"},
    ],
    "corporate_law": [
        {"id": "corporate_procedure", "title": "Procedure"},
        {"id": "corporate_timeline",  "title": "Timeline"},
        {"id": "corporate_consult",   "title": "Talk to Expert"},
    ],
    "legal_docs": [
        {"id": "docs_procedure", "title": "Procedure"},
        {"id": "docs_timeline",  "title": "Timeline"},
        {"id": "docs_consult",   "title": "Book Consultation"},
    ],
}

_BIZ_CATEGORY_HEADERS = {
    "biz_business": "Business Consultancy",
    "biz_tax":      "Taxation Services",
    "biz_accounts": "Accountancy Services",
    "biz_legal":    "Corporate Legal Advisory",
}

_BIZ_CATEGORY_ITEMS = {
    "biz_business": [
        {"id": "biz_business_1", "title": "Private Ltd/SMC/LLC"},
        {"id": "biz_business_2", "title": "Partnership / AOP"},
        {"id": "biz_business_3", "title": "Proprietorship"},
        {"id": "biz_business_4", "title": "Trademark Registration"},
        {"id": "biz_business_5", "title": "Copyright Registration"},
        {"id": "biz_business_6", "title": "Patent Registration"},
        {"id": "biz_business_7", "title": "Other Registrations"},
        {"id": "biz_business_8", "title": "Talk to an Expert"},
    ],
    "biz_tax": [
        {"id": "biz_tax_1", "title": "NTN - Individual"},
        {"id": "biz_tax_2", "title": "NTN - Business"},
        {"id": "biz_tax_3", "title": "Income Tax Return"},
        {"id": "biz_tax_4", "title": "Sales Tax Registration"},
        {"id": "biz_tax_5", "title": "Sales Tax Monthly Rtn"},
        {"id": "biz_tax_6", "title": "Provincial Sales Tax"},
        {"id": "biz_tax_7", "title": "ATL Status"},
        {"id": "biz_tax_8", "title": "Tax Notices"},
        {"id": "biz_tax_9", "title": "Tax Refund"},
        # NOTE: no "Talk to an Expert" row here on purpose — Taxation
        # already has 9 content rows + 1 nav row = 10, the list format's
        # hard cap. Anyone wanting an expert can reach "Talk to an
        # Expert" one tap further via the main menu itself.
    ],
    "biz_accounts": [
        {"id": "biz_accounts_1", "title": "Bookkeeping"},
        {"id": "biz_accounts_2", "title": "Annual Accounts Mgmt"},
        {"id": "biz_accounts_3", "title": "Audited Accounts"},
        {"id": "biz_accounts_4", "title": "Internal/External Audit"},
        {"id": "biz_accounts_5", "title": "Financial Reporting"},
        {"id": "biz_accounts_6", "title": "Accounting Consultation"},
        {"id": "biz_accounts_7", "title": "Talk to an Expert"},
    ],
    "biz_legal": [
        {"id": "biz_legal_1", "title": "Contract Drafting"},
        {"id": "biz_legal_2", "title": "Corporate Compliance"},
        {"id": "biz_legal_3", "title": "Legal Notices"},
        {"id": "biz_legal_4", "title": "Legal Opinions"},
        {"id": "biz_legal_5", "title": "Regulatory Compliance"},
        {"id": "biz_legal_6", "title": "Company Secretarial"},
        {"id": "biz_legal_7", "title": "Legal Consultation"},
        {"id": "biz_legal_8", "title": "Talk to an Expert"},
    ],
}

_NAV_BACK_ROW = {"id": "nav_back", "title": "🔙 Back"}
_NAV_MAIN_ROW = {"id": "nav_main", "title": "🏠 Main Menu"}
_NAV_MAIN_ONLY_ROW = {"id": "nav_main", "title": "🔙 Back to Main Menu"}


def send_service_menu(to: str, category_id: str):
    """Sends a category screen (tier 2) as a WhatsApp list — the
    content items belonging to this category, plus nav row(s) at the
    bottom. See the block comment above for why Law gets 2 nav rows
    and Biz gets 1."""
    if category_id in _LAW_CATEGORY_ITEMS:
        header = _LAW_CATEGORY_HEADERS[category_id]
        rows = list(_LAW_CATEGORY_ITEMS[category_id]) + [_NAV_BACK_ROW, _NAV_MAIN_ROW]
    elif category_id in _BIZ_CATEGORY_ITEMS:
        header = _BIZ_CATEGORY_HEADERS[category_id]
        rows = list(_BIZ_CATEGORY_ITEMS[category_id]) + [_NAV_MAIN_ONLY_ROW]
    else:
        return False, None
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header},
                "body": {"text": "What would you like to know?"},
                "action": {
                    "button": "View Options",
                    "sections": [{"title": header, "rows": rows}],
                }
            }
        }
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_service_menu to {to}")
        return False, None
    except Exception as e:
        print(f"send_service_menu error: {e}")
        return False, None


def send_nav_buttons(to: str, header_text: str, body_text: str):
    """Sends a leaf answer screen (tier 3) with exactly the two nav
    buttons every leaf screen carries: 🔙 Back (returns to the category
    list this leaf came from) and 🏠 Main Menu (jumps straight home).
    2 buttons comfortably fits WhatsApp's 3-button cap.

    header_text may be empty/None — WhatsApp allows an interactive
    button message with no header."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None
    try:
        interactive = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "nav_back", "title": "🔙 Back"}},
                    {"type": "reply", "reply": {"id": "nav_main", "title": "🏠 Main Menu"}},
                ]
            }
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_nav_buttons to {to}")
        return False, None
    except Exception as e:
        print(f"send_nav_buttons error: {e}")
        return False, None


def send_media(to: str, file_path: str, media_type: str, caption: str = ""):
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
        res = _session.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=30,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_media to {to}")
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
            res = _session.post(
                f"{WA_BASE}/{PHONE_NUMBER_ID}/media",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                files={"file": (os.path.basename(file_path), f, mime_type)},
                data={"messaging_product": "whatsapp", "type": media_type},
            )
        if res.status_code == 200:
            return res.json().get("id")
        _handle_wa_error(res.status_code, res.text, "_upload_media")
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


def cleanup_old_media(days: int = 30):
    """Delete media files older than `days` days. Call on a schedule."""
    if not os.path.exists(MEDIA_FOLDER):
        return 0, 0
    cutoff = time.time() - (days * 86400)
    deleted = 0
    freed = 0
    for filename in os.listdir(MEDIA_FOLDER):
        filepath = os.path.join(MEDIA_FOLDER, filename)
        try:
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff:
                size = os.path.getsize(filepath)
                os.remove(filepath)
                deleted += 1
                freed += size
        except Exception as e:
            print(f"cleanup error for {filepath}: {e}")
    if deleted:
        print(f"[Media cleanup] Deleted {deleted} files, freed {freed / 1024 / 1024:.1f} MB")
    return deleted, freed