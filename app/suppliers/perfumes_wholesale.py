"""perfumes-wholesale.eu: two XML feeds, opened with a hash that works like a password.
  catalogue  https://m2.znzelectronics.cz/feeds/download/catalog/hash/…/format/xml/currency/EUR/language/en_GB/type/default/
             every product with its name, brand, EAN and who it's for; refreshed once a night
  stock      https://m2.znzelectronics.cz/feeds/download/stock/hash/…/format/xml/currency/EUR/type/default/
             SKU, price and quantity; refreshed every 10 minutes
Env: SUPPLIER_PERFUMES_WHOLESALE_HASH.

The names come from the catalogue, the price and quantity from the stock feed. A product
missing from the stock feed, or priced 0 there, isn't available (their rule).

About 15,500 products, two thirds perfumery. Kept: perfumes, testers, unboxed bottles and gift
sets; left out: samples, miniatures, used bottles, deodorants, body care, candles and the like.
Some products sit in two or three warehouses at different prices: the cheapest one in stock
is the one shown.

A catalogue product looks like this (the name starts with the brand and ends with who it's for;
both are dropped from the name, since they have their own fields):
  <shopItem><productNo>165823</productNo><availability>1</availability><warehouse>01111020</warehouse>
    <price>16.01</price><product>Zadig &amp; Voltaire This is Him Eau De Toilette - unpacked 30 ml (man)</product>
    <manufacturer>Zadig &amp; Voltaire</manufacturer><ean>9999901658230</ean><size>30 ml</size>
    <gender>Male</gender><category_root>Perfumes</category_root><category>Eau De Toilette - unpacked</category></shopItem>
"""

import os
import re
import xml.etree.ElementTree as ET

import httpx

from app.item import Item

FEEDS = "https://m2.znzelectronics.cz/feeds/download"
# Their category says what a product is: "Eau De Parfum - tester", "Gift Set EDP", "Bodyspray"…
KEPT = re.compile(r"eau de|parfum|extrait|perfume|cologne|gift set|eau fra", re.I)
LEFT_OUT = re.compile(r"sample|miniature|used|candle|deo|shower|body|hair|shave|soap|cream|oil|"
                      r"diffuser|interior|car scents|laundry|roll-on|case|kids", re.I)
AUDIENCES = {"Male": "man", "Female": "woman", "Unisex": "unisex"}  # their gender field


def fetch() -> list[Item]:
    secret = os.environ["SUPPLIER_PERFUMES_WHOLESALE_HASH"]
    catalogue = download("catalogue", f"{FEEDS}/catalog/hash/{secret}/format/xml/currency/EUR/language/en_GB/type/default/")
    stock = download("stock", f"{FEEDS}/stock/hash/{secret}/format/xml/currency/EUR/type/default/")
    return parse(catalogue, stock)


def download(what: str, url: str) -> bytes:
    response = httpx.get(url, timeout=300, follow_redirects=True)
    if response.status_code != 200:
        # Said without the URL: it carries the hash, and errors show on the Suppliers page.
        raise RuntimeError(f"perfumes-wholesale {what} feed: HTTP {response.status_code}")
    return response.content


def parse(catalogue: bytes, stock: bytes) -> list[Item]:
    offers = best_offers(stock)
    items = []
    for product in ET.fromstring(catalogue).iter("shopItem"):
        sku = product.findtext("productNo")
        category = product.findtext("category") or ""
        offer = offers.pop(sku, None)  # pop: a product listed in two warehouses is taken once
        if (offer is None or product.findtext("category_root") != "Perfumes"
                or not KEPT.search(category) or LEFT_OUT.search(category)):
            continue
        # "Hermès L'Ombre des Merveilles Eau De Parfum 100 ml (unisex)" -> "L'Ombre des
        # Merveilles Eau De Parfum 100 ml": the brand has its own field, like the other shops.
        brand = product.findtext("manufacturer").strip()
        name = re.sub(r"\s*\([^)]*\)\s*$", "", product.findtext("product")).strip()
        if name.lower().startswith(brand.lower() + " "):
            name = name[len(brand):].strip()
        if "unpacked" in category.lower() and "tester" not in name.lower():
            name += " Tester"  # an unboxed bottle is sold like a tester, so it's grouped with them
        ean = (product.findtext("ean") or "").strip()
        price, qty = offer
        items.append(Item(
            sku=sku,
            name=name,
            brand=brand,
            ean=ean or None,
            ean2=None,
            ean3=None,
            qty=qty,
            price=price,
            flagged_new=False,
            audience=AUDIENCES.get(product.findtext("gender")),
        ))
    return items


def best_offers(stock: bytes) -> dict[str, tuple[float, int]]:
    """SKU -> (price, quantity) of its cheapest warehouse that has it, from the stock feed."""
    offers = {}
    for row in ET.fromstring(stock).iter("shopItem"):
        price, qty = float(row.findtext("price") or 0), int(row.findtext("availability") or 0)
        sku = row.findtext("productNo")
        if price > 0 and qty > 0 and (sku not in offers or price < offers[sku][0]):
            offers[sku] = (price, qty)
    return offers
