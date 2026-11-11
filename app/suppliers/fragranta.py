"""fragranta.eu: logged in as your B2B account, download their Excel catalogue, the same file
the site's "download catalogue" gives you (https://fragranta.eu/en/catalogue). Logged out,
the site hides stock and prices, so the login is needed.
Env: SUPPLIER_FRAGRANTA_EMAIL, SUPPLIER_FRAGRANTA_PASSWORD.

The login is their own email + password form: the tracker opens the login page, sends the
form back with your details, and keeps the session cookie for the download.

The catalogue lists every product in stock (about 2,500), a quarter of it cosmetics and hair
care. Kept: perfumes (anything named as an eau de parfum, eau de toilette, extrait, parfum or
cologne) and perfume gift sets; left out: deodorants, body and hair mists, shower gels, after
shaves, candles and diffusers. A promo price, when there is one, is the price.

The sheet starts with a few lines of notes; the table's header row starts with "EAN":
  EAN | SKU | Brand | Product Name | New Item | Stock | Net Price | Promo Price | …
  0085715166722 | 25154 | Abercrombie & Fitch | Abercrombie & Fitch 100% Passion Men Eau de Toilette 30ml | | 14 | 17.42 | |
"""

import html
import io
import os
import re

import httpx
import openpyxl

from app.item import Item

SITE = "https://fragranta.eu"
PERFUME = re.compile(r"eau de|\bed[pt]\b|\bedc\b|parfum|extrait|cologne", re.I)
NOT_PERFUME = re.compile(r"deo|deodorant|body spray|body mist|hair mist|shower|after ?shave|lotion|"
                         r"candle|diffuser|sample|vial|miniature", re.I)
GIFT_SET = re.compile(r"\bset\b", re.I)


def fetch() -> list[Item]:
    with httpx.Client(base_url=SITE, follow_redirects=True, timeout=120) as client:
        log_in(client)
        response = client.get("/en/catalogue")
        if "spreadsheet" not in response.headers.get("content-type", ""):
            raise RuntimeError(f"fragranta catalogue: no Excel file (HTTP {response.status_code})")
        return parse(response.content)


def log_in(client: httpx.Client) -> None:
    """Fill in the login form the way a browser does: its hidden fields, plus your details."""
    page = client.get("/en/login").text
    form = re.search(r'<form aria-label="Partner login".*?</form>', page, re.S)
    if form is None:
        raise RuntimeError("fragranta login: the login form wasn't found (has the site changed?)")
    fields = {html.unescape(name): html.unescape(value) for name, value in
              re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"(?:[^>]*value="([^"]*)")?', form.group(0))}
    fields.update(email=os.environ["SUPPLIER_FRAGRANTA_EMAIL"], password=os.environ["SUPPLIER_FRAGRANTA_PASSWORD"])
    client.post("/en/login", files={name: (None, value) for name, value in fields.items()})
    if "fr_customer" not in client.cookies:
        raise RuntimeError("fragranta login failed: check SUPPLIER_FRAGRANTA_EMAIL and SUPPLIER_FRAGRANTA_PASSWORD")


def parse(xlsx: bytes) -> list[Item]:
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True).worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    for row in rows:  # skip the notes above the table
        if row and row[0] == "EAN":
            columns = {name: i for i, name in enumerate(row) if name}
            break
    else:
        raise RuntimeError("fragranta catalogue: the table's header row wasn't found")
    items = []
    for row in rows:
        value = lambda name: row[columns[name]]
        name = " ".join(str(value("Product Name") or "").split())  # also turns odd spaces into plain ones
        qty = int(value("Stock") or 0)
        price = float(value("Promo Price") or value("Net Price") or 0)
        is_set = bool(GIFT_SET.search(name))
        if not PERFUME.search(name) or (NOT_PERFUME.search(name) and not is_set) or qty <= 0 or price <= 0:
            continue
        brand = str(value("Brand")).strip()
        if name.lower().startswith(brand.lower() + " "):
            name = name[len(brand):].strip()  # the brand has its own column, like the other suppliers
        if is_set:
            # "Chrome Gift Set Eau de Toilette 100ml + 2x Shower Gel 75ml" -> "Chrome Eau de
            # Toilette 100ml + 2x Shower Gel 75ml Set", so the fragrance is read from the perfume.
            name = re.sub(r"\s*\bgift set\b|\s*\bset\b", "", name, count=1, flags=re.I).strip() + " Set"
        ean = str(value("EAN") or "").strip()
        items.append(Item(
            sku=str(value("SKU")),
            name=name,
            brand=brand,
            ean=ean or None,
            ean2=None,
            ean3=None,
            qty=qty,
            price=price,
            flagged_new=value("New Item") == "New",
        ))
    return items
