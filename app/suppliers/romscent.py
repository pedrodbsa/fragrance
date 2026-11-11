"""romscent.com: logged in as your B2B account, download the Excel price list the site's
"Stock export" page gives you (https://romscent.com/frontend/stock-export). The page asks the
site where your list is (it depends on your customer price group), then downloads it.
Env: SUPPLIER_ROMSCENT_EMAIL, SUPPLIER_ROMSCENT_PASSWORD.

About 1,300 products in stock, nearly all perfumes. Kept: men's, women's and unisex perfumes
and perfume gift sets; left out: deodorants, body lotions, shower gels and cosmetics.
Stock above 120 shows as "120+", read as 120.

The sheet's columns:
  Product Ids | EAN | Main Category | Subcategory | Products | Manufacturers | STOCK | Price | Order
  307345 | 6290171002284 | Perfume | Women's fragrances | Rare Tiffany Eau de Parfum 100ml | Afnan | 120+ | 17.5 | 0
"""

import io
import os
import re

import httpx
import openpyxl

from app.item import Item

SITE = "https://romscent.com"
# Their subcategory says who it's for; only these perfume subcategories are kept.
KEPT = {"Men's fragrances": "man", "Women's fragrances": "woman", "Unisex fragrances": "unisex",
        "Fragrances gift sets": None, "Parfumuri": None}


def fetch() -> list[Item]:
    with httpx.Client(base_url=SITE, follow_redirects=True, timeout=120) as client:
        log_in(client)
        where = client.get("/api/client/get-xls-prices-export-url", headers={"Accept": "application/json"})
        if where.status_code != 200:
            raise RuntimeError(f"romscent price list: HTTP {where.status_code} asking where it is")
        response = client.get(where.json()["url"])
        if "spreadsheet" not in response.headers.get("content-type", ""):
            raise RuntimeError(f"romscent price list: no Excel file (HTTP {response.status_code})")
        return parse(response.content)


def log_in(client: httpx.Client) -> None:
    """Fill in the login form the way a browser does: its security token, plus your details."""
    token = re.search(r'name="_token" value="([^"]+)"', client.get("/").text)
    if token is None:
        raise RuntimeError("romscent login: the login form wasn't found (has the site changed?)")
    response = client.post("/login", data={"_token": token.group(1), "email": os.environ["SUPPLIER_ROMSCENT_EMAIL"],
                                           "password": os.environ["SUPPLIER_ROMSCENT_PASSWORD"]})
    if "/frontend" not in str(response.url):  # a wrong password lands back on the login page
        raise RuntimeError("romscent login failed: check SUPPLIER_ROMSCENT_EMAIL and SUPPLIER_ROMSCENT_PASSWORD")


def parse(xlsx: bytes) -> list[Item]:
    rows = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
    columns = {name: i for i, name in enumerate(next(rows)) if name}
    items = []
    for row in rows:
        value = lambda name: row[columns[name]]
        subcategory = value("Subcategory")
        brand = str(value("Manufacturers") or "").strip()
        qty = int(re.sub(r"\D", "", str(value("STOCK") or "")) or 0)  # "120+" -> 120
        price = float(value("Price") or 0)
        if value("Main Category") != "Perfume" or subcategory not in KEPT or not brand or qty <= 0 or price <= 0:
            continue
        name = " ".join(str(value("Products")).split())
        if subcategory == "Fragrances gift sets" and "set" not in name.lower():
            name += " Set"
        ean = str(value("EAN") or "").strip()
        items.append(Item(
            sku=str(value("Product Ids")),
            name=name,
            brand=brand,
            ean=ean or None,
            ean2=None,
            ean3=None,
            qty=qty,
            price=price,
            flagged_new=False,
            audience=KEPT[subcategory],
        ))
    return items
