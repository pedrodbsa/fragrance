"""Brings an older database up to date when the app or a schedule starts. Each step runs once.

  listings        the old layout (a `products` table whose brand and fragrance were worked out
                  on every page load) becomes listings pointing to a fragrance catalogue. Your
                  fragrance decisions and merges carry over.
  brand-cleanup-1 brand names tidied and duplicate spellings merged (app/brand_cleanup.py).
  audience        fragrances remember who they're for (man | woman | unisex); filled in by
                  the next collection.
  brand-reviewed  brands remember whether you've chosen for them yet. Followed and ignored
                  ones count as chosen, and so do default ones older than 30 days (the old
                  New brands page no longer showed them).
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app import brand_cleanup
from app.db import SCHEMA, brand_for, now
from app.fragrances import find_or_create, identify, key


def upgrade(conn) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'products'").fetchone():
        once(conn, "listings", to_listings)
    once(conn, "brand-cleanup-1", brand_cleanup.apply)
    once(conn, "brand-reviewed", brand_reviewed)
    once(conn, "audience", audience)


def audience(conn) -> None:
    if "audience" not in {c["name"] for c in conn.execute("PRAGMA table_info(fragrances)")}:
        conn.execute("ALTER TABLE fragrances ADD COLUMN audience TEXT")
    conn.execute("DROP VIEW IF EXISTS catalog")  # recreated with the new column
    for statement in statements(SCHEMA):
        if "CREATE VIEW" in statement:
            conn.execute(statement)


def brand_reviewed(conn) -> None:
    if "reviewed_at" not in {c["name"] for c in conn.execute("PRAGMA table_info(brands)")}:
        conn.execute("ALTER TABLE brands ADD COLUMN reviewed_at TEXT")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    conn.execute("UPDATE brands SET reviewed_at = ? WHERE status != 'default' OR created_at < ?", (now(), month_ago))


def once(conn, name: str, step) -> None:
    """Run a step in one transaction, unless it already ran: half an upgrade never sticks."""
    conn.execute("BEGIN")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS upgrades (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        if not conn.execute("SELECT 1 FROM upgrades WHERE name = ?", (name,)).fetchone():
            step(conn)
            conn.execute("INSERT INTO upgrades VALUES (?, ?)", (name, now()))
            print(f"upgrade: {name} applied")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def statements(script: str):
    """The statements of a SQL script, to run them inside a transaction (executescript can't)."""
    current = ""
    for line in script.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            yield current
            current = ""


def to_listings(conn) -> None:
    conn.execute("ALTER TABLE fragrances RENAME TO old_fragrances")
    conn.execute("DROP VIEW catalog")
    for statement in statements(SCHEMA):
        conn.execute(statement)

    # Earlier merges: a name read from listings -> the fragrance name it counts as.
    merged = {(a["brand_id"], a["name"], a["concentration"]): (a["into_name"], a["into_concentration"] or None)
              for a in conn.execute("SELECT * FROM fragrance_aliases")}

    def juice(brand_id, name, concentration):
        for _ in range(10):  # merges of merges; the cap guards against a loop
            target = merged.get((brand_id, key(name), concentration or ""))
            if target is None:
                break
            name, concentration = target
        return name, concentration

    for p in conn.execute("SELECT * FROM products").fetchall():
        brand_id = brand_for(conn, p["brand"], announced=True)
        read = identify(p["name"], p["brand"])
        fragrance_id = find_or_create(conn, brand_id, *juice(brand_id, *read))
        conn.execute("INSERT OR IGNORE INTO fragrance_names VALUES (?, ?, ?, ?)",
                     (brand_id, key(read[0]), read[1] or "", fragrance_id))
        conn.execute(
            """INSERT INTO listings (supplier, sku, name, brand, ean, ean2, ean3, qty, price, flagged_new,
                                     first_seen, last_seen, fragrance_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["supplier"], p["sku"], p["name"], p["brand"], p["ean"], p["ean2"], p["ean3"], p["qty"], p["price"],
             p["flagged_new"], p["first_seen"], p["last_seen"], fragrance_id))

    # Decisions: a concentration left empty covered every concentration of that name.
    for d in conn.execute("SELECT * FROM old_fragrances").fetchall():
        if d["brand_id"] is None:
            print(f"upgrade: dropped '{d['name']}' (any brand): add it again with its brand")
            continue
        ids = [r["fragrance_id"] for r in conn.execute(
            "SELECT DISTINCT fragrance_id FROM fragrance_names WHERE brand_id = ? AND name = ? AND (? IS NULL OR concentration = ?)",
            (d["brand_id"], key(d["name"]), d["concentration"], d["concentration"]))]
        for fragrance_id in ids or [find_or_create(conn, d["brand_id"], d["name"], d["concentration"])]:
            conn.execute("UPDATE fragrances SET status = ?, owned = ?, note = ?, size = ? WHERE id = ?",
                         (d["status"], d["owned"], d["note"], d["size"], fragrance_id))

    for table in ("products", "old_fragrances", "fragrance_aliases"):
        conn.execute(f"DROP TABLE {table}")
