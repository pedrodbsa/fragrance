"""Backoffice: browse stock and changes, triage and manage brands, and decide on single
fragrances (want / own / not interested).
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

from app import brands, telegram
from app.db import connect, upgrade
from app.fragrances import CONCENTRATIONS, STATUSES, hidden, identify, key, matcher
from app.fragrances import save as fragrance_save

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
           WHERE c.status != 'ignore' AND (? = '' OR e.kind = ?) ORDER BY e.id DESC LIMIT ?""",
        (kind, kind, PAGE * 3),
    ).fetchall()
    rows = [r for r in annotate(recent, match) if not hidden(r, r["decision"])][:PAGE]
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    day = conn.execute(
        """SELECT e.kind, c.name, c.brand, c.brand_id, c.status FROM events e
           JOIN catalog c ON c.supplier = e.supplier AND c.sku = e.sku WHERE e.created_at >= ?""", (since,)).fetchall()
    last_day = Counter(r["kind"] for r in day if not hidden(r, match(r)))
    in_stock = conn.execute("SELECT * FROM catalog WHERE qty > 0").fetchall()
    shown = [r for r in in_stock if not hidden(r, match(r))]
    to_triage = conn.execute("SELECT count(*) FROM brands WHERE status = 'new'").fetchone()[0]
    return templates.TemplateResponse(request, "events.html", {
        "rows": rows, "kind": kind, "last_day": last_day, "in_stock": len(shown),
        "suppliers": len({r["supplier"] for r in shown}), "to_triage": to_triage,
    })


def annotate(listings, match) -> list[dict]:
    """Catalog rows plus what the stock tables need: the fragrance decision covering each
    listing, the fragrance name and concentration read from it, and its product page."""
    rows = []
    for r in listings:
        name, concentration = identify(r["name"], r["brand"])
        decision = match(r)
        page = (f"/products/{decision['id']}" if decision else
                "/fragrance?" + urlencode({"brand": r["brand_id"], "name": name, "concentration": concentration or ""}))
        rows.append({**dict(r), "decision": decision, "fragrance": name, "concentration": concentration, "page": page})
    return rows


IN_STOCK_FIRST = "ORDER BY qty = 0, name"


@office.get("/stock")
def stock(request: Request, q: str = "", brand: str = "", supplier: str = "",
          in_stock: bool = True, followed: bool = False, everything: bool = False):
    """Listings from brands you follow or browse and fragrances you want or own.
    'followed' narrows to what alerts you; 'everything' adds what's hidden."""
    conn = connect()
    match = matcher(conn)
    found = conn.execute(
        """SELECT * FROM catalog
           WHERE (? = '' OR name LIKE '%' || ? || '%' OR ean = ? OR ean2 = ? OR ean3 = ? OR sku = ?)
             AND (? = '' OR brand_id = ?) AND (? = '' OR supplier = ?) AND (NOT ? OR qty > 0)
           ORDER BY brand_name, name""",
        (q, q, q, q, q, q, brand, brand, supplier, supplier, in_stock),
    ).fetchall()
    rows = []
    for r in annotate(found, match):
        alerting = r["decision"]["status"] == "want" if r["decision"] else r["status"] == "follow"
        if (everything or not hidden(r, r["decision"])) and (alerting or not followed):
            rows.append(r)
    brand_list = conn.execute("SELECT id, name FROM brands WHERE status != 'ignore' ORDER BY name").fetchall()
    suppliers = [r[0] for r in conn.execute("SELECT DISTINCT supplier FROM products ORDER BY supplier")]
    return templates.TemplateResponse(request, "stock.html", {
        "rows": rows[:PAGE], "total": len(rows), "brands": brand_list, "suppliers": suppliers,
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


@office.get("/triage")
def triage(request: Request):
    conn = connect()
    rows = conn.execute(BRAND_ROWS + " WHERE b.status = 'new' ORDER BY in_stock DESC, b.name").fetchall()
    return templates.TemplateResponse(request, "triage.html", {
        "rows": rows, "hints": brands.suggestions(conn),
    })


@office.post("/triage")
def triage_post(action: str = Form(...), ids: list[int] = Form([])):
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
    return RedirectResponse("/triage", status_code=303)


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
        "rows": annotate(listings, matcher(conn)),
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

@office.get("/products")
def products(request: Request, status: str = "want"):
    conn = connect()
    match = matcher(conn)
    offers = defaultdict(list)  # decision id -> listings it covers
    for r in conn.execute("SELECT * FROM catalog WHERE qty > 0"):
        decision = match(r)
        if decision:
            offers[decision["id"]].append(r)
    rows = conn.execute(
        """SELECT f.*, b.name AS brand_name FROM fragrances f LEFT JOIN brands b ON b.id = f.brand_id
           WHERE f.status = ? ORDER BY b.name, f.name""", (status,)).fetchall()
    counts = dict(conn.execute("SELECT status, count(*) FROM fragrances GROUP BY status").fetchall())
    brand_list = conn.execute("SELECT id, name FROM brands ORDER BY name").fetchall()
    return templates.TemplateResponse(request, "products.html", {
        "rows": [{**dict(r), "offers": sorted(offers[r["id"]], key=lambda o: o["price"] or 0)} for r in rows],
        "status": status, "counts": counts, "brands": brand_list, "concentrations": CONCENTRATIONS,
    })


@office.get("/products/{fragrance_id}")
def product_detail(request: Request, fragrance_id: int):
    conn = connect()
    product = conn.execute(
        "SELECT f.*, b.name AS brand_name FROM fragrances f LEFT JOIN brands b ON b.id = f.brand_id WHERE f.id = ?",
        (fragrance_id,)).fetchone()
    if product is None:
        raise HTTPException(404, "product not found")
    match = matcher(conn)
    candidates = conn.execute(
        f"SELECT * FROM catalog WHERE ? IS NULL OR brand_id = ? {IN_STOCK_FIRST}",
        (product["brand_id"], product["brand_id"])).fetchall()
    rows = [r for r in annotate(candidates, match) if r["decision"] and r["decision"]["id"] == fragrance_id]
    return templates.TemplateResponse(request, "product.html", {"product": product, "rows": rows})


@office.get("/fragrance")
def fragrance_page(request: Request, brand: int, name: str, concentration: str = ""):
    """Page for any fragrance seen in stock, decided on or not. Once there's a decision
    covering it, its product page takes over."""
    conn = connect()
    match = matcher(conn)
    listings = conn.execute(f"SELECT * FROM catalog WHERE brand_id = ? {IN_STOCK_FIRST}", (brand,)).fetchall()
    rows = [r for r in annotate(listings, match)
            if key(r["fragrance"]) == key(name) and (r["concentration"] or "") == concentration]
    decided = next((r["decision"] for r in rows if r["decision"]), None)
    if decided:
        return RedirectResponse(f"/products/{decided['id']}", status_code=303)
    brand_row = conn.execute("SELECT name FROM brands WHERE id = ?", (brand,)).fetchone()
    if brand_row is None:
        raise HTTPException(404, "brand not found")
    product = {"id": None, "brand_id": brand, "brand_name": brand_row["name"], "name": name,
               "concentration": concentration or None, "status": None, "note": None}
    return templates.TemplateResponse(request, "product.html", {"product": product, "rows": rows})


@office.post("/products")
def product_save(name: str = Form(...), status: str = Form(...), brand_id: str = Form(""),
                 concentration: str = Form(""), note: str = Form(""), back: str = Form("/products")):
    if not name.strip():
        raise HTTPException(400, "a product needs a name")
    conn = connect()
    with conn:
        fragrance_save(conn, int(brand_id) if brand_id else None, name, concentration or None, status, note.strip() or None)
    return back_to(back, "/products")


@office.post("/products/{fragrance_id}/status")
def product_status(fragrance_id: int, status: str = Form(...), back: str = Form("/products")):
    if status not in STATUSES:
        raise HTTPException(400, "unknown status")
    conn = connect()
    with conn:
        conn.execute("UPDATE fragrances SET status = ? WHERE id = ?", (status, fragrance_id))
    return back_to(back, "/products")


@office.post("/products/{fragrance_id}/delete")
def product_delete(fragrance_id: int, back: str = Form("/products")):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM fragrances WHERE id = ?", (fragrance_id,))
    gone = back.split("?")[0] == f"/products/{fragrance_id}"  # its own page no longer exists
    return back_to("/products" if gone else back, "/products")


app.include_router(office)


# --- Telegram buttons ------------------------------------------------------------------------

LABELS = {"follow": "⭐ Following", "browse": "👀 Browsing", "ignore": "🚫 Ignored"}


@app.post("/telegram")
def telegram_tap(update: dict = Body(...), x_telegram_bot_api_secret_token: str = Header("")):
    """A tap on a triage button in the digest: apply it, then replace the buttons with the outcome."""
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
