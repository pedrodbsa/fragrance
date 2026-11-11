"""Backoffice: browse stock and changes, edit watch and mute rules.

Run: uvicorn app.web:app. Protected by HTTP basic auth (BACKOFFICE_USER, BACKOFFICE_PASSWORD).
"""

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.db import connect
from app.rules import FIELDS

security = HTTPBasic()


def login(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    user_ok = secrets.compare_digest(credentials.username, os.environ["BACKOFFICE_USER"])
    password_ok = secrets.compare_digest(credentials.password, os.environ["BACKOFFICE_PASSWORD"])
    if not (user_ok and password_ok):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


app = FastAPI(dependencies=[Depends(login)], docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
PAGE = 200


@app.get("/")
def events(request: Request, kind: str = ""):
    rows = connect().execute(
        """SELECT e.*, p.name, p.brand, p.ean, p.price, p.qty
           FROM events e JOIN products p ON p.supplier = e.supplier AND p.sku = e.sku
           WHERE ? = '' OR e.kind = ? ORDER BY e.id DESC LIMIT ?""",
        (kind, kind, PAGE),
    ).fetchall()
    return templates.TemplateResponse(request, "events.html", {"rows": rows, "kind": kind})


@app.get("/products")
def products(request: Request, q: str = "", brand: str = "", supplier: str = "", in_stock: bool = True):
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM products
           WHERE (? = '' OR name LIKE '%' || ? || '%' OR ean = ? OR ean2 = ? OR ean3 = ? OR sku = ?)
             AND (? = '' OR brand = ? COLLATE NOCASE)
             AND (? = '' OR supplier = ?)
             AND (NOT ? OR qty > 0)
           ORDER BY brand, name LIMIT ?""",
        (q, q, q, q, q, q, brand, brand, supplier, supplier, in_stock, PAGE),
    ).fetchall()
    brands = [r[0] for r in conn.execute("SELECT DISTINCT brand FROM products ORDER BY brand")]
    suppliers = [r[0] for r in conn.execute("SELECT DISTINCT supplier FROM products ORDER BY supplier")]
    return templates.TemplateResponse(request, "products.html", {
        "rows": rows, "brands": brands, "suppliers": suppliers,
        "q": q, "brand": brand, "supplier": supplier, "in_stock": in_stock, "page": PAGE,
    })


@app.get("/rules")
def rules(request: Request):
    rows = connect().execute("SELECT * FROM rules ORDER BY action, field, value").fetchall()
    return templates.TemplateResponse(request, "rules.html", {"rows": rows, "fields": FIELDS})


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
