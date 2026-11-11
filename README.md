# Fragrance tracker

Watches B2B suppliers' perfume stock and messages you on Telegram when something you care
about appears, comes back, or gets cheaper, plus a digest of new products you haven't muted.

## How it works

```
Dokploy schedule ─▶ run-supplier nunu ─▶ fragrance collect nunu ─▶ SQLite (products, events)
                                     └─▶ fragrance notify ─▶ Telegram
backoffice (https://…) ◀─ you: browse stock and changes, edit rules
Litestream ─▶ R2 (continuous backup; restored automatically on a fresh server)
```

- **collect** fetches a supplier's full in-stock list, compares it with what's stored, and
  records events: `new`, `restock`, `price_drop`, `price_up`, `soldout`. A supplier's first
  run only stores the starting point. Quantity changes are stored but aren't events.
- **notify** sends one message per run:
  - **Watchlist**: products matching a *watch* rule that are new, back in stock or cheaper.
  - **New products**: every other new product unless a *mute* rule matches it.
- **Rules** match on `brand` (exact), `ean` (any of the product's EANs), `keyword` (in the
  name) or `supplier`. Edit them in the backoffice; the Stock page has one-click watch/mute.

## Code map

| Path | What |
| --- | --- |
| `app/suppliers/<name>.py` | One per supplier: `fetch()` returns its in-stock items |
| `app/collect.py` | Compares a fetch with the database, records events |
| `app/notify.py` | Builds and sends the Telegram message |
| `app/rules.py` | Rule matching |
| `app/web.py`, `app/templates/` | Backoffice |
| `app/db.py` | Schema |
| `docker/` | Entrypoint, Litestream config, `run-supplier` |

## Adding a supplier

1. Write `app/suppliers/<name>.py` with `fetch() -> list[Item]` (see `nunu.py`); credentials
   come from env vars.
2. Register it in `app/suppliers/__init__.py`.
3. Add its env vars in Dokploy and a schedule `run-supplier <name>` (docs/deploy.md).

## Suppliers

| Key | Site | Source |
| --- | --- | --- |
| `nunu` | nunutrading.com | BigCommerce storefront GraphQL (the API behind the stock-offer Excel download), logged in as the B2B customer so prices are included. Perfume category only. |

## Running locally

```
uv sync
set -a; . ./.env; set +a
uv run fragrance collect nunu && uv run fragrance notify
uv run uvicorn app.web:app --reload   # http://127.0.0.1:8000
```
