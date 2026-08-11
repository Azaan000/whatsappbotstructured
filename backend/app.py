from dotenv import load_dotenv
load_dotenv()

import os
import shutil
import threading
import time
from datetime import datetime
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from models.database import init_db, DB_PATH
from routes.webhook import webhook_bp
from routes.analytics import analytics_bp
from routes.chat import chat_bp
from routes.auth import auth_bp
from routes.broadcast import broadcast_bp
from utils.logger import get_logger

log = get_logger(__name__)

BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})
socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    ping_timeout=60,
    ping_interval=25,
)

app.extensions["socketio"] = socketio

# Wire socketio into whatsapp_handler so it can emit 401 warnings
from bot.whatsapp_handler import set_socketio
set_socketio(socketio)

app.register_blueprint(webhook_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(broadcast_bp)


@app.route("/")
def home():
    return "APP VERSION 1"


init_db()


def _run_media_cleanup():
    """Background thread: clean up media files older than 30 days.
    Runs once shortly after startup (so a server that's restarted daily
    for deploys isn't silently skipping cleanup forever), then every
    24h after that."""
    from bot.whatsapp_handler import cleanup_old_media
    time.sleep(60)  # brief delay so this doesn't compete with startup
    while True:
        try:
            deleted, freed = cleanup_old_media(days=30)
            log.info(f"Media cleanup done: {deleted} files, {freed/1024/1024:.1f} MB freed")
        except Exception as e:
            log.error(f"Media cleanup error: {e}")
        time.sleep(86400)


def _run_db_backup():
    """Background thread: back up the SQLite database file on a schedule.

    There was previously NO backup mechanism at all — if database.db got
    corrupted, deleted, or a bad migration ran, every conversation and
    every user record would simply be gone with no way back. This copies
    the live db file (safe to do even while the app is running, since
    SQLite's WAL mode means readers/writers don't block a file copy of
    the main db file — though a copy mid-write can occasionally miss the
    very latest WAL-only transactions; for anything more rigorous than
    this lightweight scheme, use the sqlite3 .backup API or a proper
    external backup tool) into BACKUP_DIR with a timestamped filename,
    then deletes backups older than BACKUP_RETENTION_DAYS so this
    doesn't grow disk usage forever.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    time.sleep(120)  # let the app fully settle before the first backup
    while True:
        try:
            if os.path.exists(DB_PATH):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = os.path.join(BACKUP_DIR, f"database_{ts}.db")
                shutil.copy2(DB_PATH, dest)
                log.info(f"Database backup created: {dest}")
            else:
                log.warning(f"Backup skipped — {DB_PATH} does not exist")

            cutoff = time.time() - (BACKUP_RETENTION_DAYS * 86400)
            removed = 0
            for fname in os.listdir(BACKUP_DIR):
                fpath = os.path.join(BACKUP_DIR, fname)
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            if removed:
                log.info(f"Pruned {removed} backup(s) older than {BACKUP_RETENTION_DAYS} days")
        except Exception as e:
            log.error(f"Database backup error: {e}")
        time.sleep(21600)  # every 6 hours


def _run_scheduled_broadcasts():
    """Background thread: every minute, look for broadcasts that were
    scheduled for a future time and are now due, and actually send
    them. This runs server-side (unlike an immediate broadcast, which
    the dashboard drives from the browser) because a scheduled send has
    to go out even if nobody has the dashboard open at that moment.
    """
    import random
    from models.broadcast import (
        get_due_scheduled_broadcasts, mark_broadcast_sending,
        set_recipient_status, finish_broadcast,
    )
    from models.message import save_message
    from bot.whatsapp_handler import send_text, send_media

    time.sleep(30)  # let the app finish starting up first
    while True:
        try:
            due = get_due_scheduled_broadcasts()
            for b in due:
                mark_broadcast_sending(b["id"])
                min_delay = max(0, b.get("min_delay_ms") or 400) / 1000
                max_delay = max(min_delay, (b.get("max_delay_ms") or 900) / 1000)
                for r in b["recipients"]:
                    if r.get("status") == "sent":
                        continue  # already sent (e.g. a resumed/interrupted run)
                    phone = r["phone"]
                    try:
                        if b.get("media_path"):
                            success, wa_id = send_media(
                                phone, b["media_path"], b.get("media_type") or "document",
                                b.get("message") or f"Sent: {b.get('file_name','')}",
                            )
                        else:
                            success, wa_id = send_text(phone, b["message"])
                        status = "sent" if success else "failed"
                        save_message(
                            phone, b.get("message") or f"Sent: {b.get('file_name','')}",
                            "bot", socketio, status=status, whatsapp_message_id=wa_id,
                        )
                    except Exception as e:
                        log.error(f"Scheduled broadcast {b['id']} send error for {phone}: {e}")
                        status = "failed"
                    set_recipient_status(b["id"], phone, status)
                    time.sleep(random.uniform(min_delay, max_delay))
                finish_broadcast(b["id"], status="completed")
                log.info(f"Scheduled broadcast {b['id']} sent")
        except Exception as e:
            log.error(f"Scheduled broadcast runner error: {e}")
        time.sleep(60)


# Start background cleanup thread
cleanup_thread = threading.Thread(target=_run_media_cleanup, daemon=True)
cleanup_thread.start()

# Start background database backup thread
backup_thread = threading.Thread(target=_run_db_backup, daemon=True)
backup_thread.start()

# Start background scheduled-broadcast thread
scheduled_broadcast_thread = threading.Thread(target=_run_scheduled_broadcasts, daemon=True)
scheduled_broadcast_thread.start()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    log.info("=" * 50)
    log.info("WhatsApp Bot Server starting")
    log.info("=" * 50)
    log.info("Webhook  : http://localhost:5000/webhook")
    log.info("Dashboard: http://localhost:3000")
    log.info("Health   : http://localhost:5000/health")
    log.info("=" * 50)
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=debug)