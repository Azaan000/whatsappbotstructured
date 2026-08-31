import os
import hmac
import hashlib
import time
import threading
import re
from collections import deque
import requests as http_requests
import mimetypes as mt
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, current_app

from models.user import save_user, get_user_mode, get_user_source
from models.message import save_message, update_message_status
import models.consultation as consultation_model
from models.database import get_db
from bot.ai_client import ask_ai
from bot.whatsapp_handler import (
    send_text, send_main_menu, send_service_menu, send_greeting_buttons,
    send_nav_buttons,
)
from utils.logger import get_logger

log = get_logger(__name__)

webhook_bp = Blueprint("webhook", __name__)

_executor = ThreadPoolExecutor(max_workers=10)

# ── Duplicate-webhook-delivery guard ─────────────────────────────────────
# WhatsApp retries webhook deliveries, so we track which message ids we've
# already handled. Two fixes vs. the old plain `set()`:
#   1. Bounded via a deque + set pair, evicting the OLDEST ids once we hit
#      the cap — instead of `.clear()`-ing the whole cache, which used to
#      forget everything at once and let old retried messages slip through
#      and get reprocessed (duplicate AI replies / duplicate sends).
#   2. Guarded by a lock so the check-and-reserve is atomic — two
#      near-simultaneous webhook deliveries for the same message id can no
#      longer both pass the "not seen yet" check before either records it
_processed_ids = set()
_processed_ids_order = deque()
_processed_lock = threading.Lock()
MAX_PROCESSED_IDS = 10000

_user_service_context = {}
_contact_collection = {}   # phone -> {"step": "awaiting_name"/"awaiting_mobile"/"awaiting_time", "name": ..., "mobile": ...}
_user_context = {}         # phone -> "main" once a consultation flow completes (kept for future use)

# Which SCREEN (category id or leaf id) this phone is actually looking
# at right now, updated every time we send a category list or a leaf
# answer. This is what makes the tap-only 🔙 Back button on any given
# screen resolve to the right place without the customer (or the code
# elsewhere) needing to track a full path:
#   - current screen is a leaf id (has an entry in LEAF_PARENT) ->
#     Back re-sends that leaf's parent category list.
#   - current screen is anything else (a category id, or nothing) ->
#     Back behaves exactly like Main Menu, since every category sits
#     directly one level below the main menu.
# See _handle_nav_back / _handle_nav_main below.
_user_current_screen = {}

# Which menu variant was actually last SHOWN to this phone number —
# None/"biz"/"law", same vocabulary as `source`. This is deliberately
# separate from `source` (the permanently-locked ad-attribution value):
# `source` decides the very first automatic welcome menu after someone
# clicks an ad, and an explicit typed "menu" (MENU_TRIGGERS) now sends
# an ad-sourced user back to THAT SAME brand's menu rather than the
# combined one — a LawAdvise-ad user asking for "menu" should land back
# on LawAdvise services, not get dumped into the full BizAdvise+LawAdvise
# list. Anyone who genuinely wants the full combined list (including an
# ad-sourced user who wants the other brand too) can ask explicitly via
# FULL_MENU_TRIGGERS ("full menu", "all services", etc.), which always
# shows both sections regardless of source.
# Numeric replies afterward need to be interpreted against whichever
# menu the person is actually looking at, not against their locked
# source — otherwise "3" would mean different things depending on
# which dict happens to be consulted. Not persisted to the DB: it only
# needs to survive for the current chat session, and defaults back to
# `source` (via _user_menu_view.get(phone, source)) whenever we haven't
# explicitly shown this phone a menu yet in this process's lifetime.
_user_menu_view = {}

CONTACT = "03003029039 / 03332454111"       # BizAdvise
LAW_CONTACT = "03003029039 / 03351340999"    # LawAdvise
MEDIA_FOLDER = "media_files"

# Appended to every free-chat AI reply (i.e. every reply that falls
# through to _process_ai_reply rather than a menu/button/list tap) so a
# customer typing questions in open chat always has a direct human
# contact on hand, not just whoever is quoted inside a specific menu
# leaf's text. Kept as a single constant so the numbers only need to be
# updated in one place.
FREE_CHAT_CONTACT_FOOTER = "\n\n📞03003029039  / 📞03332454111 for more details "

# ── Ad-based menu routing ────────────────────────────────────────────────
# When someone taps a "Click to WhatsApp" ad, WhatsApp attaches a
# `referral` object to their very first message — containing the ad's
# headline, body text and source URL (see _detect_ad_source below). We
# scan that text for keywords to decide whether they came from a
# LawAdvise ad or a BizAdvise ad, and show them ONLY that brand's menu
# instead of the combined one. Add more phrases here as new ad
# campaigns go live — no code changes needed elsewhere.
LAW_AD_KEYWORDS = {
    "law", "legal", "lawadvise", "law advise", "nikah", "marriage",
    "divorce", "khula", "custody", "guardianship", "inheritance",
    "nafaqa", "lawyer", "advocate", "family law", "property law",
}
BIZ_AD_KEYWORDS = {
    "biz", "business", "bizadvise", "biz advise", "tax", "taxation",
    "ngo", "charity", "accountancy", "accounting", "bookkeeping",
    "company registration", "trademark", "copyright", "patent",
    "secp", "fbr", "ntn", "startup", "digital marketing",
}


def _detect_ad_source(msg: dict):
    """Looks at this message's `referral` block (only present on the
    first message after someone taps a Click-to-WhatsApp ad) and
    keyword-matches its headline/body/source_url to decide which brand
    the ad was for. Returns 'biz', 'law', or None if there's no
    referral, or the text doesn't clearly point to one brand (e.g. it
    mentions both, or neither).

    Falls back to the customer's own typed text when there's no
    referral, so someone who messages first (no ad involved) and
    mentions e.g. "divorce" or "tax" up front gets routed to that
    brand's menu the same way a matching ad click would — same
    keyword lists, same ambiguous-match-means-None rule, just a
    different source of text to scan."""
    referral = msg.get("referral") or {}
    if referral:
        haystack = " ".join(
            str(referral.get(field, "")) for field in ("headline", "body", "source_url")
        ).lower()
    elif msg.get("type") == "text":
        haystack = str(msg.get("text", {}).get("body", "")).lower()
    else:
        return None

    if not haystack.strip():
        return None

    is_law = any(kw in haystack for kw in LAW_AD_KEYWORDS)
    is_biz = any(kw in haystack for kw in BIZ_AD_KEYWORDS)

    if is_law and not is_biz:
        return "law"
    if is_biz and not is_law:
        return "biz"
    return None  # ambiguous (matched both, or neither) — fall back to combined menu

# Marker phrase embedded in every choice-gated prompt below — used to
# detect "this message just asked the customer to choose between a
# callback and calling us directly" without relying on an exact-string
# match against the whole message (fragile — breaks the instant the
# wording changes even slightly). See _is_consult_choice_prompt().
_CALLBACK_CHOICE_MARKER = "call you back? Reply:"


def _consult_choice_message(intro: str, contact: str = None) -> str:
    """Shared template for 'Talk to Expert' / 'Talk to Lawyer' style
    replies — as opposed to explicit 'Book Consultation' replies, these
    give the phone number immediately and ASK whether the customer wants
    a callback, rather than assuming it and immediately demanding their
    name/mobile/time.

    `contact` lets LawAdvise flows pass LAW_CONTACT instead of silently
    falling back to the BizAdvise number — previously every "Talk to an
    Expert" reply (including the LawAdvise ones) always quoted CONTACT,
    so a LawAdvise customer asking for a lawyer was handed the BizAdvise
    line."""
    contact = contact or CONTACT
    return (
        f"{intro}\n\n"
        f"📞 Call or WhatsApp us directly: {contact}\n\n"
        f"Would you like our team to call you back? Reply:\n"
        f"1️⃣ Yes, call me back\n"
        f"2️⃣ No thanks, I'll reach out myself"
    )


# ── All your existing BUTTON_RESPONSES, BIZ_SUB_MENU, etc. ───────────────
# (keeping them exactly as you have them)

BUTTON_RESPONSES = {
    "biz_business": (
        "🏢 *Business Consultancy*\n\n"
        "We offer:\n"
        "• Private Limited / SMC / LLC Registration (UK / USA)\n"
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
        "• NTN Registration — Individual (Rs.500 / 30 mins)\n"
        "• NTN Registration — Business (Sole Proprietor / Partnership / Company)\n"
        "• Income Tax Returns (Salaried, Freelancer, Business, Company, Overseas Pakistani)\n"
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
        "• Accounting Software (QuickBooks, Xero, Excel, Customized Solution)\n\n"
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
        "• Company Secretarial Services\n"
        "• Legal Consultation (Startup, SME, Corporate Advisory, Business Risk Assessment)\n\n"
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
        "• Branding & Graphic Design\n"
        "• Marketing Consultation\n\n"
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
    "biz_consult": _consult_choice_message(
        "👨‍💼 *Talk to an Expert*\n\nOur consultants are available to help you."
    ),
    "nikah_procedure": f"📋 *Online Nikah Procedure:*\n\n• At least one party must be residing outside Pakistan.\n• The legal process is identical to a conventional Nikah.\n• One party participates remotely through a secure online platform.\n\nWould you like to book a consultation with our legal team?",
    "nikah_documents": f"📄 *Required Documents for Online Nikah:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "nikah_consult": _consult_choice_message(
        "💬 *Online Nikah — Talk to a Lawyer*", contact=LAW_CONTACT
    ),
    "court_procedure": "📋 *Court Marriage Procedure:*\n\n• Both parties must be present in person.\n• All legal requirements are the same as a conventional Nikah.\n\nWould you like to book a consultation?",
    "court_documents": "📄 *Required Documents for Court Marriage:*\n\nFrom both parties:\n• Valid CNIC / NICOP or Passport\n• Recent passport-size photographs\n• 2 Witnesses (CNIC of both witnesses)\n\nWould you like to book a consultation?",
    "court_consult": f"💬 Our legal team will be in touch shortly to assist you with Court Marriage.\n\n📞 Call or WhatsApp us directly: {LAW_CONTACT}",
    "divorce_procedure": "📋 *Divorce / Khula Procedure:*\n\nEvery case is unique. Please consult one of our legal experts for advice tailored to your specific situation.",
    "divorce_timeline": "⏳ *Divorce / Khula Timeline:*\n\nThe timeline varies depending on the nature and complexity of your case.",
    "divorce_consult": f"💬 Our legal expert will contact you shortly to discuss your Divorce / Khula case. Your matter will be handled with full confidentiality.\n\n📞 Call or WhatsApp us directly: {LAW_CONTACT}",
    "custody_procedure": "📋 *Child Custody / Guardianship:*\n\nThis matter requires a detailed legal assessment. Our legal team will be happy to assist you personally.",
    "custody_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "custody_consult": _consult_choice_message(
        "💬 *Child Custody / Guardianship — Talk to an Expert*", contact=LAW_CONTACT
    ),
    "maintenance_procedure": "📋 *Maintenance (Nafaqa) / Dowery:*\n\nThis matter cannot be accurately assessed through chat alone. Our legal team will assist you personally.",
    "maintenance_timeline": "⏳ *Timeline:*\n\nEach case is unique; the estimated timeline may vary.",
    "maintenance_consult": _consult_choice_message(
        "💬 *Maintenance / Dowery — Talk to an Expert*", contact=LAW_CONTACT
    ),
    "property_procedure": "📋 *Property Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "property_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "property_consult": f"💬 Our property law expert will contact you shortly.\n\n📞 Call or WhatsApp us directly: {LAW_CONTACT}",
    "inheritance_procedure": "📋 *Inheritance:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "inheritance_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "inheritance_consult": _consult_choice_message(
        "💬 *Inheritance — Talk to an Expert*", contact=LAW_CONTACT
    ),
    "corporate_procedure": "📋 *Corporate Law:*\n\nThis requires a detailed legal consultation. Please connect with one of our lawyers.",
    "corporate_timeline": "⏳ *Timeline:*\n\nThe duration depends on the legal process and circumstances of your case.",
    "corporate_consult": _consult_choice_message(
        "💬 *Corporate Law — Talk to an Expert*", contact=LAW_CONTACT
    ),
    "docs_procedure": "📋 *Legal Documentation:*\n\nThis requires a detailed legal consultation. Our legal team can assist with document drafting and verification.",
    "docs_timeline": "⏳ *Timeline:*\n\nThe duration depends on the type and complexity of documentation required.",
    "docs_consult": f"💬 Our legal team will contact you shortly to assist with your documentation needs.\n\n📞 Call or WhatsApp us directly: {LAW_CONTACT}",
    "contact_us": _consult_choice_message("📞 *Contact Us*"),
    # LawAdvise-context variant of the same "Talk to an Expert" reply —
    # "contact_us" is reached both from the ambiguous combined-menu row
    # (item 17, no way to know which brand the customer wants) and from
    # LawAdvise's own dedicated "Talk to an Expert" row (item 10 on the
    # Law-only menu, and the LawAdvise widget's "Talk to a Lawyer"
    # button). The plain "contact_us" entry above stays the ambiguous
    # default (BizAdvise's CONTACT number); this one is used instead
    # wherever the calling code already knows it's a LawAdvise context —
    # see _contact_us_response() below.
    "contact_us_law": _consult_choice_message("📞 *Contact Us*", contact=LAW_CONTACT),
}


def _contact_us_response(brand: str) -> str:
    """contact_us is the one BUTTON_RESPONSES entry without a single
    fixed answer — every other id maps to text for one specific brand,
    but this id is shared between the ambiguous combined-menu row and
    LawAdvise's own dedicated one. Callers that already know the brand
    (from _user_menu_view, an active text menu, or an explicit widget
    topic) should use this instead of indexing BUTTON_RESPONSES
    directly, so a LawAdvise customer reaches LAW_CONTACT rather than
    silently getting BizAdvise's number."""
    return BUTTON_RESPONSES["contact_us_law"] if brand == "law" else BUTTON_RESPONSES["contact_us"]

# ── "Back to menu" hint ───────────────────────────────────────────────────
# Appended to every leaf response so a customer reading any single
# service's answer VIA THE TEXT/NUMBER FALLBACK PATH (see
# _extract_menu_selection below) can jump straight back to the main
# menu by typing *menu*. Customers who tap their way here instead get
# real Back / Main Menu buttons via send_nav_buttons and never see this
# hint — see _strip_back_hint / _send_leaf_reply.
_BACK_TO_MENU_HINT = "\n\n🔙 Type *menu* anytime to return to the main menu."


def _add_back_to_menu_hint(d: dict) -> dict:
    """Appends the hint (in place) to every string value in a flat dict,
    or recurses into every inner dict of a dict-of-dicts. Skips any
    value that already carries the hint, so values borrowed from an
    already-hinted dict (e.g. BIZ_SUB_RESPONSES pulling straight from
    BUTTON_RESPONSES) never get it appended twice."""
    for key, value in d.items():
        if isinstance(value, dict):
            _add_back_to_menu_hint(value)
        elif isinstance(value, str) and _BACK_TO_MENU_HINT not in value:
            d[key] = value + _BACK_TO_MENU_HINT
    return d


_add_back_to_menu_hint(BUTTON_RESPONSES)


def _strip_back_hint(text: str) -> str:
    """Removes the typed-'menu' hint before sending a leaf answer via
    real nav buttons — the hint exists for the text-fallback path only;
    showing it alongside actual Back/Main Menu buttons would be
    redundant and confusing."""
    if text.endswith(_BACK_TO_MENU_HINT):
        return text[: -len(_BACK_TO_MENU_HINT)]
    return text


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

_add_back_to_menu_hint(TEXT_SUB_MENU)
_add_back_to_menu_hint(TEXT_SUB_RESPONSES)

BIZ_SUB_MENU = {
    "biz_business": (
        "🏢 *Business Consultancy* — which registration do you need?\n\n"
        "1️⃣ Private Limited / SMC / LLC (UK / USA)\n"
        "2️⃣ Partnership Firm / AOP\n"
        "3️⃣ Proprietorship\n"
        "4️⃣ Trademark Registration\n"
        "5️⃣ Copyright Registration\n"
        "6️⃣ Patent Registration\n"
        "7️⃣ Other Registrations (KCCI / PEC / DTS / PSEB)\n"
        "8️⃣ Talk to an Expert\n"
        "9️⃣ 🔙 Back to Main Menu"
    ),
    "biz_tax": (
        "💰 *Taxation Services* — which service do you need?\n\n"
        "1️⃣ NTN Registration — Individual\n"
        "2️⃣ NTN Registration — Business\n"
        "3️⃣ Income Tax Return\n"
        "4️⃣ Sales Tax Registration\n"
        "5️⃣ Sales Tax Monthly Return\n"
        "6️⃣ Provincial Sales Tax (SRB/PRA/BRA/KPRA)\n"
        "7️⃣ ATL (Active Taxpayer List)\n"
        "8️⃣ Tax Notices\n"
        "9️⃣ Tax Refund\n"
        "🔟 Talk to an Expert\n"
        "1️⃣1️⃣ 🔙 Back to Main Menu"
    ),
    "biz_accounts": (
        "📊 *Accountancy Services* — which service do you need?\n\n"
        "1️⃣ Bookkeeping\n"
        "2️⃣ Annual Accounts Management\n"
        "3️⃣ Audited Accounts\n"
        "4️⃣ Internal & External Audit\n"
        "5️⃣ Financial Reporting\n"
        "6️⃣ Accounting Consultation\n"
        "7️⃣ Talk to an Expert\n"
        "8️⃣ 🔙 Back to Main Menu"
    ),
    "biz_legal": (
        "⚖️ *Corporate Legal Advisory* — which service do you need?\n\n"
        "1️⃣ Contract Drafting\n"
        "2️⃣ Corporate Compliance\n"
        "3️⃣ Legal Notices\n"
        "4️⃣ Legal Opinions\n"
        "5️⃣ Regulatory Compliance\n"
        "6️⃣ Company Secretarial Services\n"
        "7️⃣ Legal Consultation\n"
        "8️⃣ Talk to an Expert\n"
        "9️⃣ 🔙 Back to Main Menu"
    ),
}

# Which numbered choice means "back to main menu" on each of the 4
# BizAdvise sub-menus above — used by the TEXT/NUMBER fallback path
# only. The interactive list version of these same screens (see
# send_service_menu in whatsapp_handler.py) carries its own tappable
# "🔙 Back to Main Menu" row with a stable "nav_main" id instead, so
# this numbering only matters for someone still typing digits by hand.
_BACK_TO_MAIN_MENU_OPTION = {
    "biz_business": "9",
    "biz_tax": "11",
    "biz_accounts": "8",
    "biz_legal": "9",
}

_add_back_to_menu_hint(BIZ_SUB_MENU)

BIZ_SUB_RESPONSES = {
    "biz_business": {
        "1": (
            "🏢 *Private Limited / SMC / LLC Registration (UK / USA)*\n\n"
            "Company Types: Private Limited Company, Single Member Company (SMC), LLC Registration (UK / USA)\n\n"
            "Required Documents:\n• Director CNIC\n• Shareholder Details\n• Company Name\n• Office Address\n"
            "• Business Activity\n• Contact Number\n• Email Address\n\n"
            f"Cost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "2": (
            "🏢 *Partnership Firm / AOP Registration*\n\n"
            "Required Documents:\n• Director CNIC\n• Shareholder Details\n• Company Name\n• Office Address\n"
            f"• Business Activity\n• Contact Number\n• Email Address\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "3": (
            "🏢 *Proprietorship Registration*\n\n"
            f"Required Documents:\n• CNIC\n• Mobile Number\n• Business Address\n• Nature of Business\n• Email Address\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "4": (
            "™️ *Trademark Registration*\n\nRegister your Brand Name or Logo.\n\n"
            f"Required Documents:\n• Applicant CNIC\n• Brand Name\n• Logo (Optional)\n• Business Details\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "5": (
            "©️ *Copyright Registration*\n\nWhat can be registered: Literary Work, Software, Music\n\n"
            f"Required Documents:\n• Business Registration Documents\n• Utility Bill\n• Owner's CNIC\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "6": (
            "📜 *Patent Registration*\n\n"
            f"Required Documents:\n• Business Registration Documents\n• Utility Bill\n• Owner's CNIC\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}"
        ),
        "7": (
            "🏛️ *Other Registrations — KCCI / PEC / DTS / PSEB*\n\n"
            "*KCCI:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, Latest Tax Return\n\n"
            "*PEC:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, PEC Registered Engineer\n\n"
            "*DTS:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo, 800CC+ vehicle, Bank Guarantee\n\n"
            f"*PSEB:* Business Registration Docs, Account Maintenance Certificate, Utility Bill, CNIC/Photo\n\nContact us: {CONTACT}"
        ),
        "8": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_tax": {
        "1": f"💰 *NTN Registration — Individual*\n\nRequired Documents:\n• Copy of CNIC\n• Email Address\n• Contact Number\n\nCost: Rs. 500\nTimeline: 30 minutes\n\nContact us: {CONTACT}",
        "2": f"💰 *NTN Registration — Business*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC\n• Contact Information\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "3": f"🧾 *Income Tax Return*\n\n• Salaried Individual: Salary Slip, Details of Assets\n• Freelancer: Bank Statement, Source of Income, Details of Assets\n• Business Owner: Bank Statement, Source of Income, Details of Assets\n• Business Tax Return: Bank Statement, Business Internal Accounts, Details of Expenses, Tax Deduction Certificates, Details of Assets\n\nContact us: {CONTACT}",
        "4": f"🧾 *Sales Tax Registration*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC\n• Rent Agreement/Ownership Document\n• Contact Details\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "5": f"🧾 *Sales Tax Monthly Return*\n\nRequirement: Details of invoices generated in the last month\n\nContact us: {CONTACT}",
        "6": f"🧾 *Provincial Sales Tax (SRB, PRA, BRA, KPRA)*\n\nRequired Documents:\n• Business Registration Documents\n• Account Maintenance Certificate\n• Utility Bill\n• Owner's CNIC/Photo\n\nCost: May vary case to case\n\nContact us: {CONTACT}",
        "7": f"📋 *ATL (Active Taxpayer List)*\n\n• Check ATL Status: Consult our specialist\n• Become Active Taxpayer: Consult our specialist\n• ATL Restoration: Consult our specialist\n\nContact us: {CONTACT}",
        "8": f"📩 *Tax Notices*\n\nFBR Notice, Audit Notice, ATL Notice, Section 114, Section 122, Section 111, Reply to Notice — all require consultation with our tax experts.\n\nContact us: {CONTACT}",
        "9": f"💵 *Tax Refund*\n\nRequires consultation with our tax experts.\n\nContact us: {CONTACT}",
        "10": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_accounts": {
        "1": f"📊 *Bookkeeping*\n\nServices: Sales Recording, Purchase Recording, Cash Book, Bank Reconciliation, Accounts Receivable, Accounts Payable, General Ledger, Expense Management, Inventory Recording, Financial Reports\n\nContact us: {CONTACT}",
        "2": f"📊 *Annual Accounts Management*\n\nIncludes: Profit & Loss Account, Balance Sheet, Cash Flow Statement, Trial Balance, General Ledger Review, Financial Statements\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "3": f"📊 *Audited Accounts*\n\nWho needs an audit: Private Limited Company, NGO, Trust, Large Business, Statutory Requirement, Voluntary Audit\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "4": f"📊 *Internal & External Audit*\n\nInternal Audit: Risk Assessment, Internal Controls, Compliance Review, Operational Review, Audit Report\n\nExternal Audit: Independent Audit, Financial Verification, Statutory Compliance, Audit Opinion, Final Report\n\nContact us: {CONTACT}",
        "5": f"📊 *Financial Reporting*\n\nTypes: Monthly Reports, Quarterly Reports, Annual Reports, Management Reports, Custom Reports\n\nContact us: {CONTACT}",
        "6": f"📊 *Accounting Consultation*\n\nServices: Business Accounting, Startup Accounting, Accounting System Setup, Accounting Software (QuickBooks, Xero, Excel, Customized Solution), Financial Health Check\n\nContact us: {CONTACT}",
        "7": BUTTON_RESPONSES["biz_consult"],
    },
    "biz_legal": {
        "1": f"⚖️ *Contract Drafting*\n\nTypes: Business Contracts, Partnership Contracts, Employment Contracts, Service Agreements, NDA, MoU\n\nCost: May vary case to case\nTimeline: May vary case to case\n\nContact us: {CONTACT}",
        "2": f"⚖️ *Corporate Compliance*\n\nServices: SECP Compliance, Company Annual Returns, Board Resolutions, Share Transfer, Director Changes, Company Record Updates, Compliance Calendar\n\nContact us: {CONTACT}",
        "3": f"⚖️ *Legal Notices*\n\nTypes: Recovery Notice, Breach of Contract Notice, Legal Demand Notice, Employee Notice, Tenant Notice, Commercial Notice\n\nContact us: {CONTACT}",
        "4": f"⚖️ *Legal Opinions*\n\nTypes: Business Legal Opinion, Contract Review, Compliance Opinion, Investment Opinion, Property Related Opinion\n\nContact us: {CONTACT}",
        "5": f"⚖️ *Regulatory Compliance*\n\nAreas: SECP, FBR, IPO Pakistan, Labour Laws, Corporate Governance, Compliance Advisory\n\nContact us: {CONTACT}",
        "6": f"⚖️ *Company Secretarial Services*\n\nServices: Statutory Registers, Board Meeting Minutes, Share Certificates, Annual Returns, Corporate Resolutions, Company Record Maintenance\n\nContact us: {CONTACT}",
        "7": f"⚖️ *Legal Consultation*\n\nTypes: Startup Legal Advice, SME Legal Advice, Corporate Advisory, Compliance Consultation, Contract Review, Business Risk Assessment\n\nContact us: {CONTACT}",
        "8": BUTTON_RESPONSES["biz_consult"],
    },
}

_add_back_to_menu_hint(BIZ_SUB_RESPONSES)

ALL_SUB_MENUS = {**TEXT_SUB_MENU, **BIZ_SUB_MENU}
ALL_SUB_RESPONSES = {**TEXT_SUB_RESPONSES, **BIZ_SUB_RESPONSES}
SERVICE_MENU_IDS = set(ALL_SUB_MENUS.keys())
BIZ_DIRECT_IDS = {"biz_ngo", "biz_digital", "biz_urgent", "biz_consult", "contact_us"}

# ── Leaf-screen id space (tap-only navigation) ───────────────────────────
# Every leaf answer reachable by TAPPING a row inside a category list
# needs a stable id so a list_reply can be routed straight to its text
# AND so 🔙 Back (see _handle_nav_back) knows which category to return
# to. The Law leaf ids already exist as keys in BUTTON_RESPONSES
# ("nikah_procedure", "divorce_timeline", ...) — this just adds the
# equivalent ids for the Biz leaves, which previously only existed as
# BIZ_SUB_RESPONSES[category][number] (meaningful only to the numbered
# TEXT fallback, not tappable on their own).
BIZ_LEAF_RESPONSES = {}
for _biz_cat, _biz_items in BIZ_SUB_RESPONSES.items():
    for _num, _leaf_text in _biz_items.items():
        BIZ_LEAF_RESPONSES[f"{_biz_cat}_{_num}"] = _leaf_text

# leaf id -> the category id it belongs to, i.e. what 🔙 Back re-sends.
# Ids with NO entry here (e.g. biz_ngo, biz_digital, contact_us — the
# top-level items hanging directly off the main menu, not nested inside
# a category) fall through in _handle_nav_back to "Back == Main Menu",
# which is exactly correct for them too.
LEAF_PARENT = {
    # Law leaves
    "nikah_procedure": "online_nikah", "nikah_documents": "online_nikah", "nikah_consult": "online_nikah",
    "court_procedure": "court_marriage", "court_documents": "court_marriage", "court_consult": "court_marriage",
    "divorce_procedure": "divorce_khula", "divorce_timeline": "divorce_khula", "divorce_consult": "divorce_khula",
    "custody_procedure": "child_custody", "custody_timeline": "child_custody", "custody_consult": "child_custody",
    "maintenance_procedure": "maintenance", "maintenance_timeline": "maintenance", "maintenance_consult": "maintenance",
    "property_procedure": "property_law", "property_timeline": "property_law", "property_consult": "property_law",
    "inheritance_procedure": "inheritance", "inheritance_timeline": "inheritance", "inheritance_consult": "inheritance",
    "corporate_procedure": "corporate_law", "corporate_timeline": "corporate_law", "corporate_consult": "corporate_law",
    "docs_procedure": "legal_docs", "docs_timeline": "legal_docs", "docs_consult": "legal_docs",
    # Biz leaves
    **{f"biz_business_{i}": "biz_business" for i in range(1, 9)},
    **{f"biz_tax_{i}": "biz_tax" for i in range(1, 10)},
    **{f"biz_accounts_{i}": "biz_accounts" for i in range(1, 8)},
    **{f"biz_legal_{i}": "biz_legal" for i in range(1, 9)},
}

# All tap-reachable leaf ids -> their response text, Law + Biz combined.
LEAF_RESPONSES = {**BUTTON_RESPONSES, **BIZ_LEAF_RESPONSES}

# Short titles for the Biz leaves — mirrors the row titles used in
# whatsapp_handler.py's _BIZ_CATEGORY_ITEMS, kept here too so
# SERVICE_LABELS (used on consultation records and leaf-screen headers)
# has a sensible label instead of the raw "biz_tax_1" id.
_BIZ_LEAF_TITLES = {
    "biz_business_1": "Private Ltd/SMC/LLC", "biz_business_2": "Partnership / AOP",
    "biz_business_3": "Proprietorship", "biz_business_4": "Trademark Registration",
    "biz_business_5": "Copyright Registration", "biz_business_6": "Patent Registration",
    "biz_business_7": "Other Registrations", "biz_business_8": "Talk to an Expert",
    "biz_tax_1": "NTN - Individual", "biz_tax_2": "NTN - Business",
    "biz_tax_3": "Income Tax Return", "biz_tax_4": "Sales Tax Registration",
    "biz_tax_5": "Sales Tax Monthly Return", "biz_tax_6": "Provincial Sales Tax",
    "biz_tax_7": "ATL Status", "biz_tax_8": "Tax Notices", "biz_tax_9": "Tax Refund",
    "biz_accounts_1": "Bookkeeping", "biz_accounts_2": "Annual Accounts Mgmt",
    "biz_accounts_3": "Audited Accounts", "biz_accounts_4": "Internal & External Audit",
    "biz_accounts_5": "Financial Reporting", "biz_accounts_6": "Accounting Consultation",
    "biz_accounts_7": "Talk to an Expert",
    "biz_legal_1": "Contract Drafting", "biz_legal_2": "Corporate Compliance",
    "biz_legal_3": "Legal Notices", "biz_legal_4": "Legal Opinions",
    "biz_legal_5": "Regulatory Compliance", "biz_legal_6": "Company Secretarial Services",
    "biz_legal_7": "Legal Consultation", "biz_legal_8": "Talk to an Expert",
}

# ── Messages that mean "we've asked the user to share their contact info" ──
# _send_text_reply / _send_leaf_reply check against this set after every
# send; a match kicks off the Name -> Mobile -> Best Time collection flow
# below, regardless of which path (typed number, tapped list row, or
# tapped button) led there.
# "Book Consultation" labeled paths — the customer already explicitly
# chose to book, so go straight into the Name -> Mobile -> Best Time
# collection flow, same as before.
CONSULT_TRIGGER_TEXTS = {
    BUTTON_RESPONSES["court_consult"],
    BUTTON_RESPONSES["divorce_consult"],
    BUTTON_RESPONSES["property_consult"],
    BUTTON_RESPONSES["docs_consult"],
}

# "Talk to Expert" / "Talk to Lawyer" labeled paths — more ambiguous
# intent (could just want the phone number), so give the number
# immediately and ask whether they'd like a callback before collecting
# any contact info. Detected via _is_consult_choice_prompt()'s marker
# phrase (see _consult_choice_message above), not exact text matching.


def _is_consult_choice_prompt(text: str) -> bool:
    return _CALLBACK_CHOICE_MARKER in text


def _interpret_yes_no(text: str):
    """Tolerant yes/no interpretation for the callback-choice step —
    accepts a numbered reply (1/2, reusing the same tolerant menu-number
    matcher used elsewhere) as well as natural language. Returns 'yes',
    'no', or None if it can't tell."""
    selection = _extract_menu_selection(text)
    if selection == "1":
        return "yes"
    if selection == "2":
        return "no"

    lower = text.strip().lower()
    yes_words = {"yes", "yeah", "yup", "sure", "ok", "okay", "haan", "ji", "yh", "y"}
    no_words = {"no", "nah", "nope", "nahi", "n"}
    if lower in yes_words or "call me" in lower or "call back" in lower or "callback" in lower:
        return "yes"
    if lower in no_words or "myself" in lower or "i'll call" in lower or "i will call" in lower:
        return "no"
    return None


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_PART_OF_DAY = {"morning": 10, "afternoon": 14, "evening": 18, "night": 20}
_TIME_RE = re.compile(r'(\d{1,2})(:(\d{2}))?\s*(am|pm)?', re.IGNORECASE)


def _parse_best_time(text: str, now: datetime = None):
    """Best-effort parse of the free-text 'Best Time to Call' reply into
    a structured datetime — 'tomorrow 5pm', 'Monday morning', '3:30 pm'
    and similar phrasings. This is a foundation for a real callback
    calendar later, not a guarantee: on anything it can't confidently
    read it returns None and the original free text is kept regardless,
    so nothing is ever lost either way."""
    if not text:
        return None
    now = now or datetime.now()
    lower = text.strip().lower()

    day_offset = None
    if "today" in lower:
        day_offset = 0
    elif "tomorrow" in lower:
        day_offset = 1
    else:
        for i, wd in enumerate(_WEEKDAYS):
            if wd in lower or wd[:3] in lower:
                day_offset = (i - now.weekday()) % 7 or 7
                break

    hour, minute = None, None
    m = _TIME_RE.search(lower)
    if m and (m.group(4) or ":" in m.group(0)):
        hour = int(m.group(1))
        minute = int(m.group(3) or 0)
        ampm = m.group(4)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    else:
        for part, part_hour in _PART_OF_DAY.items():
            if part in lower:
                hour, minute = part_hour, 0
                break

    if hour is None:
        if day_offset is None:
            return None
        hour, minute = 12, 0  # a bare day with no time given — default to noon

    target_date = (now + timedelta(days=day_offset)).date() if day_offset is not None else now.date()
    try:
        target = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
    except ValueError:
        return None

    if day_offset is None and target < now:
        target += timedelta(days=1)

    return target.strftime("%Y-%m-%dT%H:%M:%SZ")

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
1️⃣6️⃣ Corporate Law
1️⃣7️⃣ 👨‍💼 Talk to an Expert

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
    "16": ("Corporate Law", "corporate_law"),
    "17": ("Talk to an Expert", "contact_us"),
}

TEXT_MAIN_MENU_BIZ = """Welcome to *BizAdvise Consulting* 🏢

How can we assist you? Please reply with a number:

1️⃣ Start a New Business / Business Consultancy
2️⃣ Start a Charity / NGO Registration
3️⃣ File My Taxes — Taxation Services
4️⃣ Manage My Accounts — Accountancy
5️⃣ Corporate Legal Advisory
6️⃣ Grow My Business Online — Digital Marketing
7️⃣ 🚨 Urgent Help
8️⃣ 👨‍💼 Talk to an Expert"""

TEXT_MAIN_MENU_LAW = """Welcome to *LawAdvise Consulting* ⚖️

How can we assist you? Please reply with a number:

1️⃣ Online Marriage / Online Nikah
2️⃣ Court Marriage
3️⃣ Divorce / Khula
4️⃣ Child Custody / Guardianship
5️⃣ Maintenance (Nafaqa) / Dowery
6️⃣ Property Law
7️⃣ Inheritance
8️⃣ Legal Documentation
9️⃣ Corporate Law
🔟 👨‍💼 Talk to an Expert"""

# Brand-scoped number -> (title, service_id) maps, renumbered from 1 so
# each brand's text menu reads cleanly on its own (rather than a
# LawAdvise-only visitor seeing options that start at "8️⃣").
TEXT_SERVICE_MENUS_BIZ = {
    "1": ("Start a New Business / Business Consultancy", "biz_business"),
    "2": ("NGO / Charity Registration", "biz_ngo"),
    "3": ("Taxation Services", "biz_tax"),
    "4": ("Accountancy Services", "biz_accounts"),
    "5": ("Corporate Legal Advisory", "biz_legal"),
    "6": ("Digital Marketing", "biz_digital"),
    "7": ("Urgent Help", "biz_urgent"),
    "8": ("Talk to an Expert", "biz_consult"),
}

TEXT_SERVICE_MENUS_LAW = {
    "1": ("Online Marriage / Online Nikah", "online_nikah"),
    "2": ("Court Marriage", "court_marriage"),
    "3": ("Divorce / Khula", "divorce_khula"),
    "4": ("Child Custody / Guardianship", "child_custody"),
    "5": ("Maintenance / Dowery", "maintenance"),
    "6": ("Property Law", "property_law"),
    "7": ("Inheritance", "inheritance"),
    "8": ("Legal Documentation", "legal_docs"),
    "9": ("Corporate Law", "corporate_law"),
    "10": ("Talk to an Expert", "contact_us"),
}

# ── Service labels for consultation records ──────────────────────────────
# Built from the same TEXT_SERVICE_MENUS map staff already see on the
# combined menu, so the label shown on a booked consultation always
# matches the label the customer themselves picked from — no separate
# list to keep in sync by hand.
_BIZ_SERVICE_IDS = {
    "biz_business", "biz_ngo", "biz_tax", "biz_accounts", "biz_legal",
    "biz_digital", "biz_urgent", "biz_consult",
}
SERVICE_LABELS = {service_id: title for title, service_id in TEXT_SERVICE_MENUS.values()}

# Leaf "...consult" ids only ever appear as a tapped button_id (never as
# a _user_service_context value), so they're not in TEXT_SERVICE_MENUS —
# alias each one back to its parent service for a consistent label.
_LEAF_SERVICE_ALIAS = {
    "nikah_consult": "online_nikah",
    "court_consult": "court_marriage",
    "divorce_consult": "divorce_khula",
    "custody_consult": "child_custody",
    "maintenance_consult": "maintenance",
    "property_consult": "property_law",
    "inheritance_consult": "inheritance",
    "corporate_consult": "corporate_law",
    "docs_consult": "legal_docs",
}
for _leaf_id, _parent_id in _LEAF_SERVICE_ALIAS.items():
    SERVICE_LABELS[_leaf_id] = SERVICE_LABELS.get(_parent_id, _leaf_id)

# Same idea for the Biz leaves, using their own short titles rather than
# aliasing to the parent category (a Biz leaf's title is informative on
# its own, e.g. "NTN - Individual", unlike the generic Law "Procedure").
for _biz_leaf_id, _biz_leaf_title in _BIZ_LEAF_TITLES.items():
    SERVICE_LABELS.setdefault(_biz_leaf_id, _biz_leaf_title)


def _service_brand(service_id: str) -> str:
    if not service_id:
        return ""
    canonical = _LEAF_SERVICE_ALIAS.get(service_id, service_id)
    canonical = LEAF_PARENT.get(canonical, canonical)
    if canonical in _BIZ_SERVICE_IDS:
        return "biz"
    if canonical == "contact_us":
        return ""
    return "law"


def _service_menu_map(source: str) -> dict:
    """Which number -> service map applies to this user, based on which
    ad (if any) brought them in. Unknown/organic users keep seeing the
    original combined 1-17 menu, unchanged."""
    if source == "biz":
        return TEXT_SERVICE_MENUS_BIZ
    if source == "law":
        return TEXT_SERVICE_MENUS_LAW
    return TEXT_SERVICE_MENUS


def _resolve_menu_source(phone: str, source: str):
    """Which brand a 'menu' request (typed 'menu', or the numbered
    'Back to Main Menu' option inside a submenu) should show.

    Prefers _user_menu_view — whichever menu this phone was ACTUALLY
    just looking at — over the permanently-locked ad `source`. Without
    this, a LawAdvise-ad customer who navigates into BizAdvise's
    Taxation submenu (via 'full menu' / 'See All Services') and then
    types 'menu' gets yanked back to the LawAdvise menu instead of
    staying in the BizAdvise context they were actually just in —
    jarring, and it also desyncs their next numbered reply (e.g. a
    submenu's own "11 Back to Main Menu" option) since that number no
    longer means anything on the menu they land on. This mirrors the
    exact same reasoning already used for interpreting numeric
    selections (see `active_view` a few lines below in _handle_message).

    Falls back to the locked `source` only when nothing's been shown
    yet this session — e.g. the very first "menu" this process has
    handled for this phone, or right after a server restart clears
    _user_menu_view — so an ad-sourced customer's first-ever "menu"
    request still lands on their own brand, same as before.
    """
    menu_source = _user_menu_view.get(phone, source)
    return menu_source if menu_source in ("biz", "law") else None


MENU_TRIGGERS = {
    "menu", "options", "option", "start", "help", "main menu", "mainmenu",
    "info", "information", "details", "services", "service", "list",
    "list of services", "what can you do", "what do you do", "show menu",
    "show options", "restart", "reset", "help me",
    "menu dikhao", "options dikhao", "madad", "madat", "khidmaat",
    "khidmat", "khidmaat dikhao", "tafseel", "tafaseel", "shuru",
    "shuru karo",
    "مینو", "آپشنز", "آپشن", "مدد", "خدمات", "تفصیل", "تفصیلات",
    "شروع", "شروع کریں", "فہرست",
}

# ── Greeting detection ────────────────────────────────────────────────────
# Pattern-based instead of an exact-match word list — Salam alone has
# dozens of phonetic Roman-Urdu spellings ("asslam mu alaikum",
# "assalam o alaikum", "asalamualaikum", ...) and an exact-match set will
# always miss some, silently falling through to the AI instead of the
# GREETING_REPLY template. This matches the "core" letter pattern of
# salam (tolerant of doubled/dropped s's and a's — the actual source of
# most real typos, incl. the "asslam" one from testing) plus an optional
# alaikum suffix, joined or spaced, so new misspellings are caught
# without further code changes.
#
# Trade-off: "Aslam" is also a common Pakistani given name, so a message
# that's just someone's name (or mentions one) can register as a
# greeting. Low-severity if it happens — worst case is the short
# GREETING_REPLY goes out instead of an AI reply — so this is accepted
# rather than trying to special-case names, which isn't reliably
# possible from text alone.
_SALAM_RE = re.compile(
    r'\b'
    r'a{0,2}s{1,2}a{0,2}l{1,2}a{1,2}m'   # salam / salaam / assalam / asalam / asslam / aslam
    r'(?:u|un|o)?'                        # assalamu / assalamun / assalamo
    r'(?:'
        r'\s*[-]?\s*(?:mu|wa)?\s*'         # optional filler: mu / wa / spacing/hyphen
        r'al[ae]i?[ky]um'                  # alaikum / alaykum / aleikum / aleykum
    r')?'
    r'\b',
    re.IGNORECASE,
)
# Catches the reply form typed alone, e.g. just "walaikum" or "alaikum"
# with no salam root before it.
_ALAIKUM_ONLY_RE = re.compile(r'\bw?al[ae]i?[ky]um\b', re.IGNORECASE)
_SALAM_UR = ("السلام", "سلام", "وعلیکم")
_ENGLISH_GREETINGS_RE = re.compile(
    r'^(hi+|hello+|hey+|helo+|yo|sup|wassup|what\'?s up|'
    r'good\s?(morning|afternoon|evening))\b',
    re.IGNORECASE,
)

# ── Website-widget lead detection ────────────────────────────────────────
# Both the live BizAdvise widget and the future LawAdvise widget build
# their "Continue on WhatsApp" prefilled text the same way (see
# index.html's addMessage): it always starts with "Hi, I'm interested
# in: <topic>". That means every widget lead technically starts with
# "Hi" — which, unqualified, is exactly what _ENGLISH_GREETINGS_RE
# matches. Without this check, _is_greeting() intercepts the ENTIRE
# lead message (topic, page URL, utm params, ref id and all) before
# _detect_ad_source ever gets a chance to read the topic, and every
# widget lead — from either brand, forever — collapses into the
# generic combined greeting instead of being routed to the right
# brand/service. This check is brand-agnostic on purpose so it keeps
# working unchanged once a LawAdvise widget goes live with its own
# topics.
_WIDGET_LEAD_RE = re.compile(r"^\s*hi,?\s*i'?m interested in\s*:", re.IGNORECASE)


def _looks_like_widget_lead(text: str) -> bool:
    return bool(_WIDGET_LEAD_RE.match(text or ""))


# Captures whatever sits between "interested in:" and the newline that
# precedes the "(via <url>)" suffix — i.e. just the topic itself, e.g.
# "File My Taxes". `.` doesn't match "\n" by default, so this naturally
# stops before the page-url line without needing a more specific
# end-of-topic marker.
_WIDGET_LEAD_TOPIC_RE = re.compile(r"^\s*hi,?\s*i'?m interested in\s*:\s*(.+?)\s*(?:\n|$)", re.IGNORECASE)


def _extract_widget_lead_topic(text: str):
    """Pulls the topic out of a widget lead's prefilled text, lowercased
    for matching against WIDGET_TOPIC_SERVICE_MAP. Returns None if the
    text isn't a widget lead at all (shouldn't normally be called unless
    _looks_like_widget_lead already returned True, but stays defensive)."""
    match = _WIDGET_LEAD_TOPIC_RE.match(text or "")
    if not match:
        return None
    return match.group(1).strip().lower()


# Maps each of the website widgets' known quick-reply topics (see
# CANNED_REPLIES in each widget backend's main.py — BizAdvise's and
# LawAdvise's are separate deployments/files, but both build their
# wa.me prefill the same way, so both sets of topic strings land here.
# These strings must stay in sync with the topic string in each
# CANNED_REPLIES entry, lowercased for matching) straight to the
# service submenu it should open, plus which brand that submenu
# belongs to. The brand is stored explicitly per topic rather than
# derived from the service_id, because "contact_us" (LawAdvise's "Talk
# to a Lawyer") is brand-ambiguous on its own — it's also the id used
# by the combined 1-17 menu's own "Talk to an Expert" row — so
# _service_brand() can't tell law from biz for it.
#
# This is what lets a "File My Taxes" or "Divorce / Khula" tap land the
# visitor directly on that specific submenu, instead of just the
# brand-level welcome menu that ad_source-only detection would give.
#
# Freeform widget chat topics are deliberately NOT covered here — each
# widget backend collapses those to a generic "bizservices"/"lawservices"
# tag before building the wa.me link (an arbitrary AI-picked topic
# string isn't reliable enough to route on), so they fall through
# unmatched to the existing ad_source-based brand-menu handling below,
# same as before.
WIDGET_TOPIC_SERVICE_MAP = {
    # BizAdvise widget topics -> (service_id, brand)
    "start a new business": ("biz_business", "biz"),
    "file my taxes": ("biz_tax", "biz"),
    "manage my accounts": ("biz_accounts", "biz"),
    "legal assistance": ("biz_legal", "biz"),
    "grow my business online": ("biz_digital", "biz"),
    "talk to an expert": ("biz_consult", "biz"),
    # LawAdvise widget topics -> (service_id, brand)
    "online marriage / nikah": ("online_nikah", "law"),
    "court marriage": ("court_marriage", "law"),
    "divorce / khula": ("divorce_khula", "law"),
    "child custody": ("child_custody", "law"),
    "property law": ("property_law", "law"),
    "talk to a lawyer": ("contact_us", "law"),
}


def _is_greeting(text: str) -> bool:
    """Pattern-based greeting detection — catches phonetic/typo variants
    of Salam and common English greetings without needing an exhaustive
    exact-match word list. Restricted to short messages so it doesn't
    fire on an unrelated sentence that happens to contain a greeting-like
    word."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _looks_like_widget_lead(stripped):
        # A "Hi, I'm interested in: ..." widget lead is not a greeting —
        # let it fall through to ad_source/keyword routing instead.
        return False
    if any(marker in stripped for marker in _SALAM_UR):
        return True
    if len(stripped) <= 40 and (_SALAM_RE.search(stripped) or _ALAIKUM_ONLY_RE.search(stripped)):
        return True
    if _ENGLISH_GREETINGS_RE.match(stripped):
        return True
    return False


# Typed specifically to jump straight to one brand's menu, same idea as
# MENU_TRIGGERS but scoped instead of combined.
BIZ_MENU_TRIGGERS = {"bizservices", "biz services", "bizservice", "bizadvise", "business services", "business service","biz", "business consulting"}
LAW_MENU_TRIGGERS = {"lawservices", "law services", "lawservice", "lawadvise", "legal services", "legal service", "law", "legal consulting"}

# Explicit ask for BOTH sections at once — always shows the full
# combined menu, even for an ad-sourced user whose plain "menu"
# (MENU_TRIGGERS) now takes them back to just their own brand. This is
# the escape hatch for e.g. a LawAdvise-ad customer who also wants to
# see BizAdvise services.
FULL_MENU_TRIGGERS = {
    "full menu", "all services", "all option", "all options", "everything",
    "show all", "show everything", "both services", "full list",
    "combined menu", "sab khidmaat", "sab services", "sab kuch dikhao",
}

# Sent to ANY plain greeting that isn't ad-sourced and isn't a direct
# bizservices/lawservices request — whether it's a brand-new contact's
# very first message or a returning contact saying hi again later.
# Lets the person decide for themselves instead of being pushed straight
# into a specific brand's menu.
GREETING_REPLY = (
    "👋 *Assalam-o-Alaikum! Welcome to BizAdvise & LawAdvise Consulting.*\n\n"
    "How can we help you today?\n\n"
    "Type *bizservices* for Business services, *lawservices* for Legal "
    "services, or *menu* to see everything."
)

# Used only as the BODY of the interactive greeting-buttons message —
# "or select below" only makes sense when the 3 buttons are actually
# attached underneath it. If the interactive send fails and we fall
# back to plain text (see _send_greeting_reply), GREETING_REPLY itself
# goes out instead, with no dangling "select below" pointing at nothing.
GREETING_REPLY_WITH_BUTTONS = GREETING_REPLY[:-1] + " — or select below 👇"


def _get_socketio():
    return current_app.extensions["socketio"]


def _check_and_mark_processed(msg_id):
    """Atomically check whether msg_id was already handled, and if not,
    reserve it immediately — before returning — so a second, near-
    simultaneous webhook delivery for the same id (WhatsApp retries do
    happen) can't slip past this check before the first one records it.

    Returns True if this message was already processed (skip it),
    False if this call just claimed it (go ahead and process it).
    """
    if not msg_id:
        return False

    with _processed_lock:
        if msg_id in _processed_ids:
            return True
        # Reserve it now, inside the lock, so any concurrent duplicate
        # request sees it in _processed_ids immediately.
        _processed_ids.add(msg_id)
        _processed_ids_order.append(msg_id)
        # Evict the OLDEST entries once we're over the cap, instead of
        # wiping the whole cache — keeps recent history intact so
        # WhatsApp's delayed retries still get caught.
        while len(_processed_ids_order) > MAX_PROCESSED_IDS:
            oldest = _processed_ids_order.popleft()
            _processed_ids.discard(oldest)

    # Not seen in-memory — could still be a duplicate from before a
    # server restart (which clears the in-memory cache), so fall back
    # to checking the DB once.
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM messages WHERE whatsapp_message_id=?", (msg_id,))
        return cursor.fetchone() is not None
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


def _download_whatsapp_media(media_id, media_type):
    """Download media from WhatsApp and save locally. Returns (filepath, filename) or (None, None)."""
    try:
        WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

        # Step 1: get media URL
        url_res = http_requests.get(
            f"https://graph.facebook.com/v18.0/{media_id}",
            headers=headers, timeout=10
        )
        if url_res.status_code != 200:
            log.error(f"Failed to get media URL: {url_res.text}")
            return None, None

        media_url = url_res.json().get("url")
        if not media_url:
            return None, None

        # Step 2: download the file
        dl_res = http_requests.get(media_url, headers=headers, timeout=30)
        if dl_res.status_code != 200:
            log.error(f"Failed to download media: {dl_res.status_code}")
            return None, None

        # Step 3: determine extension from content-type
        content_type = dl_res.headers.get("Content-Type", "").split(";")[0].strip()
        ext = mt.guess_extension(content_type) or ""
        # Fix common wrong guesses
        ext_fixes = {".jpe": ".jpg", ".jpeg": ".jpg", ".jfif": ".jpg"}
        ext = ext_fixes.get(ext, ext)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{media_type}_{timestamp}{ext}"
        os.makedirs(MEDIA_FOLDER, exist_ok=True)
        filepath = os.path.join(MEDIA_FOLDER, filename)

        with open(filepath, "wb") as f:
            f.write(dl_res.content)

        log.info(f"Media saved: {filepath}")
        return filepath, filename

    except Exception as e:
        log.error(f"_download_whatsapp_media error: {e}")
        return None, None


@webhook_bp.route("/webhook", methods=["GET"])
def verify():
    verify_token = os.getenv("VERIFY_TOKEN")
    incoming = request.args.get("hub.verify_token")
    log.info(f"Webhook verify: incoming='{incoming}' expected='{verify_token}'")
    if incoming and incoming == verify_token:
        return request.args.get("hub.challenge")
    return "Forbidden", 403


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        log.warning("Invalid webhook signature — request rejected")
        return "Forbidden", 403

    data = request.get_json(silent=True)
    log.info(f"POST received, entries={len(data.get('entry', [])) if data else 0}")
    if not data:
        log.warning("Empty/invalid JSON body — nothing to process")
        return "OK", 200

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

                incoming_messages = value.get("messages", [])
                log.info(f"{len(incoming_messages)} message(s) in this payload")

                for msg in incoming_messages:
                    msg_id = msg.get("id")
                    log.info(f"Handling message id={msg_id} type={msg.get('type')} from={msg.get('from')}")

                    if _check_and_mark_processed(msg_id):
                        log.info(f"Duplicate skipped: {msg_id}")
                        continue

                    phone = msg["from"]
                    name = contacts.get(phone, "")
                    _handle_message(msg, socketio, name=name)
                    log.info(f"Finished handling {msg_id}")

    except Exception as e:
        log.error(f"ERROR while processing: {e}")
        import traceback
        traceback.print_exc()

    return "OK", 200


_MENU_SELECTION_RE = re.compile(
    r'^(?:option|opt|no\.?|number|#)?\s*[:\-]?\s*\(?\s*(\d{1,2})\s*\)?\s*[.\)]?$',
    re.IGNORECASE,
)


def _extract_menu_selection(text):
    """Recognizes a menu-number reply even with the punctuation/wording
    real customers actually type — '1', '1.', '(2)', '#3', 'Option 4',
    'no. 5' — while still refusing to match ordinary sentences that
    merely happen to contain a digit ('call after 5pm', 'I have 2
    kids'), since the whole (stripped) message must match end-to-end.
    Returns the number as a string (e.g. '1'), or None if this doesn't
    look like a menu selection at all.
    """
    text = (text or "").strip()
    if not text:
        return None
    match = _MENU_SELECTION_RE.match(text)
    return match.group(1) if match else None


def _handle_message(msg, socketio, name=""):
    phone = msg["from"]
    msg_type = msg.get("type", "text")
    msg_id = msg.get("id")

    # If this message carries a Click-to-WhatsApp ad referral, figure out
    # which brand it points to. Passed into save_user so it gets recorded
    # against this phone number the first time — and only the first time
    # — a source is available for them (see save_user's docstring).
    ad_source = _detect_ad_source(msg)
    is_new = save_user(phone, socketio, name=name, source=ad_source)
    # Whatever's on file for this user now (just-recorded ad_source for a
    # brand-new contact, or whatever was recorded on a previous contact) —
    # this decides which menu they see.
    source = ad_source or get_user_source(phone)

    # A brand-new contact's first message might not be plain text at all
    # — a photo of their CNIC, a voice note, a shared location. Without
    # this, only the "text" branch below ever greets a new user, so
    # anyone whose first contact is a photo/document/etc. gets total
    # silence. The text branch handles its own is_new welcome (it also
    # needs to check MENU_TRIGGERS at the same time), so skip it there
    # to avoid sending the welcome menu twice.
    #
    # IMPORTANT: this must exclude "interactive" (list_reply/button_reply
    # taps) and "button" (legacy quick-reply taps). Those are explicit
    # menu selections that get handled by their own branch further down
    # in this function — a genuinely brand-new contact can never have an
    # interactive/button reply as their literal first message anyway
    # (there's nothing on their screen yet to tap). If `is_new` is True
    # on one of these (e.g. a user record got reset/recreated while an
    # old menu was still on the customer's screen), letting this block
    # run too means BOTH this generic/combined welcome AND the specific
    # menu from the real tap handler get sent — e.g. tapping "Business
    # Services" would send the combined Biz+Law text here first, then
    # the correct Biz-only list from the button_reply handler below.
    if is_new and msg_type not in ("text", "interactive", "button"):
        _user_service_context.pop(phone, None)
        _contact_collection.pop(phone, None)
        _user_menu_view[phone] = source
        _user_current_screen.pop(phone, None)
        _executor.submit(_send_welcome_menu, phone, socketio, source)

    if msg_type == "text":
        text = msg["text"]["body"].strip()
        socketio.emit("user_typing", {"phone": phone, "typing": True})
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)

        text_lower = text.lower()

        # If we're mid-way through collecting Name / Mobile / Best Time,
        # every text reply goes to that flow until it completes — this
        # MUST be checked before MENU_TRIGGERS, otherwise a user typing
        # something like "help" or "info" as their name/mobile/best-time
        # answer would silently abort the booking flow and reset to the
        # main menu instead of completing the consultation booking.
        if phone in _contact_collection:
            _handle_contact_collection(phone, text, socketio)
            return

        # ── Widget lead → straight to the specific submenu ──────────────
        # A widget lead's topic is a much stronger signal than an ad
        # click's free text: it's one of the widget's own fixed button
        # labels, not a phrase we have to keyword-guess at. When it
        # matches a known service, skip the brand-level welcome menu
        # entirely (both the is_new and returning-contact branches below
        # would otherwise only get us as far as "biz" or "law") and open
        # that service's submenu directly — same as if the customer had
        # manually tapped "View Services" -> "Taxation Services"
        # themselves. Runs for both new and returning contacts, since
        # someone can click "Continue on WhatsApp" again after having
        # messaged the bot before.
        if _looks_like_widget_lead(text):
            topic = _extract_widget_lead_topic(text)
            match = WIDGET_TOPIC_SERVICE_MAP.get(topic) if topic else None
            if match:
                service_id, brand = match
                _user_service_context.pop(phone, None)
                _contact_collection.pop(phone, None)
                _user_menu_view[phone] = brand
                if service_id in SERVICE_MENU_IDS:
                    _user_service_context[phone] = service_id
                    _user_current_screen[phone] = service_id
                    _executor.submit(_send_service_menu_safe, phone, service_id, socketio)
                elif service_id in BIZ_DIRECT_IDS:
                    response = _contact_us_response(brand) if service_id == "contact_us" else BUTTON_RESPONSES.get(service_id, "")
                    if response:
                        _user_current_screen[phone] = service_id
                        _executor.submit(_send_text_reply, phone, response, socketio, service_id)
                    else:
                        _user_current_screen.pop(phone, None)
                        _executor.submit(_send_welcome_menu, phone, socketio, brand)
                else:
                    # Topic matched a service_id that isn't wired into
                    # either dict yet (e.g. a future addition) — fail
                    # safe to the brand menu rather than sending nothing.
                    _user_current_screen.pop(phone, None)
                    _executor.submit(_send_welcome_menu, phone, socketio, brand)
                return
            # Unmatched topic (the generic "bizservices" tag from freeform
            # widget chat, or a future topic not yet added to the map
            # above) — fall through unchanged to the existing
            # is_new/ad_source handling below.

        if is_new:
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)

            if ad_source:
                # Came in via a Click-to-WhatsApp ad for a specific brand —
                # that's an explicit signal, so go straight to that brand's
                # menu rather than making them ask for it.
                _user_menu_view[phone] = source
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, source)
                return

            if text_lower in BIZ_MENU_TRIGGERS:
                _user_menu_view[phone] = "biz"
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, "biz")
                return

            if text_lower in LAW_MENU_TRIGGERS:
                _user_menu_view[phone] = "law"
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, "law")
                return

            if _is_greeting(text):
                # Plain "hi"/"salam"/etc. with no ad and no direct brand
                # request — greet them and let them pick, same short reply
                # a returning contact gets, instead of dumping the full menu.
                _user_menu_view[phone] = None
                _executor.submit(_send_greeting_reply, phone, socketio)
                return

            # Anything else from a brand-new contact (an explicit "menu",
            # or free text that isn't a greeting/trigger) — fall back to
            # the original behavior and show the combined/brand menu.
            _user_menu_view[phone] = source
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, source)
            return

        if ad_source:
            # RETURNING contact, but this message's content/referral still
            # clearly points to one brand — e.g. tapping a "Continue on
            # WhatsApp" link from the website widget again after having
            # messaged the bot before. Previously ad_source was only ever
            # acted on inside the `if is_new:` block above, so a returning
            # tester always fell through to MENU_TRIGGERS / _is_greeting
            # instead and got the generic combined menu no matter what
            # they'd actually clicked. This applies identically to a
            # future LawAdvise widget lead, since ad_source is already
            # 'biz' | 'law' | None from _detect_ad_source, brand-agnostic.
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            _user_menu_view[phone] = ad_source
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, ad_source)
            return

        if text_lower in FULL_MENU_TRIGGERS:
            # Explicit ask for EVERYTHING — always the full combined menu,
            # regardless of which ad (if any) this phone is attributed to.
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            _user_menu_view[phone] = None
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, None)
            return

        if text_lower in MENU_TRIGGERS:
            # An explicit "menu" request is a different signal than the
            # passive first-touch welcome — the person is actively asking
            # what's available. Uses _resolve_menu_source, which prefers
            # whichever menu they were actually just looking at over
            # their permanently-locked ad `source` — e.g. a LawAdvise-ad
            # customer who navigated into BizAdvise's Taxation submenu
            # via "full menu" stays in that BizAdvise context on "menu",
            # rather than being snapped back to LawAdvise just because
            # that's the ad they originally clicked. First-ever "menu"
            # this session still falls back to their locked source, so
            # ad attribution still matters — see _resolve_menu_source's
            # docstring for the full reasoning. Anyone who wants the
            # full combined list on purpose can ask via FULL_MENU_TRIGGERS
            # above.
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            menu_source = _resolve_menu_source(phone, source)
            _user_menu_view[phone] = menu_source
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, menu_source)
            return

        if text_lower in BIZ_MENU_TRIGGERS:
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            _user_menu_view[phone] = "biz"
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, "biz")
            return

        if text_lower in LAW_MENU_TRIGGERS:
            _user_service_context.pop(phone, None)
            _contact_collection.pop(phone, None)
            _user_menu_view[phone] = "law"
            _user_current_screen.pop(phone, None)
            _executor.submit(_send_welcome_menu, phone, socketio, "law")
            return

        if _is_greeting(text):
            # Returning contact greeting again (any time later) — short
            # reply pointing them to bizservices/lawservices/menu, instead
            # of routing to the AI.
            mode = get_user_mode(phone)
            if mode == 0:
                _executor.submit(_send_greeting_reply, phone, socketio)
            return

        if phone in _user_service_context:
            service = _user_service_context[phone]
            selection = _extract_menu_selection(text)
            if selection and selection == _BACK_TO_MAIN_MENU_OPTION.get(service):
                # Same resolution as typed "menu" — stay in whichever
                # brand's menu they were actually just navigating
                # (_user_menu_view), not hardcoded to the combined menu.
                # Previously this always forced the combined menu even
                # for an ad-sourced customer who'd been shown (and was
                # backing out of) a single-brand submenu, which put them
                # somewhere they hadn't asked to be.
                del _user_service_context[phone]
                _contact_collection.pop(phone, None)
                menu_source = _resolve_menu_source(phone, source)
                _user_menu_view[phone] = menu_source
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, menu_source)
                return
            response = ALL_SUB_RESPONSES.get(service, {}).get(selection) if selection else None
            if response:
                _executor.submit(_send_text_reply, phone, response, socketio, service)
                del _user_service_context[phone]
                return
            # Didn't match this submenu — the user went off-script (asked
            # something free-form) or mistyped a number. Clear the stale
            # context so a LATER message (e.g. a genuine new main-menu
            # number) isn't misinterpreted as still answering this old
            # submenu, then fall through to check the main menu / AI below.
            del _user_service_context[phone]

        selection = _extract_menu_selection(text)
        # Interpret the number against whichever menu this phone was
        # actually last shown (_user_menu_view), not against their
        # permanently-locked ad `source` — if they typed "menu" and got
        # the combined 1-17 list, "10" must mean "Divorce / Khula" from
        # that list, not whatever "10" would mean on a brand-only menu.
        # Falls back to `source` if we haven't shown this phone a menu
        # yet in this process's lifetime (e.g. server just restarted).
        active_view = _user_menu_view.get(phone, source)
        service_menu_map = _service_menu_map(active_view)
        if selection and selection in service_menu_map:
            title, service_id = service_menu_map[selection]
            if service_id in SERVICE_MENU_IDS:
                _user_service_context[phone] = service_id
                _user_current_screen[phone] = service_id
                _executor.submit(_send_service_menu_safe, phone, service_id, socketio)
            elif service_id in BIZ_DIRECT_IDS:
                response = _contact_us_response(active_view) if service_id == "contact_us" else BUTTON_RESPONSES.get(service_id, "")
                if response:
                    _user_current_screen[phone] = service_id
                    _executor.submit(_send_text_reply, phone, response, socketio, service_id)
            return

        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)
        else:
            log.info(f"Human mode active for {phone} — AI skipped")

    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")

        if interactive_type == "list_reply":
            selected_id = interactive["list_reply"]["id"]
            selected_title = interactive["list_reply"]["title"]
            save_message(phone, selected_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)

            if selected_id == "show_full_menu":
                # Tapped the "See All Services" row appended to a
                # single-brand menu — same as typing a FULL_MENU_TRIGGERS
                # phrase, always shows the combined menu regardless of
                # this phone's ad source.
                _user_service_context.pop(phone, None)
                _contact_collection.pop(phone, None)
                _user_menu_view[phone] = None
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, None)

            elif selected_id == "nav_main":
                # Tapped the "🏠 Main Menu" (or single-row "🔙 Back to
                # Main Menu" on a Biz category list) — always jumps home.
                _handle_nav_main(phone, socketio, source)

            elif selected_id == "nav_back":
                # Tapped "🔙 Back" inside a Law category list (5-row
                # version) — one tier below main, so this behaves the
                # same as nav_main here; kept distinct from the leaf
                # 🔙 Back case below only for symmetry with the diagram.
                _handle_nav_back(phone, socketio, source)

            elif selected_id in BIZ_DIRECT_IDS:
                # _user_menu_view (whichever brand's list this row was
                # actually tapped from) rather than the locked `source` —
                # matches the same reasoning as _resolve_menu_source, and
                # is what makes a LawAdvise customer's "Talk to an
                # Expert" tap resolve to LAW_CONTACT via
                # _contact_us_response below instead of always getting
                # BizAdvise's number.
                menu_brand = _user_menu_view.get(phone, source)
                response = _contact_us_response(menu_brand) if selected_id == "contact_us" else BUTTON_RESPONSES.get(selected_id, "")
                if response:
                    _user_current_screen[phone] = selected_id
                    _executor.submit(_send_leaf_reply, phone, response, socketio, selected_id, None)

            elif selected_id in SERVICE_MENU_IDS:
                # Tapped a category row on the main menu list.
                _user_service_context[phone] = selected_id
                _user_current_screen[phone] = selected_id
                _executor.submit(_send_service_menu_safe, phone, selected_id, socketio)

            elif selected_id in LEAF_RESPONSES:
                # Tapped a content row inside a category list (e.g.
                # "divorce_procedure" or "biz_tax_1") — send the leaf
                # answer with its own Back/Main Menu buttons.
                response = LEAF_RESPONSES[selected_id]
                parent = LEAF_PARENT.get(selected_id)
                _user_current_screen[phone] = selected_id
                _executor.submit(_send_leaf_reply, phone, response, socketio, selected_id, parent)

        elif interactive_type == "button_reply":
            button_id = interactive["button_reply"]["id"]
            button_title = interactive["button_reply"]["title"]
            save_message(phone, button_title, "user", socketio,
                         status="delivered", whatsapp_message_id=msg_id)

            if button_id == "nav_main":
                _handle_nav_main(phone, socketio, source)
                return

            if button_id == "nav_back":
                _handle_nav_back(phone, socketio, source)
                return

            if button_id in ("greet_biz", "greet_law", "greet_menu"):
                # Tapped one of the 3 greeting quick-reply buttons —
                # routes to the exact same place as typing bizservices /
                # lawservices / menu would.
                _user_service_context.pop(phone, None)
                _contact_collection.pop(phone, None)
                menu_source = {"greet_biz": "biz", "greet_law": "law", "greet_menu": None}[button_id]
                _user_menu_view[phone] = menu_source
                _user_current_screen.pop(phone, None)
                _executor.submit(_send_welcome_menu, phone, socketio, menu_source)
                return

            if button_id in SERVICE_MENU_IDS:
                # Legacy path — kept in case a customer still has an old
                # 3-button category message on screen from before this
                # rollout.
                _user_service_context[phone] = button_id
                _user_current_screen[phone] = button_id
                _executor.submit(_send_service_menu_safe, phone, button_id, socketio)
                return

            if button_id in LEAF_RESPONSES:
                response = LEAF_RESPONSES[button_id]
                parent = LEAF_PARENT.get(button_id)
                _user_current_screen[phone] = button_id
                _executor.submit(_send_leaf_reply, phone, response, socketio, button_id, parent)
                return

            mode = get_user_mode(phone)
            if mode == 0:
                _executor.submit(_process_ai_reply, phone, button_title, socketio)

    elif msg_type in ("image", "audio", "document", "video"):
        media_info = msg.get(msg_type, {})
        caption = media_info.get("caption", "") or ""
        media_id = media_info.get("id")

        # Download in background so webhook returns fast
        def save_media():
            local_path, local_filename = None, None
            if media_id:
                local_path, local_filename = _download_whatsapp_media(media_id, msg_type)
            display_text = caption or f"Sent a {msg_type}"
            save_message(
                phone, display_text, "user", socketio,
                message_type=msg_type, whatsapp_message_id=msg_id,
                media_path=local_path,
                file_name=local_filename or media_info.get("filename", ""),
            )

        _executor.submit(save_media)

    elif msg_type == "button":
        text = msg["button"]["text"]
        save_message(phone, text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id)
        mode = get_user_mode(phone)
        if mode == 0:
            _executor.submit(_process_ai_reply, phone, text, socketio)

    elif msg_type == "location":
        loc = msg.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        label = loc.get("name") or loc.get("address") or ""
        display_text = f"📍 Shared location{f' — {label}' if label else ''}"
        if lat is not None and lng is not None:
            display_text += f" ({lat}, {lng})"
        save_message(phone, display_text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type="location")

    elif msg_type == "contacts":
        contact_cards = msg.get("contacts", [])
        names = [
            c.get("name", {}).get("formatted_name", "Contact")
            for c in contact_cards
        ] or ["a contact"]
        display_text = f"👤 Shared contact: {', '.join(names)}"
        save_message(phone, display_text, "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type="contacts")

    else:
        # Catch-all for anything not explicitly handled above (stickers,
        # reactions, polls, unsupported/future WhatsApp message types).
        # Previously these were silently dropped — not even saved — so
        # staff had no idea the customer sent anything at all. At minimum
        # always record that something arrived.
        log.warning(f"Unhandled message type '{msg_type}' from {phone} — saving a placeholder")
        save_message(phone, f"[Unsupported message type: {msg_type}]", "user", socketio,
                     status="delivered", whatsapp_message_id=msg_id,
                     message_type=msg_type)


def _handle_nav_main(phone, socketio, source):
    """🏠 Main Menu — always jumps straight home, skipping however deep
    the customer had navigated. Same brand-resolution as a typed
    'menu' (see _resolve_menu_source): stays on whichever brand they
    were actually just looking at."""
    _user_service_context.pop(phone, None)
    _contact_collection.pop(phone, None)
    menu_source = _resolve_menu_source(phone, source)
    _user_menu_view[phone] = menu_source
    _user_current_screen.pop(phone, None)
    _executor.submit(_send_welcome_menu, phone, socketio, menu_source)


def _handle_nav_back(phone, socketio, source):
    """🔙 Back — "one screen up", resolved from _user_current_screen:
      - currently on a LEAF answer -> re-send its parent category list
        (and update the tracked screen back to that category).
      - currently on anything else (a category list, or we've lost
        track of where they were) -> behaves exactly like Main Menu,
        since every category sits directly one level below the main
        menu — there's nowhere else "up" to go."""
    current = _user_current_screen.get(phone)
    parent = LEAF_PARENT.get(current) if current else None
    if parent:
        _user_service_context[phone] = parent
        _user_current_screen[phone] = parent
        _executor.submit(_send_service_menu_safe, phone, parent, socketio)
    else:
        _handle_nav_main(phone, socketio, source)


def _handle_contact_collection(phone, text, socketio):
    """Walks a user through an optional callback-choice step (for the
    more ambiguous 'Talk to Expert' paths), then Name -> Mobile -> Best
    Time to Call, then emits a consultation_booked event so the
    dashboard can surface it."""
    state = _contact_collection.get(phone, {})
    step = state.get("step")

    # Let the customer bail out of the callback/booking flow at any
    # step and jump straight back to the main menu, instead of being
    # stuck finishing (or awkwardly answering into) Name/Mobile/Best-Time
    # just because they started down this path earlier.
    text_lower = text.strip().lower()

    if text_lower in FULL_MENU_TRIGGERS:
        # Explicit ask for EVERYTHING — full combined menu regardless of
        # this phone's ad source.
        del _contact_collection[phone]
        _user_service_context.pop(phone, None)
        _user_menu_view[phone] = None
        _user_current_screen.pop(phone, None)
        _executor.submit(_send_welcome_menu, phone, socketio, None)
        return

    if text_lower in MENU_TRIGGERS:
        # Same resolution as the MENU_TRIGGERS branch in _handle_message —
        # prefers whichever menu this phone was actually last shown
        # (_user_menu_view) over their permanently-locked ad `source`,
        # falling back to `source` only if nothing's been shown yet
        # this session. See _resolve_menu_source's docstring.
        del _contact_collection[phone]
        _user_service_context.pop(phone, None)
        source = get_user_source(phone)
        menu_source = _resolve_menu_source(phone, source)
        _user_menu_view[phone] = menu_source
        _user_current_screen.pop(phone, None)
        _executor.submit(_send_welcome_menu, phone, socketio, menu_source)
        return

    if step == "awaiting_callback_choice":
        choice = _interpret_yes_no(text)
        if choice == "yes":
            _contact_collection[phone]["step"] = "awaiting_name"
            _executor.submit(_send_text_reply, phone,
                             "Great! Let's get you booked in. Please share your *Name*:\n\n_(Type menu anytime to start over)_", socketio)
        elif choice == "no":
            reply_contact = state.get("contact", CONTACT)
            del _contact_collection[phone]
            _executor.submit(_send_text_reply, phone,
                             f"No problem! Feel free to reach us anytime at 📞 {reply_contact}.{_BACK_TO_MENU_HINT}", socketio)
        else:
            # Didn't understand the reply — re-ask rather than silently
            # dropping into the collection flow (or out of it) on a guess.
            _executor.submit(_send_text_reply, phone,
                             "Sorry, I didn't quite catch that 🙏 Please reply *1* for a callback, or *2* if you'll reach out yourself.",
                             socketio)
        return

    if step == "awaiting_name":
        _contact_collection[phone]["name"] = text
        _contact_collection[phone]["step"] = "awaiting_mobile"
        _executor.submit(_send_text_reply, phone,
                         "Thank you! Please share your *Mobile Number*:\n\n_(Type menu anytime to start over)_", socketio)

    elif step == "awaiting_mobile":
        _contact_collection[phone]["mobile"] = text
        _contact_collection[phone]["step"] = "awaiting_time"
        _executor.submit(_send_text_reply, phone,
                         "Great! What is the *Best Time to Call* you?\n_(e.g. Morning, Afternoon, Evening or a specific time)_\n\n_(Type menu anytime to start over)_", socketio)

    elif step == "awaiting_time":
        name = state.get("name", "")
        mobile = state.get("mobile", "")
        best_time = text
        reply_contact = state.get("contact", CONTACT)
        consultation_id = state.get("consultation_id")
        service_label = state.get("service_label", "")
        del _contact_collection[phone]
        confirmation = (
            f"✅ *Thank you, {name}!*\n\n"
            f"Our team will contact you at *{mobile}* during *{best_time}*.\n\n"
            f"If urgent, you can also reach us at:\n📞 {reply_contact}"
            f"{_BACK_TO_MENU_HINT}"
        )
        _executor.submit(_send_text_reply, phone, confirmation, socketio)
        _user_context[phone] = "main"

        scheduled_at = _parse_best_time(best_time)
        if consultation_id:
            consultation_model.mark_booked(consultation_id, name, mobile, best_time, scheduled_at)
        else:
            # Shouldn't normally happen (the lead is created the moment
            # the booking flow starts) — but never drop a completed
            # booking just because that earlier step failed somehow.
            new_id = consultation_model.create_lead(phone, "", service_label, "")
            consultation_model.mark_booked(new_id, name, mobile, best_time, scheduled_at)
            consultation_id = new_id

        # Emit consultation booked event for dashboard notification
        socketio.emit("consultation_booked", {
            "id": consultation_id,
            "phone": phone,
            "name": name,
            "mobile": mobile,
            "best_time": best_time,
            "scheduled_at": scheduled_at,
            "service_label": service_label,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        log.info(f"Consultation booked: {name} ({mobile}) — best time: {best_time}")


def _send_greeting_reply(phone, socketio):
    """Sends the greeting as 3 tappable buttons (Business Services /
    Legal Services / Full Menu) so the customer can pick with a tap
    instead of typing bizservices/lawservices/menu by hand. Falls back
    to the plain-text GREETING_REPLY (still spelling out those three
    typed options) if the interactive send fails for any reason."""
    try:
        success, wa_id = send_greeting_buttons(phone, GREETING_REPLY_WITH_BUTTONS)
        if success:
            # Log the plain base text against this phone in the
            # dashboard's message history — GREETING_REPLY_WITH_BUTTONS's
            # "select below" only means something next to the buttons
            # that were actually attached, not as a standalone log line.
            save_message(phone, GREETING_REPLY, "bot", socketio,
                         status="sent", whatsapp_message_id=wa_id, source="ai")
        else:
            _send_text_reply(phone, GREETING_REPLY, socketio)
    except Exception as e:
        log.error(f"Greeting reply error for {phone}: {e}")
        _send_text_reply(phone, GREETING_REPLY, socketio)


def _send_welcome_menu(phone, socketio, source=None):
    """source: 'biz' or 'law' shows that brand's menu only (detected from
    a Click-to-WhatsApp ad referral, or previously recorded for this
    user); anything else shows the original combined menu."""
    try:
        success, wa_id = send_main_menu(phone, source=source)
        if success:
            if source == "biz":
                combined_text = TEXT_MAIN_MENU_BIZ
            elif source == "law":
                combined_text = TEXT_MAIN_MENU_LAW
            else:
                combined_text = TEXT_MAIN_MENU_1 + "\n" + TEXT_MAIN_MENU_2
            save_message(phone, combined_text,
                         "bot", socketio, status="sent",
                         whatsapp_message_id=wa_id, source="ai")
        elif source == "biz":
            success1, wa_id1 = send_text(phone, TEXT_MAIN_MENU_BIZ)
            save_message(phone, TEXT_MAIN_MENU_BIZ, "bot", socketio,
                         status="sent" if success1 else "failed",
                         whatsapp_message_id=wa_id1, source="ai")
        elif source == "law":
            success1, wa_id1 = send_text(phone, TEXT_MAIN_MENU_LAW)
            save_message(phone, TEXT_MAIN_MENU_LAW, "bot", socketio,
                         status="sent" if success1 else "failed",
                         whatsapp_message_id=wa_id1, source="ai")
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
        log.error(f"Welcome menu error for {phone}: {e}")


def _send_service_menu_safe(phone, service_id, socketio):
    try:
        success, wa_id = send_service_menu(phone, service_id)
        if success:
            save_message(phone, ALL_SUB_MENUS.get(service_id, ""), "bot", socketio,
                         status="sent", whatsapp_message_id=wa_id, source="ai")
        else:
            sub_menu = ALL_SUB_MENUS.get(service_id, "")
            if sub_menu:
                _send_text_reply(phone, sub_menu, socketio)
    except Exception as e:
        log.error(f"Service menu error for {phone}: {e}")


def _send_text_reply(phone, text, socketio, service_id=None):
    """service_id: whichever service menu (e.g. 'divorce_khula',
    'biz_tax') the customer was actually looking at when this reply was
    sent — passed through explicitly by every call site that knows it,
    since by the time a background thread gets around to running this,
    _user_service_context[phone] may already have been cleared for the
    next message. Only matters for the two branches below that kick off
    a consultation lead; ignored otherwise.

    Used for the TEXT/NUMBER fallback path and for internal booking-flow
    prompts (Name/Mobile/Best-Time). Interactive taps use
    _send_leaf_reply instead, which attaches real nav buttons."""
    try:
        success, wa_id = send_text(phone, text)
        save_message(phone, text, "bot", socketio,
                     status="sent" if success else "failed",
                     whatsapp_message_id=wa_id, source="ai")
        if not success:
            return
        service_label = SERVICE_LABELS.get(service_id, "")
        brand = _service_brand(service_id)
        if not brand and LAW_CONTACT in text:
            # Same reasoning as _send_leaf_reply — contact_us is
            # brand-ambiguous by id, but `text` is already the resolved
            # reply, so use it to record an accurate brand on the lead.
            brand = "law"
        # "Book Consultation" paths — explicit booking intent, go
        # straight into the Name -> Mobile -> Best Time collection flow.
        if text in CONSULT_TRIGGER_TEXTS:
            # CONSULT_TRIGGER_TEXTS is exclusively the LawAdvise
            # "Book Consultation" replies (court/divorce/property/docs) —
            # there's no BizAdvise path through here, so LAW_CONTACT is
            # correct unconditionally rather than falling back to CONTACT.
            lead_id = consultation_model.create_lead(phone, service_id or "", service_label, brand or "law")
            _contact_collection[phone] = {
                "step": "awaiting_name",
                "contact": LAW_CONTACT,
                "consultation_id": lead_id,
                "service_label": service_label,
            }
        # "Talk to Expert" / "Talk to Lawyer" paths — more ambiguous
        # intent, so ask first whether they even want a callback before
        # collecting any contact info. Matched by marker phrase rather
        # than exact text, so it doesn't silently break if the wording
        # of any individual prompt changes later.
        elif _is_consult_choice_prompt(text):
            lead_id = consultation_model.create_lead(phone, service_id or "", service_label, brand)
            _contact_collection[phone] = {
                "step": "awaiting_callback_choice",
                # Remembers which brand's number was just quoted, so the
                # "no thanks" reply below doesn't fall back to CONTACT
                # (BizAdvise) for a LawAdvise conversation.
                "contact": LAW_CONTACT if LAW_CONTACT in text else CONTACT,
                "consultation_id": lead_id,
                "service_label": service_label,
            }
    except Exception as e:
        log.error(f"Text reply error for {phone}: {e}")


def _send_leaf_reply(phone, text, socketio, leaf_id, parent_category):
    """Sends a leaf answer reached by TAPPING (a list row or, for the
    legacy BIZ_DIRECT_IDS top-level items, a button) as a 2-button
    message: 🔙 Back (re-sends parent_category's list, or acts like
    Main Menu if parent_category is None — see _handle_nav_back) and
    🏠 Main Menu.

    `text` still carries the typed-'menu' hint (_BACK_TO_MENU_HINT)
    since it's shared with the text-fallback dicts — stripped only for
    display here since real buttons make the hint redundant. Consult-
    flow detection below matches against the original `text`, not the
    stripped version, so it stays in sync with CONSULT_TRIGGER_TEXTS /
    _is_consult_choice_prompt regardless of stripping."""
    try:
        header = SERVICE_LABELS.get(parent_category) or SERVICE_LABELS.get(leaf_id, "")
        body = _strip_back_hint(text)
        success, wa_id = send_nav_buttons(phone, header, body)
        save_message(phone, body, "bot", socketio,
                     status="sent" if success else "failed",
                     whatsapp_message_id=wa_id, source="ai")
        if not success:
            return
        service_label = SERVICE_LABELS.get(leaf_id) or SERVICE_LABELS.get(parent_category, "")
        brand = _service_brand(leaf_id) or _service_brand(parent_category)
        if not brand and LAW_CONTACT in text:
            # contact_us is brand-ambiguous by id alone (see
            # _service_brand's docstring) — but by this point `text` is
            # already the resolved reply (via _contact_us_response), so
            # if it's quoting the LawAdvise number, this is genuinely a
            # LawAdvise lead and the consultation record should say so
            # instead of leaving brand blank.
            brand = "law"
        if text in CONSULT_TRIGGER_TEXTS:
            lead_id = consultation_model.create_lead(phone, leaf_id or "", service_label, brand or "law")
            _contact_collection[phone] = {
                "step": "awaiting_name",
                "contact": LAW_CONTACT,
                "consultation_id": lead_id,
                "service_label": service_label,
            }
        elif _is_consult_choice_prompt(text):
            lead_id = consultation_model.create_lead(phone, leaf_id or "", service_label, brand)
            _contact_collection[phone] = {
                "step": "awaiting_callback_choice",
                "contact": LAW_CONTACT if LAW_CONTACT in text else CONTACT,
                "consultation_id": lead_id,
                "service_label": service_label,
            }
    except Exception as e:
        log.error(f"Leaf reply error for {phone}: {e}")


def _process_ai_reply(phone, text, socketio):
    try:
        reply = ask_ai(text)
        # Every free-chat AI reply carries the human contact numbers —
        # appended here (once, right before send/save) rather than
        # inside ask_ai/the system prompt, so it's guaranteed present
        # regardless of what the model actually generated, and is
        # never itself sent to the model as something to reason about
        # or accidentally omit.
        reply_with_contact = reply + FREE_CHAT_CONTACT_FOOTER
        success, wa_msg_id = send_text(phone, reply_with_contact)
        status = "sent" if success else "failed"
        save_message(phone, reply_with_contact, "bot", socketio,
                     status=status, whatsapp_message_id=wa_msg_id, source="ai")
    except Exception as e:
        log.error(f"AI reply error for {phone}: {e}")