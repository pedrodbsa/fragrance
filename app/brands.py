"""Brand decisions, merging, and merge suggestions.

Each brand has one status:
  follow  shown in Stock; new products and restocks alert you
  browse  shown in Stock; never alerts (except fragrances on your wishlist)
  ignore  hidden everywhere, never alerts
  new     not triaged yet: waits on the Triage page and is offered on Telegram
"""

import re
import unicodedata
from collections import defaultdict

from app.db import add_brand

STATUSES = ("follow", "browse", "ignore")


def set_status(conn, brand_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    conn.execute("UPDATE brands SET status = ? WHERE id = ?", (status, brand_id))


def rename(conn, brand_id: int, name: str) -> None:
    conn.execute("UPDATE brands SET name = ? WHERE id = ?", (name.strip(), brand_id))


def merge(conn, brand_id: int, into_id: int) -> None:
    """brand_id becomes part of into_id: its spellings and fragrance decisions move over, and
    into_id's status stays."""
    if brand_id == into_id:
        return
    conn.execute("UPDATE brand_aliases SET brand_id = ? WHERE brand_id = ?", (into_id, brand_id))
    conn.execute("UPDATE fragrances SET brand_id = ? WHERE brand_id = ?", (into_id, brand_id))
    conn.execute("DELETE FROM brands WHERE id = ?", (brand_id,))


def split(conn, alias: str) -> int:
    """Take one spelling out of its brand and make it a brand of its own, to triage again."""
    conn.execute("DELETE FROM brand_aliases WHERE alias = ?", (alias,))
    return add_brand(conn, alias, announced=True)


# --- Merge suggestions -------------------------------------------------------------------
# A brand to triage might be another spelling of a brand you already have. Two signals:
#   same EAN  one product listed under both names by different suppliers
#   similar   the names match once accents, punctuation and filler words are ignored,
#             one name contains the other, or one is the other's initials (YSL)
# EAN manufacturer prefixes were tried and dropped: they identify the licence holder
# (Armani, Lancôme and Valentino share one), not the brand.

FILLER = {"PARFUMS", "PARFUM", "PERFUMES", "PERFUME", "FRAGRANCES", "PARIS", "LONDON", "MILANO", "NEW", "YORK"}


def key(name: str) -> str:
    """'Hermès Parfums' -> 'HERMES'."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^A-Z0-9]+", " ", plain.upper()).split()
    return " ".join(w for w in words if w not in FILLER) or " ".join(words)


def initials(name: str) -> str | None:
    words = name.split()
    return "".join(w[0] for w in words) if len(words) >= 2 else None


def similar(a: str, b: str) -> bool:
    wa, wb = set(a.split()), set(b.split())
    contained = (wa <= wb or wb <= wa) and min(len(a), len(b)) >= 3
    return contained or a.replace(" ", "") == initials(b) or b.replace(" ", "") == initials(a)


def suggestions(conn) -> dict[int, list[tuple[int, str, str]]]:
    """For every brand to triage: [(other brand id, its name, reason)], strongest first."""
    brands = {r["id"]: r for r in conn.execute("SELECT * FROM brands")}
    listed = defaultdict(set)  # EAN -> {(brand, supplier)}
    for r in conn.execute("SELECT brand_id, supplier, ean, ean2, ean3 FROM catalog"):
        for ean in (r["ean"], r["ean2"], r["ean3"]):
            if ean:
                listed[ean].add((r["brand_id"], r["supplier"]))

    found = defaultdict(dict)  # brand -> {other brand: reason}; the first reason found is the strongest
    for owners in listed.values():
        # Within one supplier a shared EAN is a data-entry slip, so only count other suppliers.
        for a, supplier_a in owners:
            for b, supplier_b in owners:
                if a != b and supplier_a != supplier_b:
                    found[a].setdefault(b, "same EAN")
    keys = {i: key(b["name"]) for i, b in brands.items()}
    for a in brands:
        if brands[a]["status"] == "new":
            for b in brands:
                if b != a and similar(keys[a], keys[b]):
                    found[a].setdefault(b, "similar name")

    return {
        a: [(b, brands[b]["name"], reason) for b, reason in others.items()]
        for a, others in found.items() if brands[a]["status"] == "new"
    }
