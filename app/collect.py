"""Collect one supplier: fetch its current stock and record what changed since the last run.

The first run for a supplier only records the baseline, so it doesn't report its whole
catalogue as new. Quantity changes update the product but aren't events: they happen
constantly and would drown the ones that matter.
"""

from collections import Counter
from datetime import datetime, timezone

from app.db import connect
from app.item import Item
from app.suppliers import SUPPLIERS

UPSERT = """
INSERT INTO products (supplier, sku, name, brand, ean, ean2, ean3, qty, price, flagged_new, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (supplier, sku) DO UPDATE SET
  name = excluded.name, brand = excluded.brand, ean = excluded.ean, ean2 = excluded.ean2,
  ean3 = excluded.ean3, qty = excluded.qty, price = excluded.price,
  flagged_new = excluded.flagged_new, last_seen = excluded.last_seen
"""


def collect(supplier: str) -> None:
    items = SUPPLIERS[supplier]()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = connect()
    with conn:  # one transaction: a run is recorded completely or not at all
        events = record(conn, supplier, items, now)
    counts = ", ".join(f"{n} {kind}" for kind, n in Counter(e[1] for e in events).items()) or "no changes"
    print(f"{supplier}: {len(items)} in stock; {counts}")


def record(conn, supplier: str, items: list[Item], now: str) -> list[tuple]:
    """Write the new stock and its events; return the events as (sku, kind, old, new)."""
    known = {row["sku"]: row for row in conn.execute("SELECT * FROM products WHERE supplier = ?", (supplier,))}
    baseline = not known
    events = []

    for item in items:
        old = known.pop(item.sku, None)
        if old is None and not baseline:
            events.append((item.sku, "new", None, item.price))
        if old is not None:
            events += [(item.sku, *change) for change in changes(old, item)]
        conn.execute(UPSERT, (supplier, item.sku, item.name, item.brand, item.ean, item.ean2, item.ean3,
                              item.qty, item.price, item.flagged_new, now, now))

    # Whatever we knew about but the supplier no longer lists has sold out.
    for sku, old in known.items():
        if old["qty"] > 0:
            conn.execute("UPDATE products SET qty = 0 WHERE supplier = ? AND sku = ?", (supplier, sku))
            events.append((sku, "soldout", old["qty"], 0))

    conn.executemany(
        "INSERT INTO events (supplier, sku, kind, old_value, new_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(supplier, *event, now) for event in events],
    )
    return events


def changes(old, item: Item) -> list[tuple]:
    """Events between a product's last known state and its current listing, as (kind, old, new)."""
    found = []
    if old["qty"] == 0 and item.qty > 0:
        found.append(("restock", 0, item.qty))
    if old["price"] is not None and item.price < old["price"]:
        found.append(("price_drop", old["price"], item.price))
    if old["price"] is not None and item.price > old["price"]:
        found.append(("price_up", old["price"], item.price))
    return found
