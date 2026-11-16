-- NK Journeys database schema (SQLite). Money is stored in paise (1 rupee = 100 paise)
-- so that prices never suffer from floating point rounding.

CREATE TABLE IF NOT EXISTS destinations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    state       TEXT NOT NULL,
    cats        TEXT NOT NULL,              -- ",beaches,family," so LIKE '%,beaches,%' works
    img         TEXT NOT NULL,
    blurb       TEXT NOT NULL,
    best        TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS packages (
    id          TEXT PRIMARY KEY,           -- URL slug, for example kerala-6d
    name        TEXT NOT NULL,
    dest_id     TEXT NOT NULL REFERENCES destinations(id),
    days        INTEGER NOT NULL,
    nights      INTEGER NOT NULL,
    price       INTEGER NOT NULL,           -- rupees per adult
    cats        TEXT NOT NULL,
    img         TEXT NOT NULL,
    summary     TEXT NOT NULL,
    highlights  TEXT NOT NULL,              -- JSON list of strings
    itinerary   TEXT NOT NULL,              -- JSON list of {title, text}
    inclusions  TEXT,                       -- JSON list, NULL means use the defaults
    exclusions  TEXT,
    featured    INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone          TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ref           TEXT NOT NULL UNIQUE,     -- shown to the customer, for example NKJ123456
    token         TEXT NOT NULL UNIQUE,     -- long random value used in private URLs
    user_id       INTEGER REFERENCES users(id),   -- NULL for guest bookings
    package_id    TEXT NOT NULL REFERENCES packages(id),
    package_name  TEXT NOT NULL,            -- snapshot, so old bookings survive package edits
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    email         TEXT NOT NULL,
    city          TEXT NOT NULL DEFAULT '',
    travel_date   TEXT NOT NULL,            -- YYYY-MM-DD
    adults        INTEGER NOT NULL,
    children      INTEGER NOT NULL,
    travellers    TEXT NOT NULL,            -- JSON list of names, lead traveller first
    coupon        TEXT NOT NULL DEFAULT '',
    pay_mode      TEXT NOT NULL,            -- full or advance
    base          INTEGER NOT NULL,
    discount      INTEGER NOT NULL,
    gst           INTEGER NOT NULL,
    total         INTEGER NOT NULL,
    pay_now       INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Pending payment',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER NOT NULL REFERENCES bookings(id),
    payment_id  TEXT NOT NULL UNIQUE,
    method      TEXT NOT NULL,
    last4       TEXT NOT NULL DEFAULT '',   -- the only card detail we ever keep
    amount      INTEGER NOT NULL,
    status      TEXT NOT NULL,              -- Success or Failed
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enquiries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT NOT NULL DEFAULT '',
    trip        TEXT NOT NULL,
    travel_when TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'New',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admins (
    username       TEXT PRIMARY KEY,
    password_hash  TEXT NOT NULL
);
