from flask import Blueprint, request, jsonify

from models.dashboard_user import (
    verify_dashboard_login,
    get_dashboard_user,
    create_dashboard_user,
    list_dashboard_users,
    delete_dashboard_user,
    verify_dashboard_password,
    dashboard_admin_count,
)
from utils.auth import issue_token, verify_token, require_auth, require_admin

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    """Public self-registration. The very first account created on a
    fresh install automatically becomes an admin; everyone after that
    is a regular user (an existing admin can promote/manage others
    through the admin endpoints below)."""
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()

    user, error = create_dashboard_user(username, password, display_name)
    if error:
        return jsonify({"error": error}), 400

    token = issue_token(user["id"])
    return jsonify({"token": token, "user": user}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    user = verify_dashboard_login(username, password)
    if not user:
        # Deliberately the same error for "no such user" and "wrong
        # password" — a different message for each would let someone
        # enumerate valid usernames by testing which ones give a
        # different error.
        return jsonify({"error": "Invalid username or password"}), 401

    token = issue_token(user["id"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"], "is_admin": user["is_admin"]},
    })


@auth_bp.route("/me", methods=["GET"])
def me():
    """Lets the dashboard check on load whether a saved token is still
    valid, and who it belongs to — without needing to re-enter the
    password just to confirm the session hasn't expired."""
    token = request.headers.get("X-Dashboard-Token") or request.args.get("token")
    user_id = verify_token(token)
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    user = get_dashboard_user(user_id)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"user": user})


@auth_bp.route("/account", methods=["DELETE"])
@require_auth
def delete_own_account():
    """Self-service account deletion. Requires re-entering the current
    password in the request body — a valid session token alone isn't
    enough for something this destructive/irreversible (protects
    against e.g. a logged-in session left open on a shared machine)."""
    user_id = request.dashboard_user_id
    if user_id is None:
        # Only reachable via the shared-secret fallback, which isn't
        # tied to any one account.
        return jsonify({"error": "No account associated with this session"}), 400

    data = request.json or {}
    password = data.get("password") or ""
    if not verify_dashboard_password(user_id, password):
        return jsonify({"error": "Incorrect password"}), 401

    user = get_dashboard_user(user_id)
    if user and user.get("is_admin") and dashboard_admin_count() <= 1:
        return jsonify({"error": "You're the last admin — promote another account to admin before deleting this one"}), 400

    if not delete_dashboard_user(user_id):
        return jsonify({"error": "Could not delete account"}), 500
    return jsonify({"ok": True})


@auth_bp.route("/dashboard-users", methods=["GET"])
@require_auth
@require_admin
def list_users():
    """Admin-only: list every dashboard account (for a user-management
    screen). No password hashes are ever included. Deliberately NOT at
    /users — chat_bp already owns that path for the list of WhatsApp
    customers."""
    return jsonify({"users": list_dashboard_users()})


@auth_bp.route("/dashboard-users/<int:target_id>", methods=["DELETE"])
@require_auth
@require_admin
def delete_user(target_id):
    """Admin-only: delete any account by id. An admin can't remove the
    last remaining admin (including themselves) this way, so the
    dashboard never ends up with zero admins able to manage it."""
    target = get_dashboard_user(target_id)
    if not target:
        return jsonify({"error": "User not found"}), 404

    if target.get("is_admin") and dashboard_admin_count() <= 1:
        return jsonify({"error": "Cannot delete the last remaining admin"}), 400

    if not delete_dashboard_user(target_id):
        return jsonify({"error": "Could not delete user"}), 500
    return jsonify({"ok": True})