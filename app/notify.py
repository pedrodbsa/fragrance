"""The digest: one Telegram message per collection window, sent only if something changed.

Sections:
  ⚠️ suppliers whose collection failed this window
  🧺 Baskets: items in one of your baskets that sold out, came back, or changed price
  ⭐ Wishlist and favourites: product changes as on the Changes page, one entry per fragrance
     across all suppliers. Wishlist fragrances: new, back in stock, or a lower 👑 best price per
     ml; favourite brands' fragrances: new or back in stock (except ones you ignored or marked
     as filler). One supplier restocking a fragrance others already had isn't a change.
  🆕 New brands: each one comes as its own message with a Favourite button (and
     "Same as …" when it looks like a brand you have). Not tapping leaves it on Follow:
     shown in Stock, no alerts. When many arrive at once, the digest links to the New
     brands page instead.
Brands you don't follow, ignored fragrances and fillers never appear. Everything else (followed brands, sold out,
price up) is recorded for the backoffice but not sent.
"""

import os
from html import escape

from app import changes, telegram
from app.brands import suggestions
from app.db import connect, now
from app.fragrances import pretty_name

WISHLIST_KINDS = ("new", "restock", "price_drop")
FAVOURITE_BRAND_KINDS = ("new", "restock")
DIGEST_MAX = 60  # fragrances; beyond this the message lists a count; the backoffice has the full list
LABELS = {"new": "New", "restock": "Back in stock", "price_drop": "Price drop"}

# Each fragrance's name and whether its changes alert: wishlist, or on no list and a favourite brand.
FRAGRANCES = """
SELECT f.id, f.name, f.concentration, f.status, b.name AS brand_name,
       CASE WHEN f.status != 'default' THEN f.status = 'wishlist' ELSE b.status = 'favourite' END AS alerting
FROM fragrances f JOIN brands b ON b.id = f.brand_id
"""
OFFER_MAX = 8    # more new brands than this go to the Brands page's New tab instead of one message each

PENDING = """
SELECT e.id, e.kind, e.old_value, e.new_value, e.created_at AS event_at, c.*,
       EXISTS (SELECT 1 FROM basket b WHERE b.supplier = e.supplier AND b.sku = e.sku) AS in_basket
FROM events e JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku
WHERE e.notified_at IS NULL ORDER BY c.brand_name, c.name
"""


def notify(failed: list[str]) -> None:
    conn = connect()
    pending = conn.execute(PENDING).fetchall()
    basket = [e for e in pending if e["in_basket"]]  # every change to a basket item matters
    followed = favourites(conn, pending)
    new_brands = conn.execute(
        "SELECT * FROM brands WHERE status = 'follow' AND announced_at IS NULL ORDER BY name").fetchall()

    digest = compose(failed, basket, followed, new_brands)
    if digest:
        telegram.send(digest)
    if len(new_brands) <= OFFER_MAX:
        hints = suggestions(conn)
        for brand in new_brands:
            telegram.send(*offer(conn, brand, hints.get(brand["id"], [])))

    stamp = now()
    with conn:
        conn.executemany("UPDATE events SET notified_at = ? WHERE id = ?", [(stamp, e["id"]) for e in pending])
        conn.executemany("UPDATE brands SET announced_at = ? WHERE id = ?", [(stamp, b["id"]) for b in new_brands])
    print(f"notify: {len(pending)} events, {len(basket)} basket, {len(followed)} followed, {len(new_brands)} new brands, "
          f"{len(failed)} failed{'' if digest else '; nothing to send'}")


def favourites(conn, pending) -> list[dict]:
    """The product changes (app/changes.py) the pending supplier events caused, for wishlist
    fragrances and favourite brands, grouped per fragrance: [{"product", "changes"}], by brand
    and name, each fragrance's changes oldest first."""
    runs = {(e["event_at"], e["supplier"]) for e in pending}
    products = {r["id"]: r for r in conn.execute(FRAGRANCES)}
    grouped = {}
    for c in reversed(changes.replay(conn)):  # replay is newest first
        p = products.get(c["fragrance_id"])
        if (c["created_at"], c["supplier"]) in runs and p and alerts(p, c["kind"]):
            grouped.setdefault(p["id"], {"product": p, "changes": []})["changes"].append(c)
    return sorted(grouped.values(), key=lambda g: (g["product"]["brand_name"], g["product"]["name"]))


def alerts(product, kind: str) -> bool:
    """A wishlist fragrance also alerts on price drops; a favourite brand's on new and restock."""
    kinds = FAVOURITE_BRAND_KINDS if product["status"] == "default" else WISHLIST_KINDS
    return product["alerting"] and kind in kinds


def compose(failed, basket, followed, new_brands) -> str:
    sections = []
    if failed:
        sections.append([f"⚠️ Collection failed: {escape(', '.join(failed))}. See the Dokploy schedule log."])
    if basket:
        sections.append([f"<b>🧺 Baskets ({len(basket)})</b>"] + [describe(e) for e in basket] + [f"See {link('/orders')}"])
    if followed:
        more = [f"…and {len(followed) - DIGEST_MAX} more in the backoffice"] if len(followed) > DIGEST_MAX else []
        sections.append([f"<b>⭐ Wishlist and favourites ({len(followed)})</b>"] + [product(g) for g in followed[:DIGEST_MAX]] + more)
    if len(new_brands) > OFFER_MAX:
        sections.append([f"<b>🆕 New brands ({len(new_brands)})</b>", f"Choose for them at {link('/brands?status=new')}"])
    elif new_brands:
        sections.append([f"<b>🆕 New brands ({len(new_brands)})</b> below"])
    return "\n\n".join("\n".join(section) for section in sections)


def describe(e) -> str:
    price = f"€{e['price']:.2f}" if e["price"] is not None else "no price"
    if e["kind"] in ("price_drop", "price_up"):
        what = f"price {'drop' if e['kind'] == 'price_drop' else 'up'} €{e['old_value']:.2f} → {price}"
    elif e["kind"] == "soldout":
        what = f"sold out (was {price})"
    else:
        what = f"{'back in stock' if e['kind'] == 'restock' else 'new'} · {price}"
    return (f"• <b>{escape(e['brand_name'])}</b> {escape(e['name'])}\n"
            f"   {what} · qty {e['qty']} · {escape(e['supplier'])} · EAN {e['ean'] or '–'}")


def product(group) -> str:
    """One fragrance and what happened to it, like a row of the Changes page:
    • Creed Aventus EDP
       Back in stock · 👑 €2.10/ml · nunu 100 ml €210.00"""
    p = group["product"]
    name = escape(pretty_name(p["name"], p["brand_name"]))
    if os.environ.get("BACKOFFICE_URL"):
        name = f'<a href="{escape(link(f"/products/{p['id']}"))}">{name}</a>'
    concentration = f" {escape(p['concentration'])}" if p["concentration"] else ""
    lines = [f"• <b>{escape(p['brand_name'])}</b> {name}{concentration}"]
    for c in group["changes"]:
        what = LABELS[c["kind"]]
        if c["kind"] == "price_drop":
            what += f" {c['offer']['per_ml'] / c['was']['per_ml'] - 1:.0%} (was €{c['was']['per_ml']:.2f}/ml)"
        if c["offer"]:
            o = c["offer"]
            what += (f" · 👑 €{o['per_ml']:.2f}/ml · {escape(o['supplier'])} {escape(o['size'])}"
                     f"{' tester' if o['tester'] else ''} €{o['price']:.2f}")
        lines.append(f"   {what}")
    return "\n".join(lines)


def offer(conn, brand, hints) -> tuple[str, list[list[dict]]]:
    """One new brand as a message with a Favourite button (not tapping keeps Follow)."""
    products = conn.execute(
        "SELECT name, supplier FROM catalog WHERE brand_id = ? AND qty > 0 ORDER BY name", (brand["id"],)).fetchall()
    suppliers = sorted({p["supplier"] for p in products})
    lines = [f"🆕 <b>{escape(brand['name'])}</b> · {len(products)} in stock at {escape(', '.join(suppliers))}"]
    lines += [f"   {escape(p['name'])}" for p in products[:3]]
    lines += [f"   Looks like <b>{escape(name)}</b> ({reason})" for _, name, reason in hints[:2]]
    buttons = [[{"text": label, "callback_data": f"brand:{brand['id']}:{status}"}
                for label, status in (("⭐ Favourite", "favourite"),)]]
    buttons += [[{"text": f"Same as {name}", "callback_data": f"merge:{brand['id']}:{other}"}] for other, name, _ in hints[:2]]
    return "\n".join(lines), buttons


def link(path: str) -> str:
    base = os.environ.get("BACKOFFICE_URL", "").rstrip("/")
    return f"{base}{path}" if base else f"the backoffice ({path})"
