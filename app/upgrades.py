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
  same-name-brands  brands whose names match once capitals, accents and words like "Parfums"
                  or "Paris" are ignored ("Hermès" and "HERMES") become one, keeping the one
                  you chose for (else the oldest) and its status.
  drop-wholesale-fragrances  that shop is no longer collected (fragrances-wholesale has the
                  same products, cheaper): its listings count as sold out, quietly.
  forget-wholesale-fragrances  and then everything it left is deleted: its listings, their
                  recorded changes and price history, basket items, and its Suppliers row.
                  Fragrances only it listed go too, unless you put them on a list or own them.
  recorded-price  listings remember the price their last recorded price change was at, so
                  price changes count from there (today's price to start with).
  small-price-changes  price changes of €5 or less recorded before that rule are deleted.
  reread-names    the name reader learned "Parfum Unisex", "Parfum - Tester" and "Perfume":
                  every fragrance's listings are read again, and a fragrance whose listings
                  all read as a new name is renamed to it, or merged into the fragrance that
                  already has that name (decisions carry over, as with a merge by hand).
  learn-eans      a fragrance now learns every EAN of the listings matched to it by EAN:
                  the other EANs of those listings are matched to it too, unless already
                  matched to another fragrance.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app import brand_cleanup, brands
from app.brands import brand_for
from app.db import SCHEMA, now
from app.fragrances import find_or_create, identify, key, learn_eans, prune, rename


def upgrade(conn) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'products'").fetchone():
        once(conn, "listings", to_listings)
    once(conn, "brand-cleanup-1", brand_cleanup.apply)
    once(conn, "brand-reviewed", brand_reviewed)
    once(conn, "audience", audience)
    once(conn, "drop-wholesale-fragrances", drop_wholesale_fragrances)
    once(conn, "same-name-brands", same_name_brands)
    once(conn, "forget-wholesale-fragrances", forget_wholesale_fragrances)
    once(conn, "recorded-price", recorded_price)
    once(conn, "small-price-changes", small_price_changes)
    once(conn, "reread-names", reread_names)
    once(conn, "learn-eans", learn_pinned_eans)


def learn_pinned_eans(conn) -> None:
    """EANs matched before a fragrance learned all its listings' EANs: learn the rest now."""
    for pin in conn.execute("SELECT ean, fragrance_id FROM fragrance_eans").fetchall():
        learn_eans(conn, pin["fragrance_id"], pin["ean"])
    prune(conn)  # fragrances whose listings all moved, if left empty and undecided


def reread_names(conn) -> None:
    for fragrance in conn.execute("SELECT id, name FROM fragrances").fetchall():
        # Listings placed by an EAN you added stay put whatever their name says, so they don't count.
        readings = {identify(l["name"], l["brand"]) for l in conn.execute(
            """SELECT name, brand FROM listings WHERE fragrance_id = ?
               AND NOT EXISTS (SELECT 1 FROM fragrance_eans e WHERE e.ean IN (ean, ean2, ean3))""",
            (fragrance["id"],))}
        if len(readings) != 1:
            continue  # nothing to read, or listings you merged that read differently: left as they are
        name, concentration = readings.pop()
        already = conn.execute(
            "SELECT 1 FROM fragrance_names WHERE fragrance_id = ? AND name = ? AND concentration = ?",
            (fragrance["id"], key(name), concentration or "")).fetchone()
        if not already:
            rename(conn, fragrance["id"], name, concentration)
            print(f"upgrade: {fragrance['name']!r} now reads as {name!r} {concentration or ''}")


def small_price_changes(conn) -> None:
    conn.execute("DELETE FROM events WHERE kind IN ('price_drop', 'price_up') AND abs(new_value - old_value) <= 5")


def recorded_price(conn) -> None:
    if "recorded_price" not in {c["name"] for c in conn.execute("PRAGMA table_info(listings)")}:
        conn.execute("ALTER TABLE listings ADD COLUMN recorded_price REAL")
    conn.execute("UPDATE listings SET recorded_price = price")


def forget_wholesale_fragrances(conn) -> None:
    for table, column in (("events", "supplier"), ("basket", "supplier"), ("listings", "supplier"), ("suppliers", "name")):
        conn.execute(f"DELETE FROM {table} WHERE {column} = 'wholesale-fragrances'")
    prune(conn)


def same_name_brands(conn) -> None:
    groups = {}
    for b in conn.execute("SELECT * FROM brands ORDER BY reviewed_at IS NULL, status = 'default', id"):
        groups.setdefault(brands.key(b["name"]), []).append(b)
    for keep, *others in groups.values():
        for other in others:
            brands.merge(conn, other["id"], keep["id"])
            print(f"upgrade: brand {other['name']!r} merged into {keep['name']!r}")


def drop_wholesale_fragrances(conn) -> None:
    conn.execute("UPDATE listings SET qty = 0 WHERE supplier = 'wholesale-fragrances'")


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
