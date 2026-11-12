"""The SQLite database: one file, path from DATABASE_PATH.

Tables:
  suppliers         one row per supplier: its minimum order value (set on the Suppliers
                    page) and how its last collection went.
  brands            one row per real brand, with your decision about it: favourite |
                    follow | none (unfollowed) (app/brands.py). announced_at is set once a new
                    brand has been offered in the digest; reviewed_at once you've chosen.
  brand_aliases     every supplier spelling of a brand ("YSL", "YVES SAINT LAURENT"), so
                    listings from all suppliers land on the same brand.
  fragrances        the catalogue: every fragrance (the juice: brand + name + concentration),
                    whether or not a supplier lists it now, with your decisions about it:
                    its list (wishlist | filler | ignore | default), whether it's in your
                    collection (owned), the size you'd buy, and who it's for (audience:
                    from suppliers, correctable on its page) (app/fragrances.py).
  fragrance_names   how listings name a fragrance: the name and concentration read from a
                    supplier's product name -> the fragrance it is. Merging two fragrances
                    points one's names at the other, so later listings land right too.
  fragrance_eans    EANs you added to a fragrance: listings with one of them belong to it,
                    whatever their name says, now and when they appear later.
  not_same          pairs of fragrances you said aren't the same juice, so the Merges page
                    stops suggesting them.
  listings          what suppliers offer: one row per supplier + SKU, sold-out ones kept
                    with qty 0. `name` and `brand` are as the supplier writes them;
                    fragrance_id is worked out once, when the listing first appears.
  events            what changed between runs (new, restock, sold out, price change).
                    notified_at is set once the notifier has handled the event.
  basket            what you're gathering to order, per supplier (app/baskets.py). Items stay
                    when they sell out.
  upgrades          one-time data changes already applied, so they run once (app/upgrades.py).

View:
  catalog           listings with their fragrance and brand, and the two answers most pages
                    need: whether a listing alerts you, and whether it's hidden.
"""

import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    name        TEXT PRIMARY KEY,   -- as in app/suppliers, e.g. "nunu"
    mov         REAL,               -- minimum order value in €, same basis as its prices
    last_run_at TEXT,               -- last collection attempt
    last_ok_at  TEXT,               -- last collection that worked
    last_count  INTEGER,            -- items in stock at that collection
    last_error  TEXT                -- why the last attempt failed; NULL when it worked
);

CREATE TABLE IF NOT EXISTS brands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids never reused: old Telegram buttons stay safe
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'follow',  -- favourite | follow | none
    created_at   TEXT NOT NULL,
    announced_at TEXT,
    reviewed_at  TEXT                -- when you first chose Favourite, Follow or Unfollow; NULL = new
);

CREATE TABLE IF NOT EXISTS brand_aliases (
    alias    TEXT PRIMARY KEY COLLATE NOCASE,
    brand_id INTEGER NOT NULL REFERENCES brands (id)
);

CREATE TABLE IF NOT EXISTS fragrances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id      INTEGER NOT NULL REFERENCES brands (id),
    name          TEXT NOT NULL,      -- as read from supplier names, e.g. "BEACH HUT MAN"
    concentration TEXT,               -- EDP | EDT | EDC | Parfum | Extrait | Cologne, or none
    status        TEXT NOT NULL DEFAULT 'default',  -- wishlist | filler | ignore | default
    owned         INTEGER NOT NULL DEFAULT 0,       -- in your collection
    size          TEXT,               -- size you'd buy, as shown in Stock ("100 ml"), tester or not
    audience      TEXT,               -- man | woman | unisex: the first supplier to say, or you
    note          TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fragrances_brand ON fragrances (brand_id);

CREATE TABLE IF NOT EXISTS fragrance_names (
    brand_id      INTEGER NOT NULL REFERENCES brands (id),
    name          TEXT NOT NULL,      -- comparable form (fragrances.key), e.g. "BEACH HUT MAN"
    concentration TEXT NOT NULL,      -- '' when none
    fragrance_id  INTEGER NOT NULL REFERENCES fragrances (id),
    PRIMARY KEY (brand_id, name, concentration)
);
CREATE INDEX IF NOT EXISTS fragrance_names_fragrance ON fragrance_names (fragrance_id);

CREATE TABLE IF NOT EXISTS fragrance_eans (
    ean          TEXT PRIMARY KEY,
    fragrance_id INTEGER NOT NULL REFERENCES fragrances (id),
    added_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fragrance_eans_fragrance ON fragrance_eans (fragrance_id);

CREATE TABLE IF NOT EXISTS not_same (
    fragrance_id INTEGER NOT NULL,    -- the lower id of the two
    other_id     INTEGER NOT NULL,
    PRIMARY KEY (fragrance_id, other_id)
);

CREATE TABLE IF NOT EXISTS listings (
    supplier     TEXT NOT NULL REFERENCES suppliers (name),
    sku          TEXT NOT NULL,
    name         TEXT NOT NULL,
    brand        TEXT NOT NULL,       -- the supplier's spelling
    ean          TEXT,
    ean2         TEXT,
    ean3         TEXT,
    qty          INTEGER NOT NULL,
    price        REAL,
    recorded_price REAL,              -- the price at the last recorded price change (or when first seen)
    flagged_new  INTEGER NOT NULL DEFAULT 0,  -- the supplier's own "new" marker
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    fragrance_id INTEGER NOT NULL REFERENCES fragrances (id),
    PRIMARY KEY (supplier, sku)
);
CREATE INDEX IF NOT EXISTS listings_fragrance ON listings (fragrance_id);

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
CREATE INDEX IF NOT EXISTS events_listing ON events (supplier, sku);

CREATE TABLE IF NOT EXISTS basket (
    supplier    TEXT NOT NULL,
    sku         TEXT NOT NULL,        -- the listing: one supplier's size of a fragrance
    quantity    INTEGER NOT NULL DEFAULT 1,
    added_at    TEXT NOT NULL,
    added_price REAL,                 -- its price when you added it
    PRIMARY KEY (supplier, sku)
);

CREATE TABLE IF NOT EXISTS upgrades (
    name       TEXT PRIMARY KEY,    -- e.g. "brand-cleanup-1"
    applied_at TEXT NOT NULL
);

-- A fragrance on a list decides for itself; one on no list ('default') follows its brand.
CREATE VIEW IF NOT EXISTS catalog AS
SELECT l.*, f.brand_id, b.name AS brand_name, b.status AS brand_status,
       f.name AS fragrance, f.concentration, f.status AS fragrance_status, f.owned, f.size AS buy_size, f.audience,
       CASE WHEN f.status != 'default' THEN f.status = 'wishlist' ELSE b.status = 'favourite' END AS alerting,
       CASE WHEN f.status != 'default' THEN f.status = 'ignore' ELSE b.status = 'none' END AS hidden
FROM listings l
JOIN fragrances f ON f.id = l.fragrance_id
JOIN brands b ON b.id = f.brand_id;
"""


def fold(text: str | None) -> str:
    """Searchable form of a name: no accents, lower case, letters and digits only.
    "Lancôme L'Homme No.5" -> "lancomelhommeno5". SQL gets it as fold(...)."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ.get("DATABASE_PATH", "fragrance.db"))
    conn.row_factory = sqlite3.Row
    # WAL lets the backoffice read while a collector writes, and Litestream requires it.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.create_function("fold", 1, fold, deterministic=True)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'products'").fetchone():
        conn.executescript(SCHEMA)  # an older database gets these from app/upgrades.py instead
    return conn


def add_brand(conn, spelling: str, announced: bool) -> int:
    """Create a brand from a supplier spelling, on Follow. Returns its id.

    announced=True leaves it out of the digest, for bulk arrivals (a supplier's first run).
    """
    stamp = now()
    brand_id = conn.execute(
        "INSERT INTO brands (name, status, created_at, announced_at) VALUES (?, 'follow', ?, ?)",
        (spelling, stamp, stamp if announced else None),
    ).lastrowid
    conn.execute("INSERT INTO brand_aliases (alias, brand_id) VALUES (?, ?)", (spelling, brand_id))
    return brand_id


def collected(conn, supplier: str, count: int, stamp: str) -> None:
    """Note that a supplier's collection worked."""
    conn.execute(
        """INSERT INTO suppliers (name, last_run_at, last_ok_at, last_count) VALUES (?, ?, ?, ?)
           ON CONFLICT (name) DO UPDATE SET last_run_at = excluded.last_run_at,
             last_ok_at = excluded.last_ok_at, last_count = excluded.last_count, last_error = NULL""",
        (supplier, stamp, stamp, count))


def collection_failed(conn, supplier: str, error: str) -> None:
    """Note that a supplier's collection failed, and why."""
    conn.execute(
        """INSERT INTO suppliers (name, last_run_at, last_error) VALUES (?, ?, ?)
           ON CONFLICT (name) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = excluded.last_error""",
        (supplier, now(), error))
