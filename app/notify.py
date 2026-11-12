"""The digest: one Telegram message per collection window, sent only if something changed.

Sections:
  ⚠️ suppliers whose collection failed this window
  🧺 Baskets: items in one of your baskets that sold out, came back, or changed price
  ⭐ Wishlist and favourites: wishlist fragrances (new, back in stock, or cheaper), plus new
     products and restocks from favourite brands (except fragrances you ignored or marked as
     filler)
  🆕 New brands: each one comes as its own message with Favourite / Unfollow buttons (and
     "Same as …" when it looks like a brand you have). Not tapping leaves it on Follow:
     shown in Stock, no alerts. When many arrive at once, the digest links to the New
     brands page instead.
Unfollowed brands, ignored fragrances and fillers never appear. Everything else (followed brands, sold out,
price up) is recorded for the backoffice but not sent.
"""

import os
from html import escape

from app import telegram
from app.brands import suggestions
from app.db import connect, now

FOLLOWED_FRAGRANCE_KINDS = ("new", "restock", "price_drop")
FOLLOWED_BRAND_KINDS = ("new", "restock")
DIGEST_MAX = 60  # beyond this the message lists a count; the backoffice has the full list
OFFER_MAX = 8    # more new brands than this go to the Brands page's New tab instead of one message each

PENDING = """
SELECT e.id, e.kind, e.old_value, e.new_value, c.*,
       EXISTS (SELECT 1 FROM basket b WHERE b.supplier = e.supplier AND b.sku = e.sku) AS in_basket
FROM events e JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku
WHERE e.notified_at IS NULL ORDER BY c.brand_name, c.name
"""


def notify(failed: list[str]) -> None:
    conn = connect()
    pending = conn.execute(PENDING).fetchall()
    basket = [e for e in pending if e["in_basket"]]  # every change to a basket item matters
    followed = [e for e in pending if alerts(e) and not e["in_basket"]]
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


def alerts(event) -> bool:
    """A wishlist fragrance also alerts on price drops; a favourite brand on new and restock."""
    kinds = FOLLOWED_BRAND_KINDS if event["fragrance_status"] == "default" else FOLLOWED_FRAGRANCE_KINDS
    return event["alerting"] and event["kind"] in kinds


def compose(failed, basket, followed, new_brands) -> str:
    sections = []
    if failed:
        sections.append([f"⚠️ Collection failed: {escape(', '.join(failed))}. See the Dokploy schedule log."])
    if basket:
        sections.append([f"<b>🧺 Baskets ({len(basket)})</b>"] + [describe(e) for e in basket] + [f"See {link('/orders')}"])
    if followed:
        more = [f"…and {len(followed) - DIGEST_MAX} more in the backoffice"] if len(followed) > DIGEST_MAX else []
        sections.append([f"<b>⭐ Wishlist and favourites ({len(followed)})</b>"] + [describe(e) for e in followed[:DIGEST_MAX]] + more)
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


def offer(conn, brand, hints) -> tuple[str, list[list[dict]]]:
    """One new brand as a message with Favourite / Unfollow buttons (not tapping keeps Follow)."""
    products = conn.execute(
        "SELECT name, supplier FROM catalog WHERE brand_id = ? AND qty > 0 ORDER BY name", (brand["id"],)).fetchall()
    suppliers = sorted({p["supplier"] for p in products})
    lines = [f"🆕 <b>{escape(brand['name'])}</b> · {len(products)} in stock at {escape(', '.join(suppliers))}"]
    lines += [f"   {escape(p['name'])}" for p in products[:3]]
    lines += [f"   Looks like <b>{escape(name)}</b> ({reason})" for _, name, reason in hints[:2]]
    buttons = [[{"text": label, "callback_data": f"brand:{brand['id']}:{status}"}
                for label, status in (("⭐ Favourite", "favourite"), ("🚫 Unfollow", "none"))]]
    buttons += [[{"text": f"Same as {name}", "callback_data": f"merge:{brand['id']}:{other}"}] for other, name, _ in hints[:2]]
    return "\n".join(lines), buttons


def link(path: str) -> str:
    base = os.environ.get("BACKOFFICE_URL", "").rstrip("/")
    return f"{base}{path}" if base else f"the backoffice ({path})"
