"""Read-only queries for destinations and packages."""
import db
from helpers import CATEGORY_KEYS

BASE = "SELECT p.*, d.name AS dest_name FROM packages p JOIN destinations d ON d.id = p.dest_id"
SORTS = {
    "pop": "p.featured DESC, p.rowid",
    "lo": "p.price ASC",
    "hi": "p.price DESC",
    "dur": "p.days ASC, p.price ASC",
}


def get_package(package_id, active_only=True):
    sql = BASE + " WHERE p.id = ?" + (" AND p.active = 1" if active_only else "")
    row = db.query(sql, (package_id,), one=True)
    return db.row_to_package(row) if row else None


def search_packages(dest="", cat="", q="", sort="pop"):
    where, args = ["p.active = 1"], []
    if dest:
        where.append("p.dest_id = ?")
        args.append(dest)
    if cat in CATEGORY_KEYS:
        where.append("p.cats LIKE ?")
        args.append(f"%,{cat},%")
    if q:
        where.append("(p.name LIKE ? OR p.summary LIKE ? OR d.name LIKE ?)")
        args += [f"%{q}%"] * 3
    order = SORTS.get(sort, SORTS["pop"])      # whitelist, never user text
    rows = db.query(f"{BASE} WHERE {' AND '.join(where)} ORDER BY {order}", args)
    return [db.row_to_package(r) for r in rows]


def featured_packages(limit=3):
    rows = db.query(f"{BASE} WHERE p.active = 1 AND p.featured = 1 ORDER BY p.rowid LIMIT ?", (limit,))
    return [db.row_to_package(r) for r in rows]


def all_packages():
    rows = db.query(BASE + " ORDER BY p.rowid")
    return [db.row_to_package(r) for r in rows]


def destinations(cat="", q="", limit=None):
    where, args = ["1 = 1"], []
    if cat in CATEGORY_KEYS:
        where.append("cats LIKE ?")
        args.append(f"%,{cat},%")
    if q:
        where.append("(name LIKE ? OR state LIKE ? OR blurb LIKE ?)")
        args += [f"%{q}%"] * 3
    sql = f"SELECT * FROM destinations WHERE {' AND '.join(where)} ORDER BY sort_order"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query(sql, args)


def get_destination(dest_id):
    return db.query("SELECT * FROM destinations WHERE id = ?", (dest_id,), one=True)
