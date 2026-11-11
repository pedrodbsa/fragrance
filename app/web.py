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
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import brands, orders, telegram
from app.db import connect, upgrade
from app import fragrances
from app.fragrances import CONCENTRATIONS, alerting, hidden, key, matcher, resolver, variant
from app.fragrances import save as fragrance_save
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
    match = matcher(conn)
    recent = conn.execute(
        """SELECT e.*, c.name, c.brand, c.brand_id, c.brand_name, c.status, c.ean, c.price, c.qty
           FROM events e JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku
           WHERE (? = '' OR e.kind = ?) ORDER BY e.id DESC LIMIT ?""",
        (kind, kind, PAGE * 3),
    ).fetchall()
    rows = [r for r in annotate(conn, recent) if not r["hidden"]][:PAGE]
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    day = conn.execute(
        """SELECT e.kind, c.name, c.brand, c.brand_id, c.status FROM events e
           JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku WHERE e.created_at >= ?""", (since,)).fetchall()
    last_day = Counter(r["kind"] for r in day if not hidden(r, match(r)))
    in_stock = conn.execute("SELECT * FROM catalog WHERE qty > 0").fetchall()
    shown = [r for r in in_stock if not hidden(r, match(r))]
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    new_brands = conn.execute(  # brands from a supplier's first run have announced_at = created_at
        """SELECT count(*) FROM brands WHERE status = 'default' AND created_at >= ?
           AND (announced_at IS NULL OR announced_at != created_at)""",
        (week,)).fetchone()[0]
    return templates.TemplateResponse(request, "events.html", {
        "rows": rows, "kind": kind, "last_day": last_day, "in_stock": len(shown),
        "suppliers": len({r["supplier"] for r in shown}), "new_brands": new_brands,
    })


def annotate(conn, listings) -> list[dict]:
    """Catalog rows plus what the stock tables need: the fragrance (juice) each listing is,
    after your merges, the decision covering it, and its product page."""
    match, juice = matcher(conn), resolver(conn)
    rows = []
    for r in listings:
        name, concentration = juice(r)
        decision = match(r)
        page = (f"/products/{decision['id']}" if decision else
                "/fragrance?" + urlencode({"brand": r["brand_id"], "name": name, "concentration": concentration or ""}))
        size, size_label = variant(r["name"])
        rows.append({**dict(r), "decision": decision, "fragrance": name, "concentration": concentration,
                     "page": page, "size": size, "size_label": size_label,
                     "alerting": alerting(r, decision), "hidden": hidden(r, decision)})
    return rows


def group(rows: list[dict]) -> list[dict]:
    """One entry per fragrance (brand + name + concentration), its sizes and testers under it.
    For each size, the cheapest in-stock listing is shown."""
    groups = {}
    for r in rows:
        g = groups.setdefault((r["brand_id"], key(r["fragrance"]), r["concentration"]), {
            **r, "listings": [], "qty": 0, "suppliers": set(), "best": None})
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
        series.append({"label": f"{r['size_label']} {r['concentration'] or ''} · {r['supplier']}".replace("  ", " "), "points": points,
                       "low": min(p for _, p in points)})
    return series


IN_STOCK_FIRST = "ORDER BY qty = 0, name"


@office.get("/stock")
def stock(request: Request, q: str = "", brand: str = "", supplier: str = "",
          in_stock: bool = True, followed: bool = False, everything: bool = False):
    """Everything that isn't ignored, one row per fragrance. 'followed' narrows to what alerts
    you; 'everything' adds what's ignored."""
    conn = connect()
    found = conn.execute(
        """SELECT * FROM catalog
           WHERE (? = '' OR name LIKE '%' || ? || '%' OR ean = ? OR ean2 = ? OR ean3 = ? OR sku = ?)
             AND (? = '' OR brand_id = ?) AND (? = '' OR supplier = ?) AND (NOT ? OR qty > 0)
           ORDER BY brand_name, name""",
        (q, q, q, q, q, q, brand, brand, supplier, supplier, in_stock),
    ).fetchall()
    rows = []
    for r in annotate(conn, found):
        if (everything or not r["hidden"]) and (r["alerting"] or not followed):
            rows.append(r)
    brand_list = conn.execute("SELECT id, name FROM brands WHERE status != 'ignore' ORDER BY name").fetchall()
    suppliers = [r[0] for r in conn.execute("SELECT DISTINCT supplier FROM products ORDER BY supplier")]
    groups = group(rows)
    return templates.TemplateResponse(request, "stock.html", {
        "groups": groups[:PAGE], "total": len(groups), "brands": brand_list, "suppliers": suppliers,
        "q": q, "brand": brand, "supplier": supplier, "in_stock": in_stock, "followed": followed,
        "everything": everything,
    })


# --- Brands ----------------------------------------------------------------------------------

BRAND_ROWS = """
SELECT b.*,
       (SELECT count(*) FROM catalog c WHERE c.brand_id = b.id AND c.qty > 0) AS in_stock,
       (SELECT group_concat(DISTINCT c.supplier) FROM catalog c WHERE c.brand_id = b.id) AS suppliers,
       (SELECT c.name FROM catalog c WHERE c.brand_id = b.id AND c.qty > 0 ORDER BY c.price DESC LIMIT 1) AS example,
       (SELECT count(*) FROM brand_aliases a WHERE a.brand_id = b.id) AS spellings
FROM brands b
"""


@office.get("/new")
def new_brands(request: Request, days: int = 30):
    """Brands first seen recently that you haven't followed or ignored."""
    conn = connect()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        BRAND_ROWS + " WHERE b.status = 'default' AND b.created_at >= ? ORDER BY b.created_at DESC, in_stock DESC, b.name",
        (since,)).fetchall()
    return templates.TemplateResponse(request, "new.html", {
        "rows": rows, "hints": brands.suggestions(conn), "days": days,
    })


@office.post("/new")
def new_brands_post(action: str = Form(...), ids: list[int] = Form([]), back: str = Form("/new")):
    """action is 'follow:12' for one brand, 'follow:selected' for the ticked ones,
    or 'merge:12:34' to merge brand 12 into brand 34."""
    conn = connect()
    kind, *args = action.split(":")
    with conn:
        if kind == "merge":
            brands.merge(conn, int(args[0]), int(args[1]))
        else:
            for brand_id in (ids if args[0] == "selected" else [int(args[0])]):
                brands.set_status(conn, brand_id, kind)
    return back_to(back, "/new")


@office.get("/brands")
def brand_list(request: Request, status: str = "", q: str = ""):
    conn = connect()
    rows = conn.execute(
        BRAND_ROWS + " WHERE (? = '' OR b.status = ?) AND b.name LIKE '%' || ? || '%' ORDER BY b.name",
        (status, status, q),
    ).fetchall()
    counts = dict(conn.execute("SELECT status, count(*) FROM brands GROUP BY status").fetchall())
    return templates.TemplateResponse(request, "brands.html", {
        "rows": rows, "status": status, "q": q, "counts": counts,
    })


@office.get("/brands/{brand_id}")
def brand_detail(request: Request, brand_id: int):
    conn = connect()
    brand = conn.execute(BRAND_ROWS + " WHERE b.id = ?", (brand_id,)).fetchone()
    if brand is None:
        raise HTTPException(404, "brand not found")
    aliases = conn.execute(
        """SELECT a.alias, (SELECT count(*) FROM products p WHERE p.brand = a.alias COLLATE NOCASE) AS products
           FROM brand_aliases a WHERE a.brand_id = ? ORDER BY a.alias""", (brand_id,)).fetchall()
    others = conn.execute("SELECT id, name FROM brands WHERE id != ? ORDER BY name", (brand_id,)).fetchall()
    decided = conn.execute("SELECT * FROM fragrances WHERE brand_id = ? ORDER BY status, name", (brand_id,)).fetchall()
    listings = conn.execute(f"SELECT * FROM catalog WHERE brand_id = ? {IN_STOCK_FIRST}", (brand_id,)).fetchall()
    return templates.TemplateResponse(request, "brand.html", {
        "brand": brand, "aliases": aliases, "others": others, "decided": decided,
        "groups": group(annotate(conn, listings)),
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


# --- Products: your decisions about single fragrances ----------------------------------------

TABS = {"wishlist": "Wishlist", "filler": "Fillers", "owned": "Collection", "ignore": "Ignored"}


@office.get("/products")
def products(request: Request, tab: str = "wishlist"):
    conn = connect()
    match = matcher(conn)
    offers = defaultdict(list)  # decision id -> listings it covers
    for r in conn.execute("SELECT * FROM catalog WHERE qty > 0"):
        decision = match(r)
        if decision:
            offers[decision["id"]].append(r)
    where = "f.owned = 1" if tab == "owned" else "f.status = ?"
    rows = conn.execute(
        f"""SELECT f.*, b.name AS brand_name FROM fragrances f LEFT JOIN brands b ON b.id = f.brand_id
            WHERE {where} ORDER BY b.name, f.name""", () if tab == "owned" else (tab,)).fetchall()
    counts = dict(conn.execute("SELECT status, count(*) FROM fragrances GROUP BY status").fetchall())
    counts["owned"] = conn.execute("SELECT count(*) FROM fragrances WHERE owned = 1").fetchone()[0]
    brand_list = conn.execute("SELECT id, name FROM brands ORDER BY name").fetchall()
    return templates.TemplateResponse(request, "products.html", {
        "rows": [{**dict(r), "offers": sorted(offers[r["id"]], key=lambda o: o["price"] or 0)} for r in rows],
        "tab": tab, "tabs": TABS, "counts": counts, "brands": brand_list, "concentrations": CONCENTRATIONS,
    })


@office.get("/products/{fragrance_id}")
def product_detail(request: Request, fragrance_id: int):
    conn = connect()
    product = conn.execute(
        "SELECT f.*, b.name AS brand_name FROM fragrances f LEFT JOIN brands b ON b.id = f.brand_id WHERE f.id = ?",
        (fragrance_id,)).fetchone()
    if product is None:
        raise HTTPException(404, "product not found")
    candidates = conn.execute(
        f"SELECT * FROM catalog WHERE ? IS NULL OR brand_id = ? {IN_STOCK_FIRST}",
        (product["brand_id"], product["brand_id"])).fetchall()
    rows = [r for r in annotate(conn, candidates) if r["decision"] and r["decision"]["id"] == fragrance_id]
    return product_page(request, conn, product, rows)


def product_page(request, conn, product, rows):
    rows = sorted(rows, key=lambda r: (r["concentration"] or "", r["size"], r["size_label"], r["qty"] == 0, r["price"] or 0))
    brand = conn.execute("SELECT status FROM brands WHERE id = ?", (product["brand_id"],)).fetchone()
    return templates.TemplateResponse(request, "product.html", {
        "product": product, "rows": rows, "history": price_history(conn, rows),
        "brand_status": brand["status"] if brand else "default",
        **(merge_options(conn, product, rows) if product["brand_id"] else {}),
    })


def merge_options(conn, product, rows) -> dict:
    """For the product page's "same juice" panel: names already merged into this fragrance,
    the brand's other fragrances to merge in, and those sharing an EAN with it (a hint only:
    suppliers sometimes reuse an EAN for a different fragrance)."""
    here = (key(product["name"]), product["concentration"] or "")
    merged = conn.execute(
        "SELECT * FROM fragrance_aliases WHERE brand_id = ? AND into_name = ? AND into_concentration = ? ORDER BY name",
        (product["brand_id"], *here)).fetchall()
    listings = conn.execute("SELECT * FROM catalog WHERE brand_id = ?", (product["brand_id"],)).fetchall()
    others = [g for g in group(annotate(conn, listings)) if (key(g["fragrance"]), g["concentration"] or "") != here]
    eans = {e for r in rows for e in (r["ean"], r["ean2"], r["ean3"]) if e}
    shared = [g for g in others if eans & {e for r in g["listings"] for e in (r["ean"], r["ean2"], r["ean3"]) if e}]
    return {"merged": merged, "others": sorted(others, key=lambda g: g["fragrance"]), "shared": shared}


@office.post("/fragrances/merge")
def fragrance_merge(brand_id: int = Form(...), name: str = Form(...), concentration: str = Form(""),
                    into_name: str = Form(...), into_concentration: str = Form(""), back: str = Form(...)):
    """name/concentration is the same juice as into_name/into_concentration."""
    conn = connect()
    with conn:
        fragrances.merge(conn, brand_id, name, concentration or None, into_name, into_concentration or None)
    return back_to(back, "/products")


@office.post("/fragrances/split")
def fragrance_split(brand_id: int = Form(...), name: str = Form(...), concentration: str = Form(""), back: str = Form(...)):
    conn = connect()
    with conn:
        fragrances.split(conn, brand_id, name, concentration or None)
    return back_to(back, "/products")


@office.get("/fragrance")
def fragrance_page(request: Request, brand: int, name: str, concentration: str = ""):
    """Page for any fragrance seen in stock, decided on or not. Once there's a decision
    covering it, its product page takes over."""
    conn = connect()
    listings = conn.execute(f"SELECT * FROM catalog WHERE brand_id = ? {IN_STOCK_FIRST}", (brand,)).fetchall()
    rows = [r for r in annotate(conn, listings)
            if key(r["fragrance"]) == key(name) and (r["concentration"] or "") == concentration]
    decided = next((r["decision"] for r in rows if r["decision"]), None)
    if decided:
        return RedirectResponse(f"/products/{decided['id']}", status_code=303)
    brand_row = conn.execute("SELECT name FROM brands WHERE id = ?", (brand,)).fetchone()
    if brand_row is None:
        raise HTTPException(404, "brand not found")
    product = {"id": None, "brand_id": brand, "brand_name": brand_row["name"], "name": name,
               "concentration": concentration or None, "status": "default", "owned": 0, "note": None}
    return product_page(request, conn, product, rows)


@office.post("/products")
def product_save(name: str = Form(...), brand_id: str = Form(""), concentration: str = Form(""),
                 status: str = Form(""), owned: str = Form(""), note: str = Form(""), back: str = Form("/products")):
    """Put a fragrance on the wishlist, fillers or ignored, or off them (status), or put it in or out of your collection
    (owned = 1 / 0). Fields left empty keep their current value."""
    if not name.strip():
        raise HTTPException(400, "a product needs a name")
    conn = connect()
    with conn:
        fragrance_save(conn, int(brand_id) if brand_id else None, name, concentration or None,
                       status=status or None, owned=(owned == "1") if owned else None, note=note.strip() or None)
    # Back on default and out of the collection, a fragrance's own page is gone: show it
    # as any other fragrance from stock instead.
    page = re.fullmatch(r"/products/(\d+)", back)
    if page and not conn.execute("SELECT 1 FROM fragrances WHERE id = ?", (int(page[1]),)).fetchone():
        back = ("/fragrance?" + urlencode({"brand": brand_id, "name": name, "concentration": concentration})
                if brand_id else "/products")
    return back_to(back, "/products")


@office.post("/products/{fragrance_id}/size")
def product_size(fragrance_id: int, size: str = Form(""), back: str = Form(...)):
    """The size you'd buy; empty buys the cheapest. Order suggestions use it."""
    conn = connect()
    with conn:
        fragrances.set_size(conn, fragrance_id, size or None)
    return back_to(back, f"/products/{fragrance_id}")


# --- Suppliers and orders --------------------------------------------------------------------

STALE = timedelta(hours=24)  # the schedule runs three times a day: a day without success is wrong


@office.get("/suppliers")
def suppliers(request: Request):
    """Every supplier: whether collecting works, when it last did, and its minimum order."""
    conn = connect()
    saved = {s["name"]: s for s in conn.execute("SELECT * FROM suppliers")}
    stock = {r["supplier"]: r for r in conn.execute(
        "SELECT supplier, sum(qty > 0) AS in_stock, max(last_seen) AS last_seen FROM products GROUP BY supplier")}
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
