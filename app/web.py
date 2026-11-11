"""Backoffice: browse stock and changes, edit watch and mute rules.

Run: uvicorn app.web:app. Protected by HTTP basic auth (BACKOFFICE_USER, BACKOFFICE_PASSWORD).
"""

import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import connect
from app.rules import FIELDS, any_match

security = HTTPBasic()


def login(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    user_ok = secrets.compare_digest(credentials.username, os.environ["BACKOFFICE_USER"])
    password_ok = secrets.compare_digest(credentials.password, os.environ["BACKOFFICE_PASSWORD"])
    if not (user_ok and password_ok):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


here = Path(__file__).parent
app = FastAPI(dependencies=[Depends(login)], docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=here / "static"), name="static")
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


@app.get("/")
def events(request: Request, kind: str = ""):
    conn = connect()
    rows = conn.execute(
        """SELECT e.*, p.name, p.brand, p.ean, p.price, p.qty
           FROM events e JOIN products p ON p.supplier = e.supplier AND p.sku = e.sku
           WHERE ? = '' OR e.kind = ? ORDER BY e.id DESC LIMIT ?""",
        (kind, kind, PAGE),
    ).fetchall()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    last_day = dict(conn.execute("SELECT kind, count(*) FROM events WHERE created_at >= ? GROUP BY kind", (since,)).fetchall())
    tracked = conn.execute("SELECT count(*), count(DISTINCT supplier) FROM products WHERE qty > 0").fetchone()
    return templates.TemplateResponse(request, "events.html", {
        "rows": rows, "kind": kind, "last_day": last_day, "in_stock": tracked[0], "suppliers": tracked[1],
    })


@app.get("/products")
def products(request: Request, q: str = "", brand: str = "", supplier: str = "", in_stock: bool = True):
    conn = connect()
    where = """WHERE (? = '' OR name LIKE '%' || ? || '%' OR ean = ? OR ean2 = ? OR ean3 = ? OR sku = ?)
                 AND (? = '' OR brand = ? COLLATE NOCASE)
                 AND (? = '' OR supplier = ?)
                 AND (NOT ? OR qty > 0)"""
    params = (q, q, q, q, q, q, brand, brand, supplier, supplier, in_stock)
    rows = conn.execute(f"SELECT * FROM products {where} ORDER BY brand, name LIMIT ?", (*params, PAGE)).fetchall()
    total = conn.execute(f"SELECT count(*) FROM products {where}", params).fetchone()[0]
    watch = conn.execute("SELECT * FROM rules WHERE action = 'watch'").fetchall()
    mute = conn.execute("SELECT * FROM rules WHERE action = 'mute'").fetchall()
    marked = [{**dict(r), "watched": any_match(watch, r), "muted": any_match(mute, r)} for r in rows]
    brands = [r[0] for r in conn.execute("SELECT DISTINCT brand FROM products ORDER BY brand")]
    suppliers = [r[0] for r in conn.execute("SELECT DISTINCT supplier FROM products ORDER BY supplier")]
    return templates.TemplateResponse(request, "products.html", {
        "rows": marked, "total": total, "brands": brands, "suppliers": suppliers,
        "q": q, "brand": brand, "supplier": supplier, "in_stock": in_stock,
    })


@app.get("/rules")
def rules(request: Request):
    rows = connect().execute("SELECT * FROM rules ORDER BY field, value").fetchall()
    return templates.TemplateResponse(request, "rules.html", {
        "watch": [r for r in rows if r["action"] == "watch"],
        "mute": [r for r in rows if r["action"] == "mute"],
        "fields": FIELDS,
    })


@app.post("/rules")
def add_rule(action: str = Form(...), field: str = Form(...), value: str = Form(...),
             note: str = Form(""), back: str = Form("/rules")):
    if action not in ("watch", "mute") or field not in FIELDS or not value.strip():
        raise HTTPException(400, "invalid rule")
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO rules (action, field, value, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (action, field, value.strip(), note.strip() or None,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return RedirectResponse(back if back.startswith("/") else "/rules", status_code=303)


@app.post("/rules/{rule_id}/delete")
def delete_rule(rule_id: int):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    return RedirectResponse("/rules", status_code=303)
