import os
from flask import Blueprint, jsonify, request, abort

from utils.status_state import get_status

system_bp = Blueprint("system", __name__)

DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")


@system_bp.route("/system-status", methods=["GET"])
def system_status():
    # If DASHBOARD_TOKEN isn't set, keep this route locked rather than
    # falling open — an unset token should mean "nobody gets in", not
    # "anyone gets in".
    if not DASHBOARD_SECRET or request.headers.get("X-Dashboard-Token") != DASHBOARD_SECRET:
      abort(401)

    return jsonify(get_status())