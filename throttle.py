"""Limits repeated failed logins. State lives on the app, so every app instance has its own."""
import time

from flask import current_app

MAX_ATTEMPTS = 5
WINDOW = 15 * 60          # five failures per fifteen minutes


def _store():
    return current_app.extensions.setdefault("login_attempts", {})


def blocked(key):
    now = time.time()
    recent = [t for t in _store().get(key, []) if now - t < WINDOW]
    _store()[key] = recent
    return len(recent) >= MAX_ATTEMPTS


def fail(key):
    _store().setdefault(key, []).append(time.time())


def reset(key):
    _store().pop(key, None)
