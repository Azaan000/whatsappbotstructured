import os
import hmac
from functools import wraps
from flask import request, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

# 7 days — long enough that staff aren't re-logging-in constantly, short
# enough that a leaked token doesn't stay valid forever. Tokens are
# per-user (unlike the old single shared DASHBOARD_SECRET), so a login
# now identifies WHO did something, not just THAT someone had the key.
TOKEN_MAX_AGE = 7 * 24 * 60 * 60

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="dashboard-login")


def issue_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def verify_token(token: str):
    """Returns the user_id if the token is valid and unexpired, else None."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def _matches_shared_secret(candidate: str) -> bool:
    """Constant-time comparison — plain `==` short-circuits on the first
    mismatched character, which leaks (very slightly) how many leading
    characters were correct via response timing. hmac.compare_digest
    takes the same time regardless of where the mismatch is."""
    if not candidate or not DASHBOARD_SECRET:
        return False
    return hmac.compare_digest(candidate, DASHBOARD_SECRET)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Dashboard-Token") or request.args.get("token")

        # Per-user login token — the normal path now.
        user_id = verify_token(token)
        if user_id is not None:
            request.dashboard_user_id = user_id
            return f(*args, **kwargs)

        # Shared-secret fallback — kept only so DASHBOARD_SECRET can still
        # be used for scripts/automation that aren't a logged-in staff
        # member. Optional: leave DASHBOARD_SECRET unset once every
        # real user has their own login and you don't need this path.
        if _matches_shared_secret(token):
            request.dashboard_user_id = None
            return f(*args, **kwargs)

        if not DASHBOARD_SECRET and user_id is None:
            # Neither a valid per-user token nor a shared secret configured
            # at all — this only happens on a fresh install before the
            # first dashboard_users row exists. Warn loudly rather than
            # silently letting every request through unauthenticated.
            print("WARNING: No valid auth on this request, and DASHBOARD_SECRET is unset.")

        return jsonify({"error": "Unauthorized"}), 401
    return decorated


def require_admin(f):
    """Like require_auth, but also requires the logged-in user to be a
    dashboard admin. Must be stacked under @require_auth (closer to the
    function) so request.dashboard_user_id is already set. The shared-
    secret fallback in require_auth sets dashboard_user_id to None,
    which deliberately fails the admin check below rather than treating
    the shared secret as an implicit admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from models.dashboard_user import get_dashboard_user

        user_id = getattr(request, "dashboard_user_id", None)
        user = get_dashboard_user(user_id) if user_id is not None else None
        if not user or not user.get("is_admin"):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated