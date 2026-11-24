"""Admin area: dashboard, bookings, enquiries and package management.

Log in at /admin/login. The admin account comes from ADMIN_USERNAME / ADMIN_PASSWORD.
"""
import json
import os
import re
import time
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

import catalog
import db
import throttle
from helpers import (BOOKING_STATUSES, CATEGORIES, CATEGORY_KEYS, ENQUIRY_STATUSES,
                     parse_lines)

bp = Blueprint("admin", __name__)
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,40}")
ADMIN_SESSION_SECONDS = 2 * 60 * 60      # an admin has to log in again after two hours


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin") or time.time() - session.get("admin_at", 0) > ADMIN_SESSION_SECONDS:
            session.pop("admin", None)
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if throttle.blocked(("admin", ip)):
            flash("Too many failed attempts. Try again in a few minutes.", "error")
            return render_template("admin/login.html"), 429
        row = db.query("SELECT * FROM admins WHERE username = ?",
                       (request.form.get("username", "").strip(),), one=True)
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            throttle.reset(("admin", ip))
            session.clear()                       # fresh session after login
            session["admin"] = row["username"]
            session["admin_at"] = int(time.time())
            target = request.args.get("next", "")
            return redirect(target if target.startswith("/admin") else url_for("admin.dashboard"))
        throttle.fail(("admin", ip))
        flash("Wrong username or password.", "error")
        return render_template("admin/login.html"), 401
    return render_template("admin/login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/")
@login_required
def dashboard():
    counts = {r["status"]: r["n"] for r in
              db.query("SELECT status, COUNT(*) AS n FROM bookings GROUP BY status")}
    revenue = db.query("SELECT COALESCE(SUM(amount), 0) AS s FROM payments WHERE status = 'Success'", one=True)["s"]
    customers = db.query("SELECT COUNT(*) AS n FROM users", one=True)["n"]
    new_enquiries = db.query("SELECT COUNT(*) AS n FROM enquiries WHERE status = 'New'", one=True)["n"]
    recent = db.query("SELECT * FROM bookings ORDER BY id DESC LIMIT 8")
    return render_template("admin/dashboard.html", counts=counts, revenue=revenue,
                           new_enquiries=new_enquiries, customers=customers, recent=recent, statuses=BOOKING_STATUSES)


@bp.get("/bookings")
@login_required
def bookings():
    status, q = request.args.get("status", ""), request.args.get("q", "").strip()
    where, args = ["1 = 1"], []
    if status in BOOKING_STATUSES:
        where.append("status = ?")
        args.append(status)
    if q:
        where.append("(ref LIKE ? OR name LIKE ? OR phone LIKE ? OR email LIKE ?)")
        args += [f"%{q}%"] * 4
    rows = db.query(f"SELECT * FROM bookings WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 300", args)
    return render_template("admin/bookings.html", rows=rows, status=status, q=q, statuses=BOOKING_STATUSES)


@bp.get("/bookings/<int:booking_id>")
@login_required
def booking(booking_id):
    row = db.query("SELECT * FROM bookings WHERE id = ?", (booking_id,), one=True) or abort(404)
    payments = db.query("SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC", (booking_id,))
    return render_template("admin/booking.html", b=row, travellers=json.loads(row["travellers"]),
                           payments=payments, statuses=BOOKING_STATUSES)


@bp.post("/bookings/<int:booking_id>/status")
@login_required
def booking_status(booking_id):
    status = request.form.get("status", "")
    if status not in BOOKING_STATUSES:
        abort(400, "Unknown status.")
    db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    flash(f"Status changed to {status}.", "ok")
    return redirect(url_for("admin.booking", booking_id=booking_id))


@bp.get("/enquiries")
@login_required
def enquiries():
    rows = db.query("SELECT * FROM enquiries ORDER BY id DESC LIMIT 300")
    return render_template("admin/enquiries.html", rows=rows, statuses=ENQUIRY_STATUSES)


@bp.post("/enquiries/<int:enquiry_id>/status")
@login_required
def enquiry_status(enquiry_id):
    status = request.form.get("status", "")
    if status not in ENQUIRY_STATUSES:
        abort(400, "Unknown status.")
    db.execute("UPDATE enquiries SET status = ? WHERE id = ?", (status, enquiry_id))
    return redirect(url_for("admin.enquiries"))


# ---------------------------------------------------------------- packages
@bp.get("/packages")
@login_required
def packages():
    return render_template("admin/packages.html", items=catalog.all_packages())


def _images():
    folder = os.path.join(current_app.static_folder, "img")
    return sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png", ".avif", ".webp")))


def _parse_package(form, creating):
    """Validate the package form. Returns (values, errors)."""
    v = {
        "id": form.get("id", "").strip().lower(),
        "name": form.get("name", "").strip(),
        "dest_id": form.get("dest_id", ""),
        "days": form.get("days", ""), "nights": form.get("nights", ""), "price": form.get("price", ""),
        "cats": [c for c in form.getlist("cats") if c in CATEGORY_KEYS],
        "img": form.get("img", ""),
        "summary": form.get("summary", "").strip(),
        "highlights_text": form.get("highlights", ""),
        "itinerary_text": form.get("itinerary", ""),
        "featured": 1 if form.get("featured") else 0,
        "active": 1 if form.get("active") else 0,
    }
    errors = []
    if creating and not SLUG_RE.fullmatch(v["id"]):
        errors.append("ID must be 3 to 41 characters: lowercase letters, numbers and hyphens, for example goa-4d.")
    elif creating and catalog.get_package(v["id"], active_only=False):
        errors.append("A package with that ID already exists.")
    if not 3 <= len(v["name"]) <= 80:
        errors.append("Name must be 3 to 80 characters.")
    if not catalog.get_destination(v["dest_id"]):
        errors.append("Choose a destination.")
    for key, label, low, high in (("days", "Days", 1, 30), ("nights", "Nights", 0, 30), ("price", "Price", 500, 500000)):
        try:
            v[key] = int(v[key])
            if not low <= v[key] <= high:
                raise ValueError
        except ValueError:
            errors.append(f"{label} must be a number from {low} to {high}.")
    if v["img"] not in _images():
        errors.append("Choose an image from the list.")
    if len(v["summary"]) < 10:
        errors.append("Summary needs at least 10 characters.")
    v["highlights"] = parse_lines(v["highlights_text"])
    if not v["highlights"]:
        errors.append("Add at least one highlight, one per line.")
    v["itinerary"] = []
    for line in parse_lines(v["itinerary_text"]):
        title, _, text = line.partition("|")
        if not title.strip() or not text.strip():
            errors.append(f"Itinerary line needs the form Title | description: {line[:40]}")
            break
        v["itinerary"].append({"title": title.strip(), "text": text.strip()})
    if not v["itinerary"] and not any("Itinerary" in e for e in errors):
        errors.append("Add at least one itinerary day, one per line as Title | description.")
    return v, errors


def _form_page(values, errors, creating, code=200):
    return render_template("admin/package_form.html", v=values, errors=errors, creating=creating,
                           destinations=catalog.destinations(), images=_images(),
                           categories=CATEGORIES), code


@bp.route("/packages/new", methods=["GET", "POST"])
@login_required
def package_new():
    if request.method == "POST":
        v, errors = _parse_package(request.form, creating=True)
        if not errors:
            _save_package(v, creating=True)
            flash("Package created.", "ok")
            return redirect(url_for("admin.packages"))
        return _form_page(v, errors, True, 400)
    blank = {"id": "", "name": "", "dest_id": "", "days": 4, "nights": 3, "price": 10000, "cats": [],
             "img": "", "summary": "", "highlights_text": "", "itinerary_text": "", "featured": 0, "active": 1}
    return _form_page(blank, [], True)


@bp.route("/packages/<package_id>/edit", methods=["GET", "POST"])
@login_required
def package_edit(package_id):
    item = catalog.get_package(package_id, active_only=False) or abort(404)
    if request.method == "POST":
        v, errors = _parse_package(request.form, creating=False)
        v["id"] = package_id
        if not errors:
            _save_package(v, creating=False)
            flash("Package saved.", "ok")
            return redirect(url_for("admin.packages"))
        return _form_page(v, errors, False, 400)
    item["highlights_text"] = "\n".join(item["highlights"])
    item["itinerary_text"] = "\n".join(f"{d['title']} | {d['text']}" for d in item["itinerary"])
    return _form_page(item, [], False)


def _save_package(v, creating):
    cats, highlights, itinerary = db.cats_to_text(v["cats"]), json.dumps(v["highlights"]), json.dumps(v["itinerary"])
    if creating:
        db.execute("INSERT INTO packages (id, name, dest_id, days, nights, price, cats, img, summary, "
                   "highlights, itinerary, featured, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (v["id"], v["name"], v["dest_id"], v["days"], v["nights"], v["price"], cats, v["img"],
                    v["summary"], highlights, itinerary, v["featured"], v["active"]))
    else:
        db.execute("UPDATE packages SET name=?, dest_id=?, days=?, nights=?, price=?, cats=?, img=?, summary=?, "
                   "highlights=?, itinerary=?, featured=?, active=? WHERE id=?",
                   (v["name"], v["dest_id"], v["days"], v["nights"], v["price"], cats, v["img"], v["summary"],
                    highlights, itinerary, v["featured"], v["active"], v["id"]))
