"""Limits repeated requests. State lives on the app, so every app instance has its own.

Used for failed logins (5 per 15 minutes) and for form spam (see rate_limit).
"""
import time

from flask import abort, current_app, request

MAX_ATTEMPTS = 5
WINDOW = 15 * 60          # five failures per fifteen minutes


def _store():
    return current_app.extensions.setdefault("login_attempts", {})


def blocked(key, limit=MAX_ATTEMPTS, window=WINDOW):
    now = time.time()
    recent = [t for t in _store().get(key, []) if now - t < window]
    _store()[key] = recent
    return len(recent) >= limit


def hit(key):
    """Record one event (a failed login, or one form submission)."""
    _store().setdefault(key, []).append(time.time())


fail = hit


def reset(key):
    _store().pop(key, None)


def rate_limit(name, limit, window=3600):
    """Stop one address from submitting the same kind of form too often."""
    key = (name, request.remote_addr or "unknown")
    if blocked(key, limit, window):
        abort(429, "Too many requests from this address. Please try again later.")
    hit(key)
