"""Backoffice: browse stock and changes, follow or ignore brands and single fragrances, and
keep your collection.
Also receives Telegram button taps on /telegram.

Run: uvicorn app.web:app. Pages are protected by HTTP basic auth (BACKOFFICE_USER,
BACKOFFICE_PASSWORD). /telegram is checked against Telegram's secret header instead.
With BACKOFFICE_URL set, the app registers that webhook with Telegram when it starts.
"""

import os
import re
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import brands, orders, telegram
from app.db import connect
from app.upgrades import upgrade
from app import fragrances
from app.fragrances import CONCENTRATIONS, key, variant
from app.suppliers import SUPPLIERS

security = HTTPBasic()


def login(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    user_ok = secrets.compare_digest(credentials.username, os.environ["BACKOFFICE_USER"])
    password_ok = secrets.compare_digest(credentials.password, os.environ["BACKOFFICE_PASSWORD"])
    if not (user_ok and password_ok):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    upgrade(connect())
    if os.environ.get("BACKOFFICE_URL"):
        try:
            telegram.register_webhook(os.environ["BACKOFFICE_URL"])
            print("telegram: webhook registered")
        except Exception as error:  # the backoffice still works; only Telegram buttons won't
            print(f"telegram: webhook registration failed: {error}")
    yield


here = Path(__file__).parent
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=here / "static"), name="static")
office = APIRouter(dependencies=[Depends(login)])
templates = Jinja2Templates(directory=here / "templates")
PAGE = 200


def local_time(stamp: str) -> str:
    """UTC timestamp from the database, shown in the server's timezone (TZ)."""
    return datetime.fromisoformat(stamp).astimezone().strftime("%d %b %H:%M")


# Suppliers list names in capitals with the brand first ("CREED AVENTUS EDP 50 ML VAPO").
# The brand has its own line, so it's dropped from the name, and the rest is title-cased
# with fragrance abbreviations kept readable ("Aventus EDP 50 ml Vapo").
UPPER = {"EDP", "EDT", "EDC", "EDS", "SPF", "II", "III", "IV", "XL", "XS", "UV", "N°", "NO."}
LOWER = {"ML", "GR", "G", "OZ", "KG", "L", "X", "DE", "DU", "LA", "LE", "DI", "OF", "THE", "AND", "&"}


def pretty_name(name: str, brand: str) -> str:
    if brand and name.upper().startswith(brand.upper() + " "):
        name = name[len(brand) + 1:]
    words = []
    for i, word in enumerate(name.upper().split()):
        if any(c.isdigit() for c in word):  # sizes and numbers: "100ML" -> "100ml", "N°5" stays
            words.append(re.sub(r"(ML|GR|G|OZ|KG)$", lambda m: m.group().lower(), word))
        elif word in UPPER:
            words.append(word)
        elif word in LOWER and i > 0:
            words.append(word.lower())
        else:  # "L'INTERDIT" -> "L'Interdit"
            words.append("'".join(part.capitalize() for part in word.split("'")))
    return " ".join(words)


templates.env.filters["local"] = local_time
templates.env.filters["pretty"] = pretty_name


def back_to(back: str, fallback: str) -> RedirectResponse:
    """Return to the page a form was posted from (only paths on this site)."""
    safe = back.startswith("/") and not back.startswith("//")
    return RedirectResponse(back if safe else fallback, status_code=303)


# --- Changes and stock ---------------------------------------------------------------------

@office.get("/")
def events(request: Request, kind: str = ""):
    conn = connect()
    recent = conn.execute(
        """SELECT e.*, c.name, c.brand, c.brand_name, c.fragrance_id, c.ean, c.price, c.qty
           FROM events e JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku
           WHERE NOT c.hidden AND (? = '' OR e.kind = ?) ORDER BY e.id DESC LIMIT ?""",
        (kind, kind, PAGE),
    ).fetchall()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    last_day = dict(conn.execute(
        """SELECT e.kind, count(*) FROM events e JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku
           WHERE e.created_at >= ? AND NOT c.hidden GROUP BY e.kind""", (since,)).fetchall())
    in_stock, suppliers = conn.execute(
        "SELECT count(*), count(DISTINCT supplier) FROM catalog WHERE qty > 0 AND NOT hidden").fetchone()
    new_brands = conn.execute("SELECT count(*) FROM brands WHERE reviewed_at IS NULL").fetchone()[0]
    return templates.TemplateResponse(request, "events.html", {
        "rows": recent, "kind": kind, "last_day": last_day, "in_stock": in_stock,
        "suppliers": suppliers, "new_brands": new_brands,
    })


def annotate(listings) -> list[dict]:
    """Catalog rows plus each one's size, as the stock tables show it."""
    rows = []
    for r in listings:
        size, size_label = variant(r["name"])
        rows.append({**dict(r), "size": size, "size_label": size_label})
    return rows


def group(rows: list[dict]) -> list[dict]:
    """One entry per fragrance, its sizes and testers under it. For each size, the cheapest
    in-stock listing is shown."""
    groups = {}
    for r in rows:
        g = groups.setdefault(r["fragrance_id"], {**r, "listings": [], "qty": 0, "suppliers": set(), "best": None})
        g["listings"].append(r)
        g["qty"] += r["qty"]
        g["suppliers"].add(r["supplier"])
        if r["qty"] > 0 and r["price"] is not None and (g["best"] is None or r["price"] < g["best"]):
            g["best"] = r["price"]
    for g in groups.values():
        cheapest = {}
        for r in sorted(g["listings"], key=lambda r: (r["qty"] == 0, r["price"] or 0)):
            cheapest.setdefault(r["size_label"], r)
        g["sizes"] = sorted(cheapest.values(), key=lambda r: (r["size"], r["size_label"]))
    return list(groups.values())


def price_history(conn, rows: list[dict]) -> list[dict]:
    """Price over time for each listing, rebuilt from recorded price changes: the price
    when first seen, each change, and today's price. One series per size and supplier."""
    series = []
    today = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        if r["price"] is None:
            continue
        changes = conn.execute(
            """SELECT created_at, old_value, new_value FROM events WHERE supplier = ? AND sku = ?
               AND kind IN ('price_drop', 'price_up') ORDER BY id""", (r["supplier"], r["sku"])).fetchall()
        start = changes[0]["old_value"] if changes else r["price"]
        points = [(r["first_seen"], start)] + [(c["created_at"], c["new_value"]) for c in changes] + [(today, r["price"])]
        series.append({"label": f"{r['size_label']} · {r['supplier']}", "points": points,
                       "low": min(p for _, p in points)})
    return series


IN_STOCK_FIRST = "ORDER BY qty = 0, name"

# Stock's sort choices: label, what to order fragrances by, and whether highest comes first.
# Sold-out fragrances (no price) go last when sorting by price.
STOCK_SORTS = {
    "brand": ("Brand", lambda g: (g["brand_name"].lower(), g["fragrance"], g["concentration"] or ""), False),
    "name": ("Name", lambda g: (g["fragrance"], g["brand_name"].lower()), False),
    "price": ("Price, low to high", lambda g: (g["best"] is None, g["best"] or 0), False),
    "price_desc": ("Price, high to low", lambda g: (g["best"] is not None, g["best"] or 0), True),
    "qty": ("Most in stock", lambda g: g["qty"], True),
    "newest": ("Newest first", lambda g: min(l["first_seen"] for l in g["listings"]), True),
}


@office.get("/stock")
def stock(request: Request, q: str = "", brand: str = "", supplier: str = "",
          in_stock: bool = True, followed: bool = False, everything: bool = False, sort: str = "brand"):
    """Everything that isn't ignored, one row per fragrance. 'followed' narrows to what alerts
    you; 'everything' adds what's ignored."""
    conn = connect()
    found = conn.execute(
        """SELECT * FROM catalog
           WHERE (? = '' OR name LIKE '%' || ? || '%' OR ean = ? OR ean2 = ? OR ean3 = ? OR sku = ?)
             AND (? = '' OR brand_id = ?) AND (? = '' OR supplier = ?) AND (NOT ? OR qty > 0)
             AND (? OR NOT hidden) AND (NOT ? OR alerting)
           ORDER BY brand_name, fragrance, concentration""",
        (q, q, q, q, q, q, brand, brand, supplier, supplier, in_stock, everything, followed),
    ).fetchall()
    brand_list = conn.execute("SELECT id, name FROM brands WHERE status != 'ignore' ORDER BY name").fetchall()
    suppliers = [r[0] for r in conn.execute("SELECT name FROM suppliers ORDER BY name")]
    sort = sort if sort in STOCK_SORTS else "brand"
    _, order, highest_first = STOCK_SORTS[sort]
    groups = sorted(group(annotate(found)), key=order, reverse=highest_first)
    return templates.TemplateResponse(request, "stock.html", {
        "groups": groups[:PAGE], "total": len(groups), "brands": brand_list, "suppliers": suppliers,
        "q": q, "brand": brand, "supplier": supplier, "in_stock": in_stock, "followed": followed,
        "everything": everything, "sort": sort, "sorts": STOCK_SORTS,
    })


# --- Brands ----------------------------------------------------------------------------------

BRAND_ROWS = """
WITH stock AS (  -- per brand, worked out in one pass over the listings
    SELECT brand_id, sum(qty > 0) AS in_stock, group_concat(DISTINCT supplier) AS suppliers,
           min(CASE WHEN qty > 0 THEN price END) AS low, max(CASE WHEN qty > 0 THEN price END) AS high
    FROM catalog GROUP BY brand_id
), examples AS (  -- each brand's most expensive product in stock
    SELECT brand_id, name AS example FROM (
        SELECT brand_id, name, row_number() OVER (PARTITION BY brand_id ORDER BY price DESC) AS n
        FROM catalog WHERE qty > 0) WHERE n = 1
), spellings AS (
    SELECT brand_id, count(*) AS spellings FROM brand_aliases GROUP BY brand_id
)
SELECT b.*, coalesce(s.in_stock, 0) AS in_stock, s.suppliers, s.low, s.high, e.example, coalesce(n.spellings, 0) AS spellings
FROM brands b
LEFT JOIN stock s ON s.brand_id = b.id
LEFT JOIN examples e ON e.brand_id = b.id
LEFT JOIN spellings n ON n.brand_id = b.id
"""


@office.get("/new")
def new_brands():
    """Old address (earlier digests link here)."""
    return RedirectResponse("/brands?status=new", status_code=303)


@office.get("/brands")
def brand_list(request: Request, status: str = "", q: str = ""):
    """Every brand, or one tab: new (not chosen yet, newest first), follow, default (Browse), ignore."""
    conn = connect()
    if status == "new":
        where, order = "b.reviewed_at IS NULL", "b.created_at DESC, in_stock DESC, b.name"
    else:
        where, order = "(? = '' OR b.status = ?)", "b.name"
    rows = conn.execute(
        f"{BRAND_ROWS} WHERE {where} AND b.name LIKE '%' || ? || '%' ORDER BY {order}",
        (q,) if status == "new" else (status, status, q),
    ).fetchall()
    counts = dict(conn.execute("SELECT status, count(*) FROM brands GROUP BY status").fetchall())
    counts["new"] = conn.execute("SELECT count(*) FROM brands WHERE reviewed_at IS NULL").fetchone()[0]
    return templates.TemplateResponse(request, "brands.html", {
        "rows": rows, "status": status, "q": q, "counts": counts,
        "hints": brands.suggestions(conn) if status == "new" else {},
    })


@office.post("/brands")
def brands_post(action: str = Form(...), ids: list[int] = Form([]), back: str = Form("/brands")):
    """action is 'follow:12' for one brand, 'follow:selected' for the ticked ones (likewise
    default and ignore), or 'merge:12:34' to merge brand 12 into brand 34."""
    conn = connect()
    kind, *args = action.split(":")
    with conn:
        if kind == "merge":
            brands.merge(conn, int(args[0]), int(args[1]))
        else:
            for brand_id in (ids if args[0] == "selected" else [int(args[0])]):
                brands.set_status(conn, brand_id, kind)
    return back_to(back, "/brands")


@office.get("/brands/{brand_id}")
def brand_detail(request: Request, brand_id: int):
    conn = connect()
    brand = conn.execute(BRAND_ROWS + " WHERE b.id = ?", (brand_id,)).fetchone()
    if brand is None:
        raise HTTPException(404, "brand not found")
    aliases = conn.execute(
        """SELECT a.alias, (SELECT count(*) FROM listings l WHERE l.brand = a.alias COLLATE NOCASE) AS products
           FROM brand_aliases a WHERE a.brand_id = ? ORDER BY a.alias""", (brand_id,)).fetchall()
    others = conn.execute("SELECT id, name FROM brands WHERE id != ? ORDER BY name", (brand_id,)).fetchall()
    decided = conn.execute(
        "SELECT * FROM fragrances WHERE brand_id = ? AND (status != 'default' OR owned) ORDER BY status, name",
        (brand_id,)).fetchall()
    listings = conn.execute(f"SELECT * FROM catalog WHERE brand_id = ? {IN_STOCK_FIRST}", (brand_id,)).fetchall()
    return templates.TemplateResponse(request, "brand.html", {
        "brand": brand, "aliases": aliases, "others": others, "decided": decided,
        "groups": group(annotate(listings)),
    })


@office.post("/brands/{brand_id}/status")
def brand_status(brand_id: int, status: str = Form(...), back: str = Form("/brands")):
    conn = connect()
    with conn:
        brands.set_status(conn, brand_id, status)
    return back_to(back, "/brands")


@office.post("/brands/{brand_id}/rename")
def brand_rename(brand_id: int, name: str = Form(...)):
    conn = connect()
    with conn:
        brands.rename(conn, brand_id, name)
    return RedirectResponse(f"/brands/{brand_id}", status_code=303)


@office.post("/brands/{brand_id}/merge")
def brand_merge(brand_id: int, into: int = Form(...)):
    conn = connect()
    with conn:
        brands.merge(conn, brand_id, into)
    return RedirectResponse(f"/brands/{into}", status_code=303)


@office.post("/brands/split")
def alias_split(alias: str = Form(...)):
    conn = connect()
    with conn:
        new_id = brands.split(conn, alias)
    return RedirectResponse(f"/brands/{new_id}", status_code=303)


# --- Products: the fragrance catalogue and your lists ----------------------------------------

TABS = {"wishlist": "Wishlist", "filler": "Fillers", "owned": "Collection", "ignore": "Ignored"}
PRODUCT = "SELECT f.*, b.name AS brand_name, b.status AS brand_status FROM fragrances f JOIN brands b ON b.id = f.brand_id"


@office.get("/products")
def products(request: Request, tab: str = "wishlist"):
    conn = connect()
    where = "f.owned = 1" if tab == "owned" else "f.status = ?"
    rows = conn.execute(f"{PRODUCT} WHERE {where} ORDER BY b.name, f.name", () if tab == "owned" else (tab,)).fetchall()
    offers = defaultdict(list)  # fragrance id -> its listings in stock, cheapest first
    for r in conn.execute(
            f"""SELECT * FROM catalog WHERE qty > 0 AND fragrance_id IN ({",".join("?" * len(rows))})
                ORDER BY price""", [r["id"] for r in rows]):
        offers[r["fragrance_id"]].append(r)
    counts = dict(conn.execute("SELECT status, count(*) FROM fragrances GROUP BY status").fetchall())
    counts["owned"] = conn.execute("SELECT count(*) FROM fragrances WHERE owned = 1").fetchone()[0]
    brand_list = conn.execute("SELECT id, name FROM brands ORDER BY name").fetchall()
    return templates.TemplateResponse(request, "products.html", {
        "rows": [{**dict(r), "offers": offers[r["id"]]} for r in rows],
        "tab": tab, "tabs": TABS, "counts": counts, "brands": brand_list, "concentrations": CONCENTRATIONS,
    })


@office.post("/products")
def product_add(brand_id: int = Form(...), name: str = Form(...), concentration: str = Form(""),
                status: str = Form("default"), owned: str = Form(""), note: str = Form(""), back: str = Form("/products")):
    """Add a fragrance by hand, even one no supplier lists yet, straight onto a list. If it
    exists already, it's that one: listings found later land on it."""
    if not name.strip():
        raise HTTPException(400, "a fragrance needs a name")
    conn = connect()
    with conn:
        fragrance_id = fragrances.find_or_create(conn, brand_id, name, concentration or None)
        fragrances.set_status(conn, fragrance_id, status)
        if owned:
            fragrances.set_owned(conn, fragrance_id, True)
        if note.strip():
            fragrances.set_note(conn, fragrance_id, note.strip())
    return back_to(back, "/products")


@office.get("/products/{fragrance_id}")
def product_detail(request: Request, fragrance_id: int):
    """Any fragrance: every listing of it by size, its price history, and merging."""
    conn = connect()
    product = conn.execute(f"{PRODUCT} WHERE f.id = ?", (fragrance_id,)).fetchone()
    if product is None:
        raise HTTPException(404, "product not found")
    listings = conn.execute("SELECT * FROM catalog WHERE fragrance_id = ?", (fragrance_id,)).fetchall()
    rows = sorted(annotate(listings), key=lambda r: (r["size"], r["size_label"], r["qty"] == 0, r["price"] or 0))
    return templates.TemplateResponse(request, "product.html", {
        "product": product, "rows": rows, "history": price_history(conn, rows), "concentrations": CONCENTRATIONS,
        **merge_options(conn, product, rows),
    })


def merge_options(conn, product, rows) -> dict:
    """For the product page's "same juice" panel: other names merged into this fragrance,
    the brand's other fragrances to merge in, and those sharing an EAN with it (a hint only:
    suppliers sometimes reuse an EAN for a different fragrance)."""
    merged = conn.execute(
        "SELECT * FROM fragrance_names WHERE fragrance_id = ? AND NOT (name = ? AND concentration = ?) ORDER BY name",
        (product["id"], key(product["name"]), product["concentration"] or "")).fetchall()
    others = conn.execute(
        """SELECT f.*, count(l.sku) AS listings FROM fragrances f JOIN listings l ON l.fragrance_id = f.id
           WHERE f.brand_id = ? AND f.id != ? GROUP BY f.id ORDER BY f.name, f.concentration""",
        (product["brand_id"], product["id"])).fetchall()
    eans = {e for r in rows for e in (r["ean"], r["ean2"], r["ean3"]) if e}
    sharing = {l["fragrance_id"] for l in conn.execute(
        "SELECT fragrance_id, ean, ean2, ean3 FROM catalog WHERE brand_id = ? AND fragrance_id != ?",
        (product["brand_id"], product["id"])) if eans & {l["ean"], l["ean2"], l["ean3"]}}
    rejected = {r[0] for r in conn.execute(  # pairs you said aren't the same
        "SELECT other_id FROM not_same WHERE fragrance_id = ? UNION SELECT fragrance_id FROM not_same WHERE other_id = ?",
        (product["id"], product["id"]))}
    shared = [o for o in others if o["id"] in sharing - rejected]
    return {"merged": merged, "others": others, "shared": shared}


@office.post("/products/{fragrance_id}/status")
def product_status(fragrance_id: int, status: str = Form(...), back: str = Form("/products")):
    """Put a fragrance on the wishlist, fillers or ignored, or off them ('default')."""
    conn = connect()
    with conn:
        fragrances.set_status(conn, fragrance_id, status)
    return back_to(back, "/products")


@office.post("/products/{fragrance_id}/owned")
def product_owned(fragrance_id: int, owned: str = Form(...), back: str = Form("/products")):
    """Put a fragrance in your collection (1) or take it out (0)."""
    conn = connect()
    with conn:
        fragrances.set_owned(conn, fragrance_id, owned == "1")
    return back_to(back, "/products")


@office.post("/products/{fragrance_id}/size")
def product_size(fragrance_id: int, size: str = Form(""), back: str = Form(...)):
    """The size you'd buy; empty buys the cheapest. Order suggestions use it."""
    conn = connect()
    with conn:
        fragrances.set_size(conn, fragrance_id, size or None)
    return back_to(back, f"/products/{fragrance_id}")


@office.post("/products/{fragrance_id}/merge")
def product_merge(fragrance_id: int, other: int = Form(...)):
    """`other` is the same juice as this fragrance: it merges into this one."""
    conn = connect()
    with conn:
        fragrances.merge(conn, other, fragrance_id)
    return RedirectResponse(f"/products/{fragrance_id}", status_code=303)


@office.post("/products/{fragrance_id}/rename")
def product_rename(fragrance_id: int, name: str = Form(...), concentration: str = Form("")):
    """Correct the name or concentration; merges into the corrected fragrance if it exists."""
    if not name.strip():
        raise HTTPException(400, "a fragrance needs a name")
    conn = connect()
    with conn:
        fragrance_id = fragrances.rename(conn, fragrance_id, name, concentration or None)
    return RedirectResponse(f"/products/{fragrance_id}", status_code=303)


@office.get("/merges")
def merges(request: Request):
    """Fragrances that share an EAN and might be the same juice: merge them or say they differ."""
    conn = connect()
    pairs = fragrances.suggestions(conn)
    ids = {i for p in pairs for i in (p["a_id"], p["b_id"])}
    # Each side's name, list, and which suppliers list it under what name.
    sides = {r["id"]: r for r in conn.execute(
        f"""SELECT f.id, f.name, f.concentration, f.status, f.owned, group_concat(DISTINCT l.supplier) AS suppliers,
                   count(l.sku) AS listings, min(l.name) AS example
            FROM fragrances f LEFT JOIN listings l ON l.fragrance_id = f.id
            WHERE f.id IN ({",".join("?" * len(ids))}) GROUP BY f.id""", list(ids))}
    return templates.TemplateResponse(request, "merges.html", {"pairs": pairs, "sides": sides})


@office.post("/merges")
def merges_post(action: str = Form(...)):
    """action is 'merge:12:34' to merge fragrance 12 into 34, or 'differ:12:34'."""
    kind, first, second = action.split(":")
    conn = connect()
    with conn:
        if kind == "merge":
            fragrances.merge(conn, int(first), int(second))
        else:
            fragrances.mark_not_same(conn, int(first), int(second))
    return RedirectResponse("/merges", status_code=303)


@office.post("/products/{fragrance_id}/split")
def product_split(fragrance_id: int, name: str = Form(...), concentration: str = Form("")):
    """Listings read as name/concentration aren't this fragrance after all."""
    conn = connect()
    with conn:
        fragrances.split(conn, fragrance_id, name, concentration)
    return RedirectResponse(f"/products/{fragrance_id}", status_code=303)


# --- Suppliers and orders --------------------------------------------------------------------

STALE = timedelta(hours=24)  # the schedule runs three times a day: a day without success is wrong


@office.get("/suppliers")
def suppliers(request: Request):
    """Every supplier: whether collecting works, when it last did, and its minimum order."""
    conn = connect()
    saved = {s["name"]: s for s in conn.execute("SELECT * FROM suppliers")}
    stock = {r["supplier"]: r for r in conn.execute(
        "SELECT supplier, sum(qty > 0) AS in_stock, max(last_seen) AS last_seen FROM listings GROUP BY supplier")}
    rows = []
    for name in sorted(SUPPLIERS):
        s, p = saved.get(name), stock.get(name)
        last_ok = (s and s["last_ok_at"]) or (p and p["last_seen"])
        if s and s["last_error"]:
            health = "failed"
        elif not last_ok:
            health = "never"
        elif datetime.now(timezone.utc) - datetime.fromisoformat(last_ok) > STALE:
            health = "stale"
        else:
            health = "ok"
        rows.append({"name": name, "health": health, "last_ok": last_ok, "last_run": s and s["last_run_at"],
                     "error": s and s["last_error"], "mov": s and s["mov"], "in_stock": p["in_stock"] if p else 0})
    return templates.TemplateResponse(request, "suppliers.html", {"rows": rows})


@office.post("/suppliers/{name}/mov")
def supplier_mov(name: str, mov: str = Form("")):
    """Set a supplier's minimum order value; empty means none."""
    if name not in SUPPLIERS:
        raise HTTPException(404, "unknown supplier")
    value = float(mov.replace(",", ".")) if mov.strip() else None
    conn = connect()
    with conn:
        conn.execute("INSERT INTO suppliers (name, mov) VALUES (?, ?) ON CONFLICT (name) DO UPDATE SET mov = excluded.mov",
                     (name, value))
    return RedirectResponse("/suppliers", status_code=303)


@office.get("/orders")
def orders_page(request: Request):
    """The order you could place at each supplier from your wishlist and fillers."""
    return templates.TemplateResponse(request, "orders.html", {"orders": orders.plan(connect())})


app.include_router(office)


# --- Telegram buttons ------------------------------------------------------------------------

LABELS = {"follow": "⭐ Following", "ignore": "🚫 Ignored", "default": "Back to default"}


@app.post("/telegram")
def telegram_tap(update: dict = Body(...), x_telegram_bot_api_secret_token: str = Header("")):
    """A tap on a Follow / Ignore button in the digest: apply it, then replace the buttons with the outcome."""
    if not secrets.compare_digest(x_telegram_bot_api_secret_token, telegram.secret()):
        raise HTTPException(403)
    tap = update.get("callback_query")
    if not tap or str(tap["message"]["chat"]["id"]) != os.environ["TELEGRAM_CHAT_ID"]:
        return {}
    outcome = apply_tap(tap["data"])
    telegram.answer(tap["id"], outcome)
    first_line = tap["message"].get("text", "").splitlines()[0]
    telegram.edit(tap["message"]["chat"]["id"], tap["message"]["message_id"],
                  f"{escape(first_line)}\n<b>→ {escape(outcome)}</b>")
    return {}


def apply_tap(data: str) -> str:
    """'brand:12:follow' or 'merge:12:34'. Returns what happened, in words."""
    conn = connect()
    kind, brand_id, value = data.split(":")
    names = dict(conn.execute("SELECT id, name FROM brands").fetchall())
    if int(brand_id) not in names or (kind == "merge" and int(value) not in names):
        return "Already handled in the backoffice"
    with conn:
        if kind == "merge":
            brands.merge(conn, int(brand_id), int(value))
            return f"Merged into {names[int(value)]}"
        brands.set_status(conn, int(brand_id), value)
        return LABELS[value]
