"""symphonya.eu: a JSON API, opened with an API key in the address. Only the read-only product
call is used; their order, address and checkout calls are deliberately left alone.
  https://www.symphonya.eu/api/getProducts/{key}?cat=fragrance&lang=en
Env: SUPPLIER_SYMPHONYA_KEY.

One call returns every fragrance product in stock (about 11,700) with its price and quantity.
Kept: perfumes and perfume sets, boxed or tester; left out: vials, miniatures, samples, body
mists, hair mists, oils and accessories.

A product looks like this (the name is a comma-separated list: brand, fragrance, concentration,
who it's for, size, then "*Tester" for testers):
  {"id": "113", "brand": "Salvatore Ferragamo", "ean": "8052464890194",
   "name": "Salvatore Ferragamo, F By Ferragamo, Eau De Toilette, For Men, 100 ml *Tester",
   "gender": "For Men", "presentation": "Tester", "category": "Fragrance",
   "subcategory": "Perfumes", "subsubcategory": "Eau De Toilette", "price": "19.90", "stock": 1}
Sets are named "Set Ikks: Little Woman, Eau De Toilette, For Women, 100 ml + Little Woman, …".
"""

import os
import re

import httpx

from app.item import Item

API = "https://www.symphonya.eu/api/getProducts"
KEPT_KINDS = {"Eau De Parfum", "Eau De Toilette", "Extrait De Parfum", "Parfum", "Eau De Cologne",
              "Eau Fraiche", "Perfume Set"}  # their subsubcategory
KEPT_PRESENTATIONS = {"Regular", "Tester"}
PERFUME = re.compile(r"eau de|parfum|extrait|cologne|eau fraiche", re.I)
AUDIENCES = {"For Men": "man", "For Women": "woman", "Women": "woman", "Unisex": "unisex"}  # their gender field


def fetch() -> list[Item]:
    response = httpx.get(f"{API}/{os.environ['SUPPLIER_SYMPHONYA_KEY']}",
                         params={"cat": "fragrance", "lang": "en"}, timeout=300)
    if response.status_code != 200:
        # Said without the URL: it carries the key, and errors show on the Suppliers page.
        raise RuntimeError(f"symphonya products: HTTP {response.status_code}")
    body = response.json()
    if body.get("error"):
        raise RuntimeError(f"symphonya products: {body.get('errorMessage')}")
    return parse(body["response"])


def parse(products: list[dict]) -> list[Item]:
    items = []
    for p in products:
        price, qty = float(p.get("price") or 0), int(p.get("stock") or 0)
        if (p.get("subsubcategory") not in KEPT_KINDS or p.get("presentation") not in KEPT_PRESENTATIONS
                or price <= 0 or qty <= 0):
            continue
        brand = p["brand"].strip()
        items.append(Item(
            sku=str(p["id"]),
            name=readable(p["name"], brand),
            brand=brand,
            ean=(p.get("clean-ean") or p.get("ean") or "").strip() or None,
            ean2=None,
            ean3=None,
            qty=qty,
            price=price,
            flagged_new=False,
            audience=AUDIENCES.get(p.get("gender")),
        ))
    return items


def readable(name: str, brand: str) -> str:
    """Their name written the way the rest of the app reads names:
    "Hugo Boss, Boss Selection, Eau De Toilette, For Men, 90 ml *Tester" ->
    "Boss Selection Eau De Toilette 90 ml Tester"; "Set Ikks: Little Woman, Eau De Toilette, …
    100 ml + …" -> "Little Woman Eau De Toilette … 100 ml + … Set", perfume first."""
    is_set = name.startswith("Set ") and ":" in name
    if is_set:
        name = name.split(":", 1)[1]
    parts = [part.strip().lstrip("*") for part in name.replace("*", ", *").split(",")]
    if parts and parts[0].lower() == brand.lower():
        parts = parts[1:]  # the brand has its own field, like the other suppliers
    words = " ".join(part for part in parts if part and part not in AUDIENCES)
    if not is_set:
        return words
    # A set's perfume goes first, so the fragrance is read from it, not from a shower gel.
    pieces = [piece.strip() for piece in words.split(" + ")]
    pieces.sort(key=lambda piece: not PERFUME.search(piece))
    return " + ".join(pieces) + " Set"
