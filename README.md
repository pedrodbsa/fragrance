# Fragrance tracker

Watches B2B suppliers' perfume stock and sends you a Telegram digest when your favourite brands
get new products or restocks, wishlist fragrances appear or get cheaper, or new brands
show up. The full plan is in docs/spec.md.

## How it works

```
Dokploy schedule ─▶ fragrance run ─▶ collect each supplier ─▶ SQLite (listings, fragrances, brands, events)
Dokploy schedule ─▶ fragrance notify ─▶ one digest a day ─▶ Telegram ─▶ Favourite button ─▶ backoffice /telegram
backoffice (https://…) ◀─ you: brand tiers, fragrance lists, stock, collection
Litestream ─▶ R2 (continuous backup; restored automatically on a fresh server)
```

- **collect** fetches a supplier's full in-stock list, compares it with what's stored, and
  records events: `new`, `restock`, `price_drop`, `price_up`, `soldout`. A supplier's first
  run only stores the starting point. Quantity changes are stored but aren't events.
- **Brands** are *favourites* (shown, alerts), *followed* (shown, no alerts; where new
  brands start) or not followed (hidden). **Fragrances** go on the *wishlist* (alerts), the *fillers* (fine to own, e.g. to
  reach a minimum order; no alerts), *ignored*, or on no list, where the brand's status
  applies. A fragrance's list wins over its brand's. Supplier
  spellings of a brand are merged through aliases, with suggestions in the Brands page's New tab.
  Products a supplier lists without a brand all go to one brand, (Unknown); move them to
  their real brand from the product page's Manage tab.
- **Feed** (the backoffice's first page) is about fragrances, not listings: new (no
  supplier had it before), back in stock or sold out across all suppliers, and supplier price
  changes that move its best price per ml (the 👑: every size and supplier, testers included) by
  more than 5%; a bottle selling out or appearing doesn't count as a price change. It's rebuilt from the events each time it opens
  (`app/changes.py`), so nothing extra is stored. Each change opens to show every supplier
  at that moment; a fragrance's page has its full per-supplier history. The Summary tab shows
  the same day grouped instead: new or back in stock, sold out, price up, price down, each
  fragrance once per group.
- **notify** sends one digest a day with everything since the last one, only if something changed: failed
  suppliers, basket items that sold out, came back or changed price, and, one entry per fragrance as on the Feed, favourite brands'
  new fragrances and restocks and wishlist fragrances (new, back in stock, cheaper), and new brands with a Favourite button. Order suggestions stay on the
  Orders page.
- **Products** lists the wishlist, fillers, ignored fragrances and your collection (owned, which
  doesn't change alerts).
- **Merges** (a tab of Products) suggests fragrances that might be the same juice (same brand, an EAN in common)
  for you to merge or mark as different; nothing merges without you.
- **Catalogue**: every listing points to a fragrance (brand + name + concentration), worked
  out once when the listing first appears, from the name read out of the supplier's product
  name. Every fragrance has its own page, on a list or not.
- **Pictures**: listings keep the supplier's product picture when it sends one
  (fragrances-wholesale, symphonya, parfumcompany, Nunu; not fragranta, romscent or
  perfumes-wholesale). A fragrance shows the first of those suppliers' pictures, in that order,
  beside its name in the lists and on its page. Pictures load straight from the suppliers' sites.

## Code map

| Path | What |
| --- | --- |
| `app/suppliers/<name>.py` | One per supplier: `fetch()` returns its in-stock items |
| `app/collect.py` | Compares a fetch with the database, records events |
| `app/changes.py` | Product-level changes for the Feed, rebuilt from the events |
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
| `fragrances-wholesale` | fragrances-wholesale.eu | XML catalogue (`/generator/catalog/xml?token=`, `SUPPLIER_FRAGRANCES_WHOLESALE_TOKEN`). Perfumes, testers and gift sets only. Its sister shop wholesale-fragrances.eu has the same products about 0.8% dearer, so it isn't collected. |
| `perfumes-wholesale` | perfumes-wholesale.eu | Two XML feeds: the nightly catalogue for names and the 10-minute stock feed for price and quantity (`SUPPLIER_PERFUMES_WHOLESALE_HASH`). Perfumes, testers, unboxed bottles and gift sets only; the cheapest warehouse when there are several. |
| `symphonya` | symphonya.eu | JSON API, product call only (`/api/getProducts/{key}?cat=fragrance`, `SUPPLIER_SYMPHONYA_KEY`); their order and checkout calls are never used. Perfumes and perfume sets, boxed or tester; no vials, minis or samples. |
| `parfumcompany` | parfumcompany.pl | XML feed (`/en/xml/dropshipping.xml?token=&mode=xml`, `SUPPLIER_PARFUMCOMPANY_TOKEN`), prices in euros without VAT. Perfumes, testers, unboxed bottles ("flacon") and sets; no miniatures, mists, oils or cosmetics. |
| `fragranta` | fragranta.eu | Logged in as the B2B customer (`SUPPLIER_FRAGRANTA_EMAIL`, `SUPPLIER_FRAGRANTA_PASSWORD`), downloads the Excel catalogue (`/en/catalogue`); logged out the site hides stock and prices. Perfumes and perfume gift sets only; the promo price when there is one. |
| `romscent` | romscent.com | Logged in as the B2B customer (`SUPPLIER_ROMSCENT_EMAIL`, `SUPPLIER_ROMSCENT_PASSWORD`), downloads the Excel price list behind the site's Stock export page. Men's, women's and unisex perfumes and gift sets only. |

## Running locally

```
uv sync
set -a; . ./.env; set +a
uv run fragrance run
uv run fragrance notify
uv run uvicorn app.web:app --reload   # http://127.0.0.1:8000
```
