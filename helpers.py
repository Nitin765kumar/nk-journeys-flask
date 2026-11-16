"""Constants, template filters and small utilities shared by the app and the admin."""
import re
import secrets
from datetime import date

import db

CATEGORIES = [
    ("mountains", "Mountains"), ("beaches", "Beaches"), ("heritage", "Heritage"),
    ("spiritual", "Spiritual"), ("honeymoon", "Honeymoon"), ("family", "Family"),
]
CATEGORY_KEYS = {key for key, _ in CATEGORIES}

DEFAULT_INCLUSIONS = [
    "Hotel stays on twin sharing with breakfast",
    "Private AC vehicle for transfers and sightseeing",
    "Airport or station pickup and drop",
    "Local guide where mentioned in the itinerary",
    "Driver charges, tolls and parking",
]
DEFAULT_EXCLUSIONS = [
    "Flights or train tickets to the starting city",
    "Lunch and dinner unless mentioned",
    "Entry tickets and personal expenses",
    "Travel insurance",
    "Anything not listed under inclusions",
]

BOOKING_STATUSES = ["Pending payment", "Confirmed", "Completed", "Cancelled"]
ENQUIRY_STATUSES = ["New", "In progress", "Closed"]

PHONE_RE = re.compile(r"[6-9]\d{9}")
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


# ---------- formatting (registered as Jinja filters) ----------
def indian(number):
    """1234567 -> 12,34,567 (Indian digit grouping)."""
    digits = str(number)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def inr(paise):
    rupees, rest = divmod(int(paise), 100)
    return "₹" + indian(rupees) + (f".{rest:02d}" if rest else "")


def inr_rupees(rupees):
    return inr(int(rupees) * 100)


def fmt_date(text):
    d = date.fromisoformat(str(text)[:10])
    return f"{d.day} {d:%b} {d.year}"


def fmt_datetime(text):
    d = date.fromisoformat(str(text)[:10])
    return f"{d.day} {d:%b} {d.year}, {str(text)[11:16]}"


# ---------- small utilities ----------
def new_ref(prefix, digits, table):
    """A short, human-friendly reference such as NKJ123456 that is not used yet."""
    while True:
        ref = prefix + "".join(secrets.choice("0123456789") for _ in range(digits))
        if not db.query(f"SELECT 1 FROM {table} WHERE ref = ?", (ref,), one=True):
            return ref


def clamp_int(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def parse_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]
