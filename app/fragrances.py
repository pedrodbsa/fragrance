"""Your decisions about single fragrances, and how supplier listings are matched to them.

A decision names a fragrance (brand + name, optionally a concentration) and says:
  want    wishlist: alerts when it's new, back in stock or cheaper, whatever the brand's status
  own     in your collection: shown with a badge, never alerts
  ignore  not interested: hidden everywhere, never alerts
A decision about a fragrance wins over the decision about its brand: you can browse Memo
but want Ithaque, or follow Amouage but ignore Beach Hut.

Listings are matched by reading the fragrance name out of the supplier's product name:
"AMOUAGE BEACH HUT MAN EDP 100 ML VAPO" -> "BEACH HUT MAN", EDP. The name ends where the
concentration or the size starts. Step 2 of docs/spec.md replaces this with Claude parsing.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

STATUSES = ("want", "own", "ignore")
CONCENTRATIONS = ("EDP", "EDT", "EDC", "Parfum", "Extrait", "Cologne")

# Where a supplier name stops naming the fragrance, strongest signal first.
STRONG = re.compile(r"\b(EAU DE PARFUM|EAU DE TOILETTE|EAU DE COLOGNE|EDP|EDT|EDC|EXTRAIT(?: DE PARFUM)?)\b")
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:ML|GR|G|OZ)\b")
WEAK = re.compile(r"\b(PARFUM|COLOGNE)\s+(?=\d)")  # only right before a size: "LE PARFUM" is a name
CANONICAL = {"EAU DE PARFUM": "EDP", "EAU DE TOILETTE": "EDT", "EAU DE COLOGNE": "EDC",
             "EXTRAIT DE PARFUM": "Extrait", "EXTRAIT": "Extrait", "PARFUM": "Parfum", "COLOGNE": "Cologne"}


def key(text: str) -> str:
    """Comparable form of a name: capitals, single spaces, no punctuation."""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", text.upper()).split())


def identify(name: str, brand: str) -> tuple[str, str | None]:
    """Supplier product name -> (fragrance name, concentration or None)."""
    # Drop the brand from the front, however it's written: "GAULTIER DIVINE" under
    # JEAN PAUL GAULTIER, "ACQUA PARMA SIGNATURE" under ACQUA DI PARMA.
    brand_words = set(key(brand).split())
    words = name.upper().split()
    while len(words) > 1 and key(words[0]) and set(key(words[0]).split()) <= brand_words:
        words.pop(0)
    text = " ".join(words)
    for pattern in (STRONG, WEAK):
        found = pattern.search(text)
        if found and found.start() > 0:
            token = found.group(1)
            return text[:found.start()].strip(), CANONICAL.get(token, token)
    found = SIZE.search(text)
    if found and found.start() > 0:
        return text[:found.start()].strip(), None
    return text, None


def matcher(conn):
    """Returns match(listing) -> the decision covering that catalog row, or None."""
    decisions = defaultdict(list)
    for d in conn.execute("SELECT * FROM fragrances"):
        decisions[key(d["name"])].append(d)

    def match(listing):
        name, concentration = identify(listing["name"], listing["brand"])
        for d in decisions.get(key(name), []):
            brand_ok = d["brand_id"] is None or d["brand_id"] == listing["brand_id"]
            if brand_ok and (d["concentration"] is None or d["concentration"] == concentration):
                return d
        return None

    return match


def hidden(listing, decision) -> bool:
    """Left out of Stock, Changes and alerts: ignored fragrances, and anything from a brand
    that's ignored or not triaged yet unless you decided on that fragrance."""
    if decision is not None:
        return decision["status"] == "ignore"
    return listing["status"] in ("ignore", "new")


def save(conn, brand_id: int | None, name: str, concentration: str | None, status: str, note: str | None) -> None:
    """Record a decision, replacing an earlier one about the same fragrance."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    for d in conn.execute("SELECT * FROM fragrances WHERE brand_id IS ? AND concentration IS ?", (brand_id, concentration)):
        if key(d["name"]) == key(name):
            conn.execute("DELETE FROM fragrances WHERE id = ?", (d["id"],))
    conn.execute(
        "INSERT INTO fragrances (brand_id, name, concentration, status, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (brand_id, " ".join(name.upper().split()), concentration, status, note,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
