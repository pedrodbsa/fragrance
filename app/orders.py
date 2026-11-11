"""Order suggestions: per supplier, an order you could place from your wishlist, topped up
with fillers to reach the supplier's minimum order value (MOV, set on the Suppliers page).

For each supplier that has a wishlist fragrance in stock, or a basket open:
  1. every wishlist fragrance it has, one bottle each, in the size you picked on the
     fragrance's page (or the cheapest size if you didn't pick one);
  2. if that and the basket are under the MOV, the fillers it has in stock that reach the
     MOV with the least money spent over it. If all its fillers together don't reach it,
     the order is short.
Fragrances already in the supplier's basket aren't suggested again, and the basket's total
counts towards the MOV.
"""

from app.fragrances import variant


def plan(conn, baskets: list[dict]) -> list[dict]:
    """One suggestion per supplier with wishlist fragrances in stock or a basket (as
    baskets.contents gives them)."""
    basket_total = {b["supplier"]: b["total"] for b in baskets}
    in_basket = {(b["supplier"], i["fragrance_id"]) for b in baskets for i in b["items"]}
    movs = {s["name"]: s["mov"] for s in conn.execute("SELECT name, mov FROM suppliers")}
    offers = {}  # (supplier, fragrance id) -> the listing to buy
    for listing in conn.execute("""SELECT * FROM catalog WHERE qty > 0 AND price IS NOT NULL
                                   AND fragrance_status IN ('wishlist', 'filler')"""):
        size = variant(listing["name"])[1]
        if listing["buy_size"] and size != listing["buy_size"]:
            continue
        if (listing["supplier"], listing["fragrance_id"]) in in_basket:
            continue
        line = {**dict(listing), "size_label": size}
        best = offers.get((listing["supplier"], listing["fragrance_id"]))
        if best is None or line["price"] < best["price"]:
            offers[(listing["supplier"], listing["fragrance_id"])] = line

    suggestions = []
    for supplier in sorted({s for s, _ in offers}):
        lines = sorted((o for (s, _), o in offers.items() if s == supplier), key=lambda o: o["price"])
        wanted = [o for o in lines if o["fragrance_status"] == "wishlist"]
        if not wanted and supplier not in basket_total:
            continue
        fillers = [o for o in lines if o["fragrance_status"] == "filler"]
        mov = movs.get(supplier)
        gap = (mov or 0) - basket_total.get(supplier, 0) - sum(o["price"] for o in wanted)
        chosen = top_up(gap, fillers)
        order = wanted + (chosen or [])
        total = sum(o["price"] for o in order)
        suggestions.append({
            "supplier": supplier, "mov": mov, "wanted": wanted, "fillers": chosen or [],
            "spare": [o for o in fillers if o not in (chosen or [])], "total": total,
            "short": None if chosen is not None else gap - sum(o["price"] for o in fillers),
        })
    return suggestions


def top_up(gap: float, fillers: list[dict]) -> list[dict] | None:
    """The fillers whose prices add up to at least `gap` with the least overspend, or None
    when all of them together don't reach it."""
    if gap <= 0:
        return []
    target = round(gap * 100)
    under = {0: []}  # total in cents -> fillers that make it, for totals still under the gap
    best = None
    for filler in fillers:
        cents = round(filler["price"] * 100)
        for total, chosen in list(under.items()):
            reached = total + cents
            if reached >= target:
                if best is None or reached < best[0]:
                    best = (reached, chosen + [filler])
            elif reached not in under:
                under[reached] = chosen + [filler]
    return best[1] if best else None
