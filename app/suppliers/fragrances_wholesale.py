"""fragrances-wholesale.eu publishes its whole catalogue as one XML file:
  /generator/catalog/xml?token=…
Env: SUPPLIER_FRAGRANCES_WHOLESALE_TOKEN.

Its sister shop wholesale-fragrances.eu lists the same products from the same stock, about
0.8% dearer, so it isn't collected (dropped on 2026-11-11).

The catalogue holds about 36,000 products, mostly cosmetics. Only perfumes, testers and gift
sets are kept, and only what's in stock.

Each product looks like this (NAME has no brand and no size):
  <PRODUCT><ID>204855</ID><TYPE>Perfume</TYPE><MANUFACTURER>24 perfumes and colognes</MANUFACTURER>
    <NAME>Gold EDT</NAME><SIZE>50ml</SIZE><EANS><EAN>3760048937030</EAN></EANS>
    <SEX>U</SEX><PRICE>15.42</PRICE><STOCK>4</STOCK></PRODUCT>
SEX is who it's for: M (men), W (women), U (unisex).
"""

import os
import re
import xml.etree.ElementTree as ET

import httpx

from app.item import Item

KEPT_TYPES = {"Perfume", "Tester", "Gift Set"}
AUDIENCES = {"M": "man", "W": "woman", "U": "unisex"}  # their SEX field


def fetch() -> list[Item]:
    return parse(download("https://www.fragrances-wholesale.eu", os.environ["SUPPLIER_FRAGRANCES_WHOLESALE_TOKEN"]))


def download(base: str, token: str) -> bytes:
    response = httpx.get(f"{base}/generator/catalog/xml", params={"token": token}, timeout=300, follow_redirects=True)
    if response.status_code != 200:
        # Said without the URL: it carries the token, and errors show on the Suppliers page.
        raise RuntimeError(f"{base} catalogue: HTTP {response.status_code}")
    return response.content


def parse(xml: bytes) -> list[Item]:
    items = []
    for product in ET.fromstring(xml).iter("PRODUCT"):
        kind = product.findtext("TYPE")
        qty = int(product.findtext("STOCK") or 0)
        if kind not in KEPT_TYPES or qty <= 0:
            continue
        # Written the way the rest of the app reads names: "Gold EDT 50 ml", "… Tester".
        name = product.findtext("NAME").strip()
        size = re.sub(r"(\d)\s*(ml|g|gr|oz)$", r"\1 \2", (product.findtext("SIZE") or "").strip(), flags=re.I)
        if size and size.lower().replace(" ", "") not in name.lower().replace(" ", ""):
            name = f"{name} {size}"
        if kind == "Tester" and "tester" not in name.lower():
            name += " Tester"
        eans = [e.text.strip() for e in product.iterfind("EANS/EAN") if e.text and e.text.strip()]
        items.append(Item(
            sku=product.findtext("ID"),
            name=name,
            brand=product.findtext("MANUFACTURER").strip(),
            ean=eans[0] if eans else None,
            ean2=eans[1] if len(eans) > 1 else None,
            ean3=eans[2] if len(eans) > 2 else None,
            qty=qty,
            price=float(product.findtext("PRICE")),
            flagged_new=False,
            audience=AUDIENCES.get(product.findtext("SEX")),
        ))
    return items
