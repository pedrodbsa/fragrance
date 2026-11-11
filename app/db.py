"""The SQLite database: one file, path from FRAGRANCE_DB.

Tables:
  products       current stock, one row per supplier + SKU. Sold-out items stay with qty 0.
                 `brand` is the supplier's own spelling.
  events         what changed between runs (new, restock, sold out, price change).
                 notified_at is set once the notifier has handled the event.
  brands         one row per real brand, with your decision about it: follow | ignore |
                 default (app/brands.py). announced_at is set once a new brand has been
                 offered in the digest.
  brand_aliases  every supplier spelling of a brand ("YSL", "YVES SAINT LAURENT"), so
                 products from all suppliers land on the same brand.
  fragrances     your decisions about single fragrances: follow | ignore | default, and
                 whether it's in your collection (owned). brand_id NULL means any brand;
                 concentration NULL means any concentration (app/fragrances.py).
  fragrance_aliases  names you merged into another fragrance of the same brand: listings read
                 as `name` count as `into_name` (same juice, different spelling or EAN).

View:
  catalog        products joined with their brand: adds brand_id, brand_name, status.
"""

import os
import sqlite3
from datetime import datetime, timezone

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

CREATE TABLE IF NOT EXISTS brands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids never reused: old Telegram buttons stay safe
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'default',  -- follow | ignore | default
    created_at   TEXT NOT NULL,
    announced_at TEXT
);

CREATE TABLE IF NOT EXISTS brand_aliases (
    alias    TEXT PRIMARY KEY COLLATE NOCASE,
    brand_id INTEGER NOT NULL REFERENCES brands (id)
);

CREATE TABLE IF NOT EXISTS fragrances (
    id            INTEGER PRIMARY KEY,
    brand_id      INTEGER REFERENCES brands (id),
    name          TEXT NOT NULL,      -- as read from supplier names, e.g. "BEACH HUT MAN"
    concentration TEXT,               -- EDP | EDT | EDC | Parfum | Extrait | Cologne
    status        TEXT NOT NULL,      -- follow | ignore | default
    owned         INTEGER NOT NULL DEFAULT 0,  -- in your collection
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fragrance_aliases (
    brand_id           INTEGER NOT NULL REFERENCES brands (id),
    name               TEXT NOT NULL,     -- as read from listings, e.g. "AVENTUS EAU DE PARFUM"
    concentration      TEXT NOT NULL,     -- '' when none
    into_name          TEXT NOT NULL,     -- the fragrance it's the same juice as
    into_concentration TEXT NOT NULL,
    PRIMARY KEY (brand_id, name, concentration)
);

CREATE VIEW IF NOT EXISTS catalog AS
SELECT p.*, b.id AS brand_id, b.name AS brand_name, b.status
FROM products p
JOIN brand_aliases a ON a.alias = p.brand
JOIN brands b ON b.id = a.brand_id;
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ.get("FRAGRANCE_DB", "fragrance.db"))
    conn.row_factory = sqlite3.Row
    # WAL lets the backoffice read while a collector writes, and Litestream requires it.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


def add_brand(conn, spelling: str, announced: bool) -> int:
    """Create a brand from a supplier spelling, on default. Returns its id.

    announced=True leaves it out of the digest, for bulk arrivals (a supplier's first run).
    """
    stamp = now()
    brand_id = conn.execute(
        "INSERT INTO brands (name, status, created_at, announced_at) VALUES (?, 'default', ?, ?)",
        (spelling, stamp, stamp if announced else None),
    ).lastrowid
    conn.execute("INSERT INTO brand_aliases (alias, brand_id) VALUES (?, ?)", (spelling, brand_id))
    return brand_id


def unknown_spellings(conn) -> list[str]:
    """Brand spellings in products that no brand claims yet."""
    return [r[0] for r in conn.execute(
        """SELECT min(brand) FROM products
           WHERE brand COLLATE NOCASE NOT IN (SELECT alias FROM brand_aliases)
           GROUP BY brand COLLATE NOCASE"""
    )]


def upgrade(conn) -> None:
    """Brings an older database up to date. Safe to run any number of times.

    - Every brand already in stock is added on default, without a digest mention.
    - Browse and triage statuses became default; fragrance want -> follow, own -> owned.
    - The old rules table is converted, then dropped:
        brand watch -> brand Follow, brand mute -> default,
        EAN or keyword watch -> fragrance Follow; supplier and other mute rules are dropped.
    """
    from app.fragrances import identify, save  # here, not at the top: fragrances builds on this module

    with conn:
        for spelling in unknown_spellings(conn):
            add_brand(conn, spelling, announced=True)
        if "owned" not in [c["name"] for c in conn.execute("PRAGMA table_info(fragrances)")]:
            conn.execute("ALTER TABLE fragrances ADD COLUMN owned INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE brands SET status = 'default' WHERE status IN ('browse', 'new')")
        conn.execute("UPDATE fragrances SET owned = 1, status = 'default' WHERE status = 'own'")
        conn.execute("UPDATE fragrances SET status = 'follow' WHERE status = 'want'")
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'rules'").fetchone():
            return
        for action, status in (("watch", "follow"), ("mute", "default")):
            conn.execute(
                """UPDATE brands SET status = ? WHERE id IN (
                     SELECT a.brand_id FROM brand_aliases a JOIN rules r ON a.alias = r.value
                     WHERE r.field = 'brand' AND r.action = ?)""",
                (status, action),
            )
        for rule in conn.execute("SELECT * FROM rules WHERE action = 'watch' AND field IN ('ean', 'keyword')").fetchall():
            if rule["field"] == "keyword":
                save(conn, None, rule["value"], None, "follow", note=rule["note"])
                continue
            listing = conn.execute("SELECT * FROM catalog WHERE ? IN (ean, ean2, ean3)", (rule["value"],)).fetchone()
            if listing:
                name, concentration = identify(listing["name"], listing["brand"])
                save(conn, listing["brand_id"], name, concentration, "follow", note=rule["note"])
        conn.execute("DROP TABLE rules")
