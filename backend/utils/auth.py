import os
from functools import wraps
from flask import request, jsonify

DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_SECRET:
            print("WARNING: DASHBOARD_SECRET not set. All routes are unprotected.")
            return f(*args, **kwargs)
        token = request.headers.get("X-Dashboard-Token")
        query_token = request.args.get("token")
        if token == DASHBOARD_SECRET or query_token == DASHBOARD_SECRET:
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated