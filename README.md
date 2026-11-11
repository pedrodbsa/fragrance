# Fragrance tracker

Watches B2B suppliers' perfume stock and sends you a Telegram digest when brands you follow
get new products or restocks, wishlist fragrances appear or get cheaper, or a new brand
needs triage. The full plan is in docs/spec.md.

## How it works

```
Dokploy schedule ─▶ fragrance run ─▶ collect each supplier ─▶ SQLite (products, events, brands)
                                 └─▶ one digest ─▶ Telegram ─▶ triage buttons ─▶ backoffice /telegram
backoffice (https://…) ◀─ you: triage brands, browse stock and changes, wishlist / collection
Litestream ─▶ R2 (continuous backup; restored automatically on a fresh server)
```

- **collect** fetches a supplier's full in-stock list, compares it with what's stored, and
  records events: `new`, `restock`, `price_drop`, `price_up`, `soldout`. A supplier's first
  run only stores the starting point. Quantity changes are stored but aren't events.
- **Brands** each have a status: *follow* (shown, alerts), *browse* (shown, no alerts),
  *ignore* (hidden everywhere) or *new* (waiting for triage). Supplier spellings of the same
  brand are merged through aliases, with suggestions on the Triage page.
- **notify** sends one digest after all suppliers ran, only if something changed: failed
  suppliers, followed brands' new products and restocks, wishlist fragrances (new, back in
  stock, cheaper), and new brands with Follow / Browse / Ignore buttons.
- **Products** are your decisions about single fragrances: *want* (wishlist, alerts),
  *own* (collection, no alerts) or *not interested* (hidden). They win over the brand's
  status. Listings are matched by the fragrance name read from the supplier's product name.

## Code map

| Path | What |
| --- | --- |
| `app/suppliers/<name>.py` | One per supplier: `fetch()` returns its in-stock items |
| `app/collect.py` | Compares a fetch with the database, records events |
| `app/notify.py` | Builds and sends the digest |
| `app/brands.py` | Brand statuses, merging, merge suggestions |
| `app/fragrances.py` | Fragrance decisions and matching listings to them |
| `app/telegram.py` | Telegram messages, buttons and webhook |
| `app/web.py`, `app/templates/` | Backoffice |
| `app/db.py` | Schema |
| `docker/` | Entrypoint, Litestream config |

## Adding a supplier

1. Write `app/suppliers/<name>.py` with `fetch() -> list[Item]` (see `nunu.py`); credentials
   come from env vars.
2. Register it in `app/suppliers/__init__.py`.
3. Add its env vars in Dokploy. The `fragrance run` schedule picks it up automatically; its
   first run records a baseline and puts its new brands on the Triage page.

## Suppliers

| Key | Site | Source |
| --- | --- | --- |
| `nunu` | nunutrading.com | BigCommerce storefront GraphQL (the API behind the stock-offer Excel download), logged in as the B2B customer so prices are included. Perfume category only. |

## Running locally

```
uv sync
set -a; . ./.env; set +a
uv run fragrance run
uv run uvicorn app.web:app --reload   # http://127.0.0.1:8000
```
