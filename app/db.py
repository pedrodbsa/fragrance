"""The SQLite database: one file, path from FRAGRANCE_DB.

Tables:
  products  current stock, one row per supplier + SKU. Sold-out items stay with qty 0.
  events    what changed between runs (new, restock, sold out, price change).
            notified_at is set once the notifier has handled the event.
  rules     what you care about: 'watch' rules alert you individually,
            'mute' rules hide items from the new-products digest.
"""

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    supplier    TEXT NOT NULL,
    sku         TEXT NOT NULL,
    name        TEXT NOT NULL,
    brand       TEXT NOT NULL,
    ean         TEXT,
    ean2        TEXT,
    ean3        TEXT,
    qty         INTEGER NOT NULL,
    price       REAL,
    flagged_new INTEGER NOT NULL DEFAULT 0,  -- the supplier's own "new" marker
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    PRIMARY KEY (supplier, sku)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    supplier    TEXT NOT NULL,
    sku         TEXT NOT NULL,
    kind        TEXT NOT NULL,  -- new | restock | soldout | price_drop | price_up
    old_value   REAL,
    new_value   REAL,
    created_at  TEXT NOT NULL,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS events_pending ON events (notified_at) WHERE notified_at IS NULL;

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY,
    action     TEXT NOT NULL,  -- watch | mute
    field      TEXT NOT NULL,  -- brand | ean | keyword | supplier
    value      TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ.get("FRAGRANCE_DB", "fragrance.db"))
    conn.row_factory = sqlite3.Row
    # WAL lets the backoffice read while a collector writes, and Litestream requires it.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn
