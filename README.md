# Fragrance tracker

Watches B2B suppliers' perfume stock and sends you a Telegram digest when brands you follow
get new products or restocks, fragrances you follow appear or get cheaper, or new brands
show up. The full plan is in docs/spec.md.

## How it works

```
Dokploy schedule ─▶ fragrance run ─▶ collect each supplier ─▶ SQLite (listings, fragrances, brands, events)
                                 └─▶ one digest ─▶ Telegram ─▶ Follow / Ignore buttons ─▶ backoffice /telegram
backoffice (https://…) ◀─ you: follow / ignore brands and fragrances, stock, collection
Litestream ─▶ R2 (continuous backup; restored automatically on a fresh server)
```

- **collect** fetches a supplier's full in-stock list, compares it with what's stored, and
  records events: `new`, `restock`, `price_drop`, `price_up`, `soldout`. A supplier's first
  run only stores the starting point. Quantity changes are stored but aren't events.
- **Brands** are *followed* (alerts), *ignored* (hidden) or on *Browse*, the default (shown,
  no alerts). **Fragrances** go on the *wishlist* (alerts), the *fillers* (fine to own, e.g. to
  reach a minimum order; no alerts), *ignored*, or on no list, where the brand's status
  applies. A fragrance's list wins over its brand's. Supplier
  spellings of a brand are merged through aliases, with suggestions in the Brands page's New tab.
- **notify** sends one digest after all suppliers ran, only if something changed: failed
  suppliers, basket items that sold out, came back or changed price, followed brands' new products and restocks, wishlist fragrances (new, back in
  stock, cheaper), and new brands with Follow / Ignore buttons. Order suggestions stay on the
  Orders page.
- **Products** lists the wishlist, fillers, ignored fragrances and your collection (owned, which
  doesn't change alerts).
- **Merges** suggests fragrances that might be the same juice (same brand, an EAN in common)
  for you to merge or mark as different; nothing merges without you.
- **Catalogue**: every listing points to a fragrance (brand + name + concentration), worked
  out once when the listing first appears, from the name read out of the supplier's product
  name. Every fragrance has its own page, on a list or not.

## Code map

| Path | What |
| --- | --- |
| `app/suppliers/<name>.py` | One per supplier: `fetch()` returns its in-stock items |
| `app/collect.py` | Compares a fetch with the database, records events |
| `app/notify.py` | Builds and sends the digest |
| `app/orders.py` | Order suggestions: wishlist plus fillers up to each supplier's minimum |
| `app/baskets.py` | Your open basket per supplier, kept until you place the order |
| `app/brands.py` | Brand statuses, merging, merge suggestions |
| `app/fragrances.py` | The fragrance catalogue: matching listings, lists, merges |
| `app/telegram.py` | Telegram messages, buttons and webhook |
| `app/web.py`, `app/templates/` | Backoffice |
| `app/db.py` | Schema (tables described at the top) |
| `app/upgrades.py`, `app/brand_cleanup.py` | One-time changes to an existing database, run on start |
| `docker/` | Entrypoint, Litestream config |

## Adding a supplier

1. Write `app/suppliers/<name>.py` with `fetch() -> list[Item]` (see `nunu.py`); credentials
   come from env vars.
2. Register it in `app/suppliers/__init__.py`.
3. Add its env vars in Dokploy. The `fragrance run` schedule picks it up automatically; its
   first run records a baseline and lists its brands in the Brands page's New tab.

## Suppliers

| Key | Site | Source |
| --- | --- | --- |
| `nunu` | nunutrading.com | BigCommerce storefront GraphQL (the API behind the stock-offer Excel download), logged in as the B2B customer so prices are included. Perfume category only. |
| `wholesale-fragrances` | wholesale-fragrances.eu | XML catalogue (`/generator/catalog/xml?token=`, `SUPPLIER_WHOLESALE_FRAGRANCES_TOKEN`). Perfumes, testers and gift sets only. |
| `fragrances-wholesale` | fragrances-wholesale.eu | Same company and format, its own prices (`SUPPLIER_FRAGRANCES_WHOLESALE_TOKEN`). |
| `perfumes-wholesale` | perfumes-wholesale.eu | Two XML feeds: the nightly catalogue for names and the 10-minute stock feed for price and quantity (`SUPPLIER_PERFUMES_WHOLESALE_HASH`). Perfumes, testers, unboxed bottles and gift sets only; the cheapest warehouse when there are several. |

## Running locally

```
uv sync
set -a; . ./.env; set +a
uv run fragrance run
uv run uvicorn app.web:app --reload   # http://127.0.0.1:8000
```
