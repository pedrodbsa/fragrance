"""parfumcompany.pl: one XML file with every product in stock, opened with a token.
  https://parfumcompany.pl/en/xml/dropshipping.xml?token=…&mode=xml
Env: SUPPLIER_PARFUMCOMPANY_TOKEN.

About 4,700 products, half of them perfumery. Kept: eau de parfum, eau de toilette, extraits,
parfums, colognes and perfume sets, testers included; left out: miniatures, body mists,
oils, candles, diffusers and cosmetics. Prices are in euros, without VAT.

A product looks like this (the name starts with the brand):
  <product><name>Abercrombie &amp; Fitch Away Woman Edp 100ml</name><ean>085715169808</ean>
    <stock>5</stock><sku>10059398</sku><producer>Abercrombie &amp; Fitch</producer>
    <parameters><parameter><name>Size</name><value>full-sized product</value></parameter>…</parameters>
    <features><feature><name>Type</name><value>eau de parfum</value></feature>
      <feature><name>Tester</name><value>no</value></feature>
      <feature><name>For whom</name><value>women's</value></feature>…</features>
    <prices><default><price_net>25.06</price_net><currency>€</currency></default></prices></product>
"""

import os
import xml.etree.ElementTree as ET

import httpx

from app.item import Item

URL = "https://parfumcompany.pl/en/xml/dropshipping.xml"
KEPT_TYPES = {"eau de parfum", "eau de toilette", "perfumes extract", "perfumes", "perfumes essence",
              "eau de cologne", "perfumes set"}  # their Type feature
AUDIENCES = {"men's": "man", "women's": "woman", "unisex": "unisex"}  # their "For whom" feature


def fetch() -> list[Item]:
    response = httpx.get(URL, params={"token": os.environ["SUPPLIER_PARFUMCOMPANY_TOKEN"], "mode": "xml"},
                         timeout=300, follow_redirects=True)
    if response.status_code != 200:
        # Said without the URL: it carries the token, and errors show on the Suppliers page.
        raise RuntimeError(f"parfumcompany feed: HTTP {response.status_code}")
    return parse(response.content)


def parse(xml: bytes) -> list[Item]:
    items = []
    for product in ET.fromstring(xml).iter("product"):
        features = {f.findtext("name"): (f.findtext("value") or "").strip()
                    for f in product.iterfind("features/feature")}
        size = next((p.findtext("value") for p in product.iterfind("parameters/parameter")
                     if p.findtext("name") == "Size"), "")
        qty = int(product.findtext("stock") or 0)
        price = float(product.findtext("prices/default/price_net") or 0)
        if features.get("Type") not in KEPT_TYPES or "miniature" in (size or "") or qty <= 0 or price <= 0:
            continue
        brand = product.findtext("producer").strip()
        name = " ".join(product.findtext("name").split())
        # "Set Lattafa Pure Oudi Edp 100ml + Deodorant 50ml", "Flacon Guerlain Rosa Amira Edp
        # 125ml": the word goes to the end, so the brand can be dropped from the front.
        first, _, rest = name.partition(" ")
        kind = first if first.lower() in ("set", "flacon") else ""
        if kind:
            name = rest
        if name.lower().startswith(brand.lower() + " "):
            name = name[len(brand):].strip()  # the brand has its own field, like the other suppliers
        if kind.lower() == "set":
            name += " Set"
        # A flacon is a bottle without its box, sold like a tester, so it's grouped with them.
        if (features.get("Tester") == "yes" or kind.lower() == "flacon") and "tester" not in name.lower():
            name += " Tester"
        items.append(Item(
            sku=product.findtext("sku"),
            name=name,
            brand=brand,
            ean=(product.findtext("ean") or "").strip() or None,
            ean2=None,
            ean3=None,
            qty=qty,
            price=price,
            flagged_new=False,
            audience=AUDIENCES.get(features.get("For whom")),
        ))
    return items
