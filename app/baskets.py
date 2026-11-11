"""Baskets: one open basket per supplier, filled as you find things, until you place the order.

A basket holds listings (a supplier's size of a fragrance) and how many bottles you want.
Items stay when they sell out: the Orders page greys them and leaves them out of the total,
and the digest tells you when a basket item sells out, comes back or changes price.
"""

from app.db import now
from app.fragrances import variant


def add(conn, supplier: str, sku: str) -> None:
    """Put a listing in its supplier's basket (one bottle), remembering today's price."""
    conn.execute(
        """INSERT OR IGNORE INTO basket (supplier, sku, quantity, added_at, added_price)
           SELECT supplier, sku, 1, ?, price FROM listings WHERE supplier = ? AND sku = ?""",
        (now(), supplier, sku))


def remove(conn, supplier: str, sku: str) -> None:
    conn.execute("DELETE FROM basket WHERE supplier = ? AND sku = ?", (supplier, sku))


def set_quantity(conn, supplier: str, sku: str, quantity: int) -> None:
    """How many bottles you want; 0 takes it out."""
    if quantity <= 0:
        remove(conn, supplier, sku)
    else:
        conn.execute("UPDATE basket SET quantity = ? WHERE supplier = ? AND sku = ?", (quantity, supplier, sku))


def empty(conn, supplier: str) -> None:
    """The order is placed: start a fresh basket."""
    conn.execute("DELETE FROM basket WHERE supplier = ?", (supplier,))


def contents(conn) -> list[dict]:
    """Every open basket: its items as they stand now, and the total of what's in stock."""
    movs = {s["name"]: s["mov"] for s in conn.execute("SELECT name, mov FROM suppliers")}
    baskets = {}
    for item in conn.execute(
            """SELECT c.*, b.quantity, b.added_at, b.added_price FROM basket b
               JOIN catalog c ON c.supplier = b.supplier AND c.sku = b.sku
               ORDER BY b.supplier, c.brand_name, c.fragrance""").fetchall():
        line = {**dict(item), "size_label": variant(item["name"])[1],
                "available": item["qty"] > 0 and item["price"] is not None}
        basket = baskets.setdefault(item["supplier"], {"supplier": item["supplier"], "mov": movs.get(item["supplier"]),
                                                       "items": [], "total": 0.0})
        basket["items"].append(line)
        if line["available"]:
            basket["total"] += item["price"] * min(item["quantity"], item["qty"])
    return list(baskets.values())


def keys(conn) -> set[tuple[str, str]]:
    """(supplier, sku) of everything in a basket, to mark it elsewhere."""
    return {(r["supplier"], r["sku"]) for r in conn.execute("SELECT supplier, sku FROM basket")}
