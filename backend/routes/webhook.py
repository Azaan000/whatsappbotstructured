import os
import hmac
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, current_app

from models.user import save_user, get_user_mode
from models.message import save_message, update_message_status
from models.database import get_db
from bot.ai_client import ask_ai
from bot.whatsapp_handler import send_text, send_main_menu, send_service_menu

webhook_bp = Blueprint("webhook", __name__)

_executor = ThreadPoolExecutor(max_workers=10)
_processed_ids = set()
_user_service_context = {}  # tracks which service a user last selected

CONTACT = "03003029093 / 03332454111"

# ── Button responses ──────────────────────────────────────────────────────

BUTTON_RESPONSES = {
    # ── BizAdvise: Business Consultancy ──
    "biz_business": (
        "🏢 *Business Consultancy*\n\n"
        "We offer:\n"
        "• Private Limited / SMC / LLC Registration\n"
        "• Partnership / AOP Registration\n"
        "• Proprietorship Registration\n"
        "• Trademark & Copyright Registration\n"
        "• Patent, KCCI, PEC, DTS, PSEB Registration\n\n"
        f"Reply with what you need or contact us: {CONTACT}"
    ),
    "biz_ngo": (
        "💰 *NGO / Charity Registration*\n\n"
        "Required Documents:\n"
        "• CNIC of all members\n"
        "• Contact details of all members\n"
        "• NGO Name & Office Address\n"
        "• Nature of charity (Education, Health, Food, etc.)\n"
        "• Utility Bill\n"
        "• Rent Agreement / Ownership Documents\n\n"
        f"Cost & timeline may vary. Contact us: {CONTACT}"
    ),
    "biz_tax": (
        "💰 *Taxation Services*\n\n"
        "We handle:\n"
        "• NTN Registration (Individual: Rs.500 / 30 mins)\n"
        "• Income Tax Returns (Salaried, Freelancer, Business, Company)\n"
        "• Sales Tax Registration & Monthly Returns\n"
        "• Provincial Tax (SRB, PRA, BRA, KPRA)\n"
        "• ATL Status & Restoration\n"
        "• Tax Notices (FBR, Audit, Section 111/114/122)\n"
        "• Tax Refunds\n\n"
        f"Contact our tax experts: {CONTACT}"
    ),
    "biz_accounts": (
        "📊 *Accountancy Services*\n\n"
        "We offer:\n"
        "• Bookkeeping (Sales, Purchases, Bank Reconciliation, etc.)\n"
        "• Annual Accounts Management\n"
        "• Audited Accounts\n"
        "• Internal & External Audit\n"
        "• Financial Reporting (Monthly, Quarterly, Annual)\n"
        "• Accounting Software (QuickBooks, Xero, Excel)\n\n"
        "Our bookkeeping specialists can help you maintain accurate and up-to-date financial records.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_legal": (
        "⚖️ *Corporate Legal Advisory*\n\n"
        "We handle:\n"
        "• Contract Drafting (Business, Partnership, Employment, NDA, MoU)\n"
        "• Corporate Compliance (SECP, Annual Returns, Board Resolutions)\n"
        "• Legal Notices (Recovery, Breach of Contract, Demand, Tenant)\n"
        "• Legal Opinions & Contract Reviews\n"
        "• Regulatory Compliance (SECP, FBR, IPO, Labour Laws)\n"
        "• Company Secretarial Services\n\n"
        "Our legal advisory specialists will assess your requirements and recommend the most suitable solution.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_digital": (
        "📈 *Digital Marketing*\n\n"
        "We offer:\n"
        "• Social Media Marketing\n"
        "• Meta Ads (Facebook & Instagram)\n"
        "• Google Ads\n"
        "• SEO (Search Engine Optimization)\n"
        "• Website Development\n"
        "• Content Writing\n"
        "• Branding & Graphic Design\n\n"
        "Our digital marketing specialists will evaluate your business objectives and recommend the most effective strategy.\n\n"
        f"Contact us: {CONTACT}"
    ),
    "biz_urgent": (
        "🚨 *Urgent Help*\n\n"
        "If you have received any of the following, contact us immediately:\n\n"
        f"• FBR Notice Received → {CONTACT}\n"
        f"• SECP Deadline → {CONTACT}\n"
        f"• Tax Return Deadline → {CONTACT}\n"
        f"• Legal Notice Received → {CONTACT}\n\n"
        "Our team is ready to assist you right away."
    ),
    "biz_consult": (
        "👨‍💼 *Talk to an Expert*\n\n"
        "Our consultants are available to help you.\n\n"
        f"📞 Call or WhatsApp: {CONTACT}\n\n"
        "Please share your Name, Mobile Number, and Best Time to Call and we will get back to you shortly."
    ),

    # ── LawAdvise ──
    "nikah_procedure": f"📋 *Online Nikah Procedure:*\n\n• At least one party must be residing outside Pakistan.\n• The legal process is identical to a conventional Nikah.\n• One party participates remotely through a secure online platform.\n\nWould you like to book a consultation with our legal team?",
    "nikah_documents": f"📄 *Required Documents for Online Nikah:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "nikah_consult": "💬 Our legal team will be in touch with you shortly to assist with your Online Nikah. Please share your preferred contact time if needed.",
    "court_procedure": "📋 *Court Marriage Procedure:*\n\n• Both parties must be present in person.\n• All legal requirements are the same as a conventional Nikah.\n\nWould you like to book a consultation?",
    "court_documents": "📄 *Required Documents for Court Marriage:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "court_consult": "💬 Our legal team will be in touch shortly to assist you with Court Marriage.",
    "divorce_procedure": "📋 *Divorce / Khula Procedure:*\n\nEvery case is unique. Please consult one of our legal experts for advice tailored to your specific situation.",
    "divorce_timeline": "⏳ *Divorce / Khula Timeline:*\n\nThe timeline varies depending on the nature and complexity of your case.",
    "divorce_consult": "💬 Our legal expert will contact you shortly to discuss your Divorce / Khula case. Your matter will be handled with full confidentiality.",
    "custody_procedure": "📋 *Child Custody / Guardianship:*\n\nThis matter requires a detailed legal assessment. Our legal team will be happy to assist you personally.",
    "custody_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "custody_consult": "💬 Our legal expert will contact you shortly regarding Child Custody / Guardianship.",
    "maintenance_procedure": "📋 *Maintenance (Nafaqa) / Dowery:*\n\nThis matter cannot be accurately assessed through chat alone. Our legal team will assist you personally.",
    "maintenance_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "maintenance_consult": "💬 Our legal expert will contact you shortly regarding your Maintenance / Dowery matter.",
    "property_procedure": "📋 *Property Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "property_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "property_consult": "💬 Our property law expert will contact you shortly.",
    "inheritance_procedure": "📋 *Inheritance:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "inheritance_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "inheritance_consult": "💬 Our legal expert will contact you shortly regarding your Inheritance matter.",
    "corporate_procedure": "📋 *Corporate Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "corporate_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "corporate_consult": "💬 Our corporate law expert will contact you shortly.",
    "docs_procedure": "📋 *Legal Documentation:*\n\nThis requires a detailed legal consultation. Our legal team can assist with document drafting and verification.",
    "docs_timeline": "⏳ *Timeline:*\n\nThe duration depends on the type and complexity of documentation required.",
    "docs_consult": "💬 Our legal team will contact you shortly to assist with your documentation needs.",
    "contact_us": f"📞 *Contact Us:*\n\nOur team will be in touch with you shortly.\n\n📱 {CONTACT}\n\nPlease share your Name, Mobile Number, and Best Time to Call.",
}

SERVICE_MENU_IDS = {
    "online_nikah", "court_marriage", "divorce_khula",
    "child_custody", "maintenance", "property_law",
    "inheritance", "corporate_law", "legal_docs"
}

# ── Text menus (fallback) ─────────────────────────────────────────────────

TEXT_MAIN_MENU_1 = """Welcome to *BizAdvise & LawAdvise Consulting* ⚖️🏢

How can we assist you? Please reply with a number:

*BizAdvise Services:*
1️⃣ Start a New Business / Business Consultancy
2️⃣ Start a Charity / NGO Registration
3️⃣ File My Taxes — Taxation Services
4️⃣ Manage My Accounts — Accountancy
5️⃣ Corporate Legal Advisory
6️⃣ Grow My Business Online — Digital Marketing
7️⃣ 🚨 Urgent Help"""

TEXT_MAIN_MENU_2 = """*LawAdvise Services:*
8️⃣ Online Marriage / Online Nikah
9️⃣ Court Marriage
🔟 Divorce / Khula
1️⃣1️⃣ Child Custody / Guardianship
1️⃣2️⃣ Maintenance (Nafaqa) / Dowery
1️⃣3️⃣ Property Law
1️⃣4️⃣ Inheritance
1️⃣5️⃣ Legal Documentation
1️⃣6️⃣ 👨‍💼 Talk to an Expert

_Reply with a number to get started._"""

TEXT_SERVICE_MENUS = {
    "1":  ("Start a New Business / Business Consultancy", "biz_business"),
    "2":  ("NGO / Charity Registration", "biz_ngo"),
    "3":  ("Taxation Services", "biz_tax"),
    "4":  ("Accountancy Services", "biz_accounts"),
    "5":  ("Corporate Legal Advisory", "biz_legal"),
    "6":  ("Digital Marketing", "biz_digital"),
    "7":  ("Urgent Help", "biz_urgent"),
    "8":  ("Online Marriage / Online Nikah", "online_nikah"),
    "9":  ("Court Marriage", "court_marriage"),
    "10": ("Divorce / Khula", "divorce_khula"),
    "11": ("Child Custody / Guardianship", "child_custody"),
    "12": ("Maintenance / Dowery", "maintenance"),
    "13": ("Property Law", "property_law"),
    "14": ("Inheritance", "inheritance"),
    "15": ("Legal Documentation", "legal_docs"),
    "16": ("Talk to an Expert", "contact_us"),
}

# BizAdvise services respond directly from BUTTON_RESPONSES — no sub-menu needed
BIZ_DIRECT_IDS = {
    "biz_business", "biz_ngo", "biz_tax", "biz_accounts",
    "biz_legal", "biz_digital", "biz_urgent", "biz_consult", "contact_us"
}

TEXT_SUB_MENU = {
    "online_nikah":   "You selected *Online Marriage / Online Nikah* 🕌\n\nReply with:\n1️⃣ Procedure\n2️⃣ Documents\n3️⃣ Talk to a Lawyer",
    "court_marriage": "You selected *Court Marriage* 💍\n\nReply with:\n1️⃣ Procedure\n2️⃣ Documents\n3️⃣ Book Consultation",
    "divorce_khula":  "You selected *Divorce / Khula* 📄\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
    "child_custody":  "You selected *Child Custody / Guardianship* 👶\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "maintenance":    "You selected *Maintenance / Dowery* 💰\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "property_law":   "You selected *Property Law* 🏠\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
    "inheritance":    "You selected *Inheritance* 📜\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "corporate_law":  "You selected *Corporate Law* 🤝\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Talk to Expert",
    "legal_docs":     "You selected *Legal Documentation* 📑\n\nReply with:\n1️⃣ Procedure\n2️⃣ Timeline\n3️⃣ Book Consultation",
}

TEXT_SUB_RESPONSES = {
    "online_nikah":   {"1": BUTTON_RESPONSES["nikah_procedure"],    "2": BUTTON_RESPONSES["nikah_documents"],       "3": BUTTON_RESPONSES["nikah_consult"]},
    "court_marriage": {"1": BUTTON_RESPONSES["court_procedure"],    "2": BUTTON_RESPONSES["court_documents"],       "3": BUTTON_RESPONSES["court_consult"]},
    "divorce_khula":  {"1": BUTTON_RESPONSES["divorce_procedure"],  "2": BUTTON_RESPONSES["divorce_timeline"],      "3": BUTTON_RESPONSES["divorce_consult"]},
    "child_custody":  {"1": BUTTON_RESPONSES["custody_procedure"],  "2": BUTTON_RESPONSES["custody_timeline"],      "3": BUTTON_RESPONSES["custody_consult"]},
    "maintenance":    {"1": BUTTON_RESPONSES["maintenance_procedure"], "2": BUTTON_RESPONSES["maintenance_timeline"],"3": BUTTON_RESPONSES["maintenance_consult"]},
    "property_law":   {"1": BUTTON_RESPONSES["property_procedure"], "2": BUTTON_RESPONSES["property_timeline"],     "3": BUTTON_RESPONSES["property_consult"]},
    "inheritance":    {"1": BUTTON_RESPONSES["inheritance_procedure"],"2": BUTTON_RESPONSES["inheritance_timeline"],"3": BUTTON_RESPONSES["inheritance_consult"]},
    "corporate_law":  {"1": BUTTON_RESPONSES["corporate_procedure"],"2": BUTTON_RESPONSES["corporate_timeline"],   "3": BUTTON_RESPONSES["corporate_consult"]},
    "legal_docs":     {"1": BUTTON_RESPONSES["docs_procedure"],     "2": BUTTON_RESPONSES["docs_timeline"],         "3": BUTTON_RESPONSES["docs_consult"]},
}

MENU_TRIGGERS = {"menu", "options", "start", "help", "main menu", "مینو", "آپشنز"}
GREETING_WORDS = {"hi", "hello", "hey", "helo", "hii", "salam", "assalam", "السلام", "assalamualaikum", "aoa"}


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
        cursor.execute("SELECT id FROM messages WHERE whatsapp_message_id=?", (msg_id,))
        exists = cursor.fetchone() is not None
        if exists:
            _processed_ids.add(msg_id)
        return exists
    finally:
        conn.close()


def _verify_signature(payload: bytes, signature: str) -> bool:
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return True
    try:
        expected = "sha256=" + hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
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

    is_new = save_user(phone, socketio, name=name)

    if msg_type == "text":
        text = msg["text"]["body"].strip()
        socketio.emit("user_typing", {"phone": phone, "typing": True})
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)

        text_lower = text.lower()

        # New user or explicit menu trigger
        if is_new or text_lower in MENU_TRIGGERS:
            _executor.submit(_send_welcome_menu, phone, socketio)
            return

        # Greetings for returning users — AI handles
        if text_lower in GREETING_WORDS:
            mode = get_user_mode(phone)
            if mode == 0:
                _executor.submit(_process_ai_reply, phone, text, socketio)
            return

        # Sub-menu: user replied 1/2/3 after selecting a LawAdvise service
        if phone in _user_service_context and text in ("1", "2", "3"):
            service = _user_service_context[phone]
            response = TEXT_SUB_RESPONSES.get(service, {}).get(text)
            if response:
                _executor.submit(_send_text_reply, phone, response, socketio)
                del _user_service_context[phone]
                return

        # Top-level number selection (1-16)
        if text in TEXT_SERVICE_MENUS:
            title, service_id = TEXT_SERVICE_MENUS[text]
            if service_id in BIZ_DIRECT_IDS:
                # BizAdvise — send response directly
                response = BUTTON_RESPONSES.get(service_id, "")
                if response:
                    _executor.submit(_send_text_reply, phone, response, socketio)
            elif service_id in SERVICE_MENU_IDS:
                # LawAdvise — show sub-menu
                _user_service_context[phone] = service_id
                sub_menu = TEXT_SUB_MENU.get(service_id, "")
                _executor.submit(_send_text_reply, phone, sub_menu, socketio)
                _executor.submit(_send_service_menu_safe, phone, service_id, socketio)
            return

        # Default — AI reply
        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)
        else:
            print(f"Human mode active for {phone} — AI skipped")

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")

        if interactive_type == "list_reply":
            selected_id = interactive["list_reply"]["id"]
            selected_title = interactive["list_reply"]["title"]
            save_message(phone, selected_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)
            if selected_id in BIZ_DIRECT_IDS:
                response = BUTTON_RESPONSES.get(selected_id, "")
                if response:
                    _executor.submit(_send_text_reply, phone, response, socketio)
            elif selected_id in SERVICE_MENU_IDS:
                _user_service_context[phone] = selected_id
                _executor.submit(_send_service_menu_safe, phone, selected_id, socketio)

        elif interactive_type == "button_reply":
            button_id = interactive["button_reply"]["id"]
            button_title = interactive["button_reply"]["title"]
            save_message(phone, button_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)
            response = BUTTON_RESPONSES.get(button_id)
            if response:
                _executor.submit(_send_text_reply, phone, response, socketio)
            else:
                mode = get_user_mode(phone)
                if mode == 0:
                    _executor.submit(_process_ai_reply, phone, button_title, socketio)

    elif msg_type in ("image", "audio", "document", "video"):
        media_info = msg.get(msg_type, {})
        caption = media_info.get("caption", "") or f"Sent a {msg_type}"
        save_message(phone, caption, "user", socketio,
                     message_type=msg_type, whatsapp_message_id=msg_id)

    elif msg_type == "button":
        text = msg["button"]["text"]
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)
        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)


def _send_welcome_menu(phone, socketio):
    """Try interactive list first, fall back to two-part text menu."""
    try:
        success, wa_id = send_main_menu(phone)
        if success:
            save_message(phone, TEXT_MAIN_MENU_1 + "\n" + TEXT_MAIN_MENU_2,
                         "bot", socketio, status="sent",
                         whatsapp_message_id=wa_id, source="ai")
        else:
            success1, wa_id1 = send_text(phone, TEXT_MAIN_MENU_1)
            save_message(phone, TEXT_MAIN_MENU_1, "bot", socketio,
                         status="sent" if success1 else "failed",
                         whatsapp_message_id=wa_id1, source="ai")
            time.sleep(0.5)
            success2, wa_id2 = send_text(phone, TEXT_MAIN_MENU_2)
            save_message(phone, TEXT_MAIN_MENU_2, "bot", socketio,
                         status="sent" if success2 else "failed",
                         whatsapp_message_id=wa_id2, source="ai")
    except Exception as e:
        print(f"Welcome menu error for {phone}: {e}")


def _send_service_menu_safe(phone, service_id, socketio):
    try:
        success, _ = send_service_menu(phone, service_id)
        if not success:
            sub_menu = TEXT_SUB_MENU.get(service_id, "")
            if sub_menu:
                send_text(phone, sub_menu)
    except Exception as e:
        print(f"Service menu error for {phone}: {e}")


def _send_text_reply(phone, text, socketio):
    try:
        success, wa_id = send_text(phone, text)
        save_message(phone, text, "bot", socketio,
                     status="sent" if success else "failed",
                     whatsapp_message_id=wa_id, source="ai")
    except Exception as e:
        print(f"Text reply error for {phone}: {e}")


def _process_ai_reply(phone, text, socketio):
    try:
        reply = ask_ai(text)
        success, wa_msg_id = send_text(phone, reply)
        status = "sent" if success else "failed"
        save_message(phone, reply, "bot", socketio,
                     status=status, whatsapp_message_id=wa_msg_id, source="ai")
    except Exception as e:
        print(f"AI reply error for {phone}: {e}")
