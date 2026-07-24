from dotenv import load_dotenv
load_dotenv()

import os
import threading
import time
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from models.database import init_db
from routes.webhook import webhook_bp
from routes.analytics import analytics_bp
from routes.chat import chat_bp

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

init_db()


def _run_media_cleanup():
    """Background thread: clean up media files older than 30 days, runs every 24h."""
    from bot.whatsapp_handler import cleanup_old_media
    while True:
        time.sleep(86400)  # wait 24 hours before first run
        try:
            deleted, freed = cleanup_old_media(days=30)
            print(f"[Scheduler] Media cleanup done: {deleted} files, {freed/1024/1024:.1f} MB freed")
        except Exception as e:
            print(f"[Scheduler] Media cleanup error: {e}")


# Start background cleanup thread
cleanup_thread = threading.Thread(target=_run_media_cleanup, daemon=True)
cleanup_thread.start()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    print("\n" + "=" * 50)
    print("WhatsApp Bot Server")
    print("=" * 50)
    print(f"Webhook  : http://localhost:5000/webhook")
    print(f"Dashboard: http://localhost:3000")
    print(f"Health   : http://localhost:5000/health")
    print("=" * 50 + "\n")
    socketio.run(app, host="0.0.0.0", port=5000, debug=debug, allow_unsafe_werkzeug=debug)