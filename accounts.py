"""Customer accounts: register, log in, log out and the "My bookings" page.

Guests can still book without an account. A booking made while logged in is linked to the account.
Admin and customer logins are separate: a customer session never opens the admin area.
"""
import sqlite3
from functools import wraps

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
import throttle
from helpers import EMAIL_RE, PHONE_RE

bp = Blueprint("accounts", __name__)
MIN_PASSWORD = 8
# Used to spend the same time checking a password when the email is unknown.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def load_user():
    """Runs before every request and makes the logged-in customer available as g.user."""
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = db.query("SELECT id, name, email, phone FROM users WHERE id = ?", (user_id,), one=True)
        if g.user is None:
            session.pop("user_id", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("accounts.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target, default):
    """Only follow redirects that stay on this site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def _sign_in(user_id):
    session.clear()                       # a fresh session when someone logs in
    session["user_id"] = user_id


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("accounts.account"))
    form = {"name": "", "email": "", "phone": ""}
    errors = []
    if request.method == "POST":
        throttle.rate_limit("register", 10)
        form = {k: request.form.get(k, "").strip() for k in form}
        form["email"] = form["email"].lower()
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        if not 2 <= len(form["name"]) <= 80:
            errors.append("Enter your full name.")
        if not EMAIL_RE.fullmatch(form["email"]) or len(form["email"]) > 120:
            errors.append("Enter a valid email address.")
        if not PHONE_RE.fullmatch(form["phone"]):
            errors.append("Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9.")
        if not MIN_PASSWORD <= len(password) <= 128:
            errors.append(f"Choose a password of at least {MIN_PASSWORD} characters.")
        elif password != confirm:
            errors.append("The two passwords do not match.")
        if not errors:
            try:
                user_id = db.execute("INSERT INTO users (name, email, phone, password_hash) VALUES (?, ?, ?, ?)",
                                     (form["name"], form["email"], form["phone"], generate_password_hash(password)))
            except sqlite3.IntegrityError:
                errors.append("An account with this email already exists. Try logging in instead.")
            else:
                _sign_in(user_id)
                flash(f"Welcome, {form['name']}. Your account is ready.", "ok")
                return redirect(safe_next(request.args.get("next"), url_for("accounts.account")))
    page = render_template("register.html", form=form, errors=errors, next=request.args.get("next", ""))
    return (page, 400) if errors else page


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("accounts.account"))
    next_url = request.args.get("next", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        key = ("user", request.remote_addr or "unknown", email)
        if throttle.blocked(key):
            flash("Too many failed attempts. Try again in a few minutes.", "error")
            return render_template("login.html", email=email, next=next_url), 429
        row = db.query("SELECT id, password_hash FROM users WHERE email = ?", (email,), one=True)
        stored = row["password_hash"] if row else _DUMMY_HASH
        if check_password_hash(stored, request.form.get("password", "")) and row:
            throttle.reset(key)
            _sign_in(row["id"])
            return redirect(safe_next(next_url, url_for("accounts.account")))
        throttle.fail(key)
        flash("Wrong email or password.", "error")
        return render_template("login.html", email=email, next=next_url), 401
    return render_template("login.html", email="", next=next_url)


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "ok")
    return redirect(url_for("home"))


@bp.get("/account")
@login_required
def account():
    rows = db.query("SELECT * FROM bookings WHERE user_id = ? ORDER BY id DESC", (g.user["id"],))
    return render_template("account.html", bookings=rows)
