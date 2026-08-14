"""
In-memory store for background-job status (DB backups, media cleanup).

Kept deliberately simple: a single dict guarded by a lock, updated by the
background threads in app.py and read by routes/system.py. This resets
on every deploy/restart, which is fine — its whole purpose is answering
"is the most recent run of these two jobs healthy", not being a
historical log.
"""
import threading

_lock = threading.Lock()

_state = {
    "last_backup_at": None,       # ISO 8601 UTC string, e.g. "2026-08-14T10:00:00Z"
    "last_backup_error": None,    # str or None
    "last_cleanup_at": None,      # ISO 8601 UTC string
    "last_cleanup_deleted": None, # int
    "last_cleanup_freed_mb": None,# float
    "last_cleanup_error": None,   # str or None
}


def update_status(**kwargs):
    """Update one or more fields. Unknown keys are ignored rather than
    raising, so a caller passing a typo'd kwarg doesn't crash a
    background thread."""
    with _lock:
        for key, value in kwargs.items():
            if key in _state:
                _state[key] = value


def get_status() -> dict:
    """Returns a shallow copy of the current state, safe to jsonify."""
    with _lock:
        return dict(_state)