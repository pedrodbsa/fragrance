"""Changes at the product level: what happened to a fragrance across all suppliers, worked out
from the supplier events (new, restock, soldout, price changes) each time the page is opened.

Every collection run (one supplier, one moment) is replayed in order. Before and after each
run we look at every listing of the fragrances it touched, at every supplier, and record:
  new         no supplier had listed this fragrance before
  restock     it was out of stock everywhere and now a supplier has it
  soldout     a supplier had it and now none does
  price_drop  the cheapest in-stock price of one of its sizes fell by more than MIN_PRICE_MOVE
  price_up    ... or rose by more than that (also when the cheapest supplier sells out)
One supplier losing a fragrance that others still have is not a product change; it shows in
the supplier breakdown and on the product page's history.

A supplier's first run only sets its starting point, as for the supplier events. Nothing new is
stored: because it's rebuilt each time, merging two fragrances also merges their history.
"""

from collections import defaultdict

from app.collect import MIN_PRICE_MOVE
from app.fragrances import variant


def replay(conn) -> list[dict]:
    """Every product change ever, newest first. Each one carries `listings`: where the fragrance
    stood at every supplier right after that run, with what changed in the run marked."""
    listings = {(r["supplier"], r["sku"]): {**r, "size": variant(r["name"])} for r in conn.execute(
        "SELECT supplier, sku, name, fragrance_id, first_seen, price FROM listings")}
    events = conn.execute(
        "SELECT supplier, sku, kind, old_value, new_value, created_at FROM events ORDER BY created_at, id").fetchall()

    # Each listing's price when first seen: before its first recorded price change, or today's.
    first_price = {}
    for e in events:
        if e["kind"] in ("price_drop", "price_up"):
            first_price.setdefault((e["supplier"], e["sku"]), e["old_value"])

    # Runs in time order: (when, supplier) -> its events, and the listings it first saw. Listings
    # first seen without a "new" event came in the supplier's first run (its starting point).
    runs = defaultdict(lambda: {"events": [], "appeared": []})
    for e in events:
        runs[(e["created_at"], e["supplier"])]["events"].append(e)
    for key, listing in listings.items():
        runs[(listing["first_seen"], listing["supplier"])]["appeared"].append(key)

    state = {}                     # listing -> {"in_stock", "price"}, once it has appeared
    by_fragrance = defaultdict(set)  # fragrance -> its listings that have appeared
    changes = []
    for (when, supplier), run in sorted(runs.items()):
        news = {(e["supplier"], e["sku"]) for e in run["events"] if e["kind"] == "new"}
        # The starting point of a first run goes in silently, before anything is compared.
        for key in run["appeared"]:
            if key not in news:
                appear(state, by_fragrance, listings, first_price, key)
        happened = {}
        for e in run["events"]:  # a restock and a price change in one run: the restock is shown
            happened.setdefault((e["supplier"], e["sku"]), e["kind"])
        touched = {listings[(e["supplier"], e["sku"])]["fragrance_id"] for e in run["events"]
                   if (e["supplier"], e["sku"]) in listings}
        before = {f: snapshot(state, by_fragrance[f], listings) for f in touched}
        for e in run["events"]:
            key = (e["supplier"], e["sku"])
            if key not in listings:  # a listing deleted since (its brand was removed)
                continue
            if key not in state:  # its "new" event, or (rarely) an event dated before its first sighting
                appear(state, by_fragrance, listings, first_price, key)
            if e["kind"] == "restock":
                state[key]["in_stock"] = True
            elif e["kind"] == "soldout":
                state[key]["in_stock"] = False
            elif e["kind"] in ("price_drop", "price_up"):
                state[key]["price"] = e["new_value"]
        for f in touched:
            after = snapshot(state, by_fragrance[f], listings)
            found = compare(before[f], after)
            if found:
                where = breakdown(state, by_fragrance[f], listings, happened)
                changes += [{**c, "fragrance_id": f, "supplier": supplier, "created_at": when, "listings": where}
                            for c in found]
    changes.reverse()
    return changes


def appear(state, by_fragrance, listings, first_price, key) -> None:
    listing = listings[key]
    state[key] = {"in_stock": True, "price": first_price.get(key, listing["price"])}
    by_fragrance[listing["fragrance_id"]].add(key)


def snapshot(state, keys, listings) -> dict:
    """A fragrance at one moment: whether any supplier listed it, whether any has it in stock,
    and the cheapest in-stock price of each size with the supplier offering it."""
    best = {}
    for key in keys:
        s = state[key]
        if s["in_stock"] and s["price"] is not None:
            size = listings[key]["size"][1]
            if size not in best or s["price"] < best[size][0]:
                best[size] = (s["price"], key[0])
    return {"listed": bool(keys), "in_stock": any(state[k]["in_stock"] for k in keys), "best": best}


def compare(before: dict, after: dict) -> list[dict]:
    """The product changes between two snapshots of a fragrance."""
    if not before["in_stock"] and after["in_stock"]:
        kind = "restock" if before["listed"] else "new"
        price, cheapest = min(after["best"].values(), default=(None, None))
        return [{"kind": kind, "size": None, "old_value": None, "new_value": price, "cheapest": cheapest}]
    if before["in_stock"] and not after["in_stock"]:
        return [{"kind": "soldout", "size": None, "old_value": None, "new_value": None, "cheapest": None}]
    found = []
    for size, (new, cheapest) in after["best"].items():
        old = before["best"].get(size, (None,))[0]
        if old is not None and abs(new - old) > MIN_PRICE_MOVE:
            found.append({"kind": "price_drop" if new < old else "price_up", "size": size,
                          "old_value": old, "new_value": new, "cheapest": cheapest})
    return found


def breakdown(state, keys, listings, happened: dict) -> list[dict]:
    """Every listing of the fragrance right after a run: supplier, size, price, in stock or
    not, whether it's the cheapest in stock for its size, and the supplier event of this run
    (happened: listing -> its event), if it had one."""
    rows = [{"supplier": k[0], "size": listings[k]["size"][1], "sort": listings[k]["size"][0],
             "name": listings[k]["name"], **state[k], "event": happened.get(k)} for k in keys]
    rows.sort(key=lambda r: (r["sort"], r["size"], not r["in_stock"], r["price"] if r["price"] is not None else 1e9))
    for i, r in enumerate(rows):  # sorted so the first in-stock listing of each size is its cheapest
        r["cheapest"] = r["in_stock"] and r["price"] is not None and (i == 0 or rows[i - 1]["size"] != r["size"])
    return rows
