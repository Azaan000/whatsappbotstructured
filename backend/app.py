from dotenv import load_dotenv
load_dotenv()

import os
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

app.register_blueprint(webhook_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(chat_bp)

init_db()

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