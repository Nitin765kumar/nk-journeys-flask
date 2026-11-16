"""Database helpers: connection, schema, seed data and the admin account."""
import json
import os
import secrets
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash

HERE = os.path.dirname(__file__)
SCHEMA = os.path.join(HERE, "schema.sql")
SEED = os.path.join(HERE, "data", "seed.json")


def get_db():
    """One connection per request, closed automatically at the end."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    rows = get_db().execute(sql, args).fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    db = get_db()
    cursor = db.execute(sql, args)
    db.commit()
    return cursor.lastrowid


def cats_to_text(cats):
    return "," + ",".join(cats) + "," if cats else ","


def cats_from_text(text):
    return [c for c in text.split(",") if c]


def row_to_package(row):
    """Turn a packages row (with JSON text columns) into a plain dict."""
    package = dict(row)
    package["cats"] = cats_from_text(package["cats"])
    package["highlights"] = json.loads(package["highlights"])
    package["itinerary"] = json.loads(package["itinerary"])
    for key in ("inclusions", "exclusions"):
        package[key] = json.loads(package[key]) if package.get(key) else None
    return package


def init_db(app):
    """Create tables, load the sample data the first time, and make sure an admin exists."""
    path = app.config["DATABASE_PATH"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    _migrate(conn)
    _seed(conn)
    _ensure_admin(conn, app)
    conn.commit()
    conn.close()


def _migrate(conn):
    """Bring a database created by an older version up to date."""
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(bookings)")]
    if "user_id" not in columns:
        conn.execute("ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id)")


def _seed(conn):
    with open(SEED, encoding="utf-8") as f:
        seed = json.load(f)
    if not conn.execute("SELECT 1 FROM destinations").fetchone():
        for d in seed["destinations"]:
            conn.execute(
                "INSERT INTO destinations (id, name, state, cats, img, blurb, best, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (d["id"], d["name"], d["state"], cats_to_text(d["cats"]), d["img"],
                 d["blurb"], d["best"], d["sort_order"]),
            )
    if not conn.execute("SELECT 1 FROM packages").fetchone():
        for p in seed["packages"]:
            conn.execute(
                "INSERT INTO packages (id, name, dest_id, days, nights, price, cats, img, summary, "
                "highlights, itinerary, featured) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["id"], p["name"], p["dest_id"], p["days"], p["nights"], p["price"],
                 cats_to_text(p["cats"]), p["img"], p["summary"], json.dumps(p["highlights"]),
                 json.dumps(p["itinerary"]), int(p["featured"])),
            )


def _ensure_admin(conn, app):
    username = app.config["ADMIN_USERNAME"]
    password = app.config.get("ADMIN_PASSWORD")
    exists = conn.execute("SELECT 1 FROM admins WHERE username = ?", (username,)).fetchone()
    if password:
        # Changing ADMIN_PASSWORD in the environment updates the stored hash on next start.
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?) "
            "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash",
            (username, generate_password_hash(password)),
        )
    elif not exists:
        password = secrets.token_urlsafe(9)
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        print(f"[NK Journeys] No ADMIN_PASSWORD set. Generated admin login -> {username} / {password}", flush=True)
