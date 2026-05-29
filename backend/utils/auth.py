import os
from functools import wraps
from flask import request, jsonify

DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_SECRET:
            # Auth not configured — allow in dev, warn loudly
            print("WARNING: DASHBOARD_SECRET not set. All routes are unprotected.")
            return f(*args, **kwargs)
        token = request.headers.get("X-Dashboard-Token")
        if token != DASHBOARD_SECRET:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated
