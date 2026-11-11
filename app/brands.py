"""Brand decisions, merging, and merge suggestions.

Each brand has one status:
  follow   new products and restocks alert you
  ignore   hidden everywhere, never alerts
  default  "Browse": shown in Stock, no alerts. Every brand starts here; new ones are offered
           in the digest with Follow / Ignore buttons, and wait on the Brands page's New tab
           until you choose (Browse included).
A fragrance on one of your lists decides for itself (app/fragrances.py).
"""

import re
import unicodedata
from collections import defaultdict

from app import fragrances
from app.db import add_brand, now

STATUSES = ("follow", "ignore", "default")


def set_status(conn, brand_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    conn.execute("UPDATE brands SET status = ?, reviewed_at = coalesce(reviewed_at, ?) WHERE id = ?",
                 (status, now(), brand_id))


def brand_for(conn, spelling: str, announced: bool) -> int:
    """The brand a supplier spelling belongs to. A spelling seen for the first time joins the
    brand with the same name ("Hermès" joins HERMES: capitals, accents and words like "Parfums"
    or "Paris" don't count) and is remembered; with no such brand it becomes a new one, on
    default (announced=True keeps it out of the digest)."""
    row = conn.execute("SELECT brand_id FROM brand_aliases WHERE alias = ?", (spelling,)).fetchone()
    if row:
        return row["brand_id"]
    brand_id = same_name(conn, spelling)
    if brand_id is None:
        return add_brand(conn, spelling, announced)
    conn.execute("INSERT INTO brand_aliases (alias, brand_id) VALUES (?, ?)", (spelling, brand_id))
    return brand_id


def same_name(conn, name: str) -> int | None:
    """The one brand whose name or a spelling matches this name (see key()); None if no
    brand does, or if several do and it's unclear which."""
    wanted = key(name)
    known = conn.execute("SELECT brand_id, alias FROM brand_aliases UNION SELECT id, name FROM brands").fetchall()
    found = {row["brand_id"] for row in known if key(row["alias"]) == wanted}
    return found.pop() if len(found) == 1 else None


def add(conn, name: str, status: str) -> int:
    """A brand you add yourself, e.g. to follow it before any supplier lists it. If you have it
    already under the same name ("Hermes Parfums" for Hermès), that one gets the status
    instead. Returns its id. Suppliers listing it under that name land on it; under another
    spelling it shows in the New tab with a "Same as" suggestion."""
    brand_id = same_name(conn, name) or add_brand(conn, name.strip(), announced=True)
    set_status(conn, brand_id, status)
    return brand_id


def rename(conn, brand_id: int, name: str) -> None:
    conn.execute("UPDATE brands SET name = ? WHERE id = ?", (name.strip(), brand_id))


def merge(conn, brand_id: int, into_id: int) -> None:
    """brand_id becomes part of into_id: its spellings and fragrances move over, and into_id's
    status stays. A fragrance both brands have (same name and concentration) becomes one."""
    if brand_id == into_id:
        return
    for name in conn.execute("SELECT * FROM fragrance_names WHERE brand_id = ?", (brand_id,)).fetchall():
        same = conn.execute(
            "SELECT fragrance_id FROM fragrance_names WHERE brand_id = ? AND name = ? AND concentration = ?",
            (into_id, name["name"], name["concentration"])).fetchone()
        if same:
            fragrances.merge(conn, name["fragrance_id"], same["fragrance_id"])
    conn.execute("UPDATE OR IGNORE fragrance_names SET brand_id = ? WHERE brand_id = ?", (into_id, brand_id))
    conn.execute("DELETE FROM fragrance_names WHERE brand_id = ?", (brand_id,))  # names into_id already had
    conn.execute("UPDATE fragrances SET brand_id = ? WHERE brand_id = ?", (into_id, brand_id))
    conn.execute("UPDATE brand_aliases SET brand_id = ? WHERE brand_id = ?", (into_id, brand_id))
    conn.execute("DELETE FROM brands WHERE id = ?", (brand_id,))


def split(conn, alias: str) -> int:
    """Take one spelling out of its brand and make it a brand of its own, on default. Its
    listings move to fragrances of the new brand. Returns the new brand's id."""
    conn.execute("DELETE FROM brand_aliases WHERE alias = ?", (alias,))
    brand_id = add_brand(conn, alias, announced=True)
    for listing in conn.execute("SELECT * FROM listings WHERE brand = ? COLLATE NOCASE", (alias,)).fetchall():
        conn.execute("UPDATE listings SET fragrance_id = ? WHERE supplier = ? AND sku = ?",
                     (fragrances.assign(conn, brand_id, listing["name"], listing["brand"]),
                      listing["supplier"], listing["sku"]))
    fragrances.prune(conn)
    return brand_id


# --- Merge suggestions -------------------------------------------------------------------
# A new brand might be another spelling of a brand you already have. Two signals:
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
    """For every undecided brand: [(other brand id, its name, reason)], strongest first."""
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
        if brands[a]["status"] == "default":
            for b in brands:
                if b != a and similar(keys[a], keys[b]):
                    found[a].setdefault(b, "similar name")

    return {
        a: [(b, brands[b]["name"], reason) for b, reason in others.items()]
        for a, others in found.items() if brands[a]["status"] == "default"
    }
