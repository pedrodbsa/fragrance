"""Your decisions about single fragrances, and how supplier listings are matched to them.

A fragrance goes on one of your lists, or on none ('default'). Its list wins over its brand's
status: leave Memo on default but wishlist Ithaque, or follow Amouage but ignore Outlands.
  wishlist  what you want to buy: alerts when it's new, back in stock or cheaper
  filler    you wouldn't mind owning it, e.g. to reach a supplier's minimum order; never alerts
  ignore    hidden everywhere, never alerts
  default   the brand's status applies (brands are follow | ignore | default)
Separately, `owned` puts a fragrance in your collection. It doesn't change alerts.

Listings are matched by reading the fragrance name out of the supplier's product name:
"AMOUAGE BEACH HUT MAN EDP 100 ML VAPO" -> "BEACH HUT MAN", EDP. The name ends where the
concentration or the size starts. Step 2 of docs/spec.md replaces this with Claude parsing.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

STATUSES = ("wishlist", "filler", "ignore", "default")
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


TESTER = re.compile(r"\b(TESTER|TST|TSTR)\b")
GIFT_SET = re.compile(r"\b(SET|KIT|COFFRET|ESTUCHE)\b|\+")  # a gift set shows as its own "size"
AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ML|GR|G|OZ)\b")


def variant(name: str) -> tuple[float, str]:
    """Size and format of a listing, for grouping sizes under one fragrance:
    "... EDP 100 ML VAPO TESTER" -> (100.0, "100 ml tester"), "... EDP SET 100 ML + 15 ML" ->
    (100.0, "100 ml set"). Unknown sizes sort last."""
    text = name.upper()
    found = AMOUNT.search(text)
    kind = " set" if GIFT_SET.search(text) else " tester" if TESTER.search(text) else ""
    if not found:
        return 1e9, "other" + kind
    number, unit = found.groups()
    return float(number.replace(",", ".")), f"{number} {unit.lower()}{kind}"


def resolver(conn):
    """Returns juice(listing) -> (fragrance name, concentration), after your merges: a listing
    read as a name you merged into another fragrance counts as that fragrance."""
    aliases = {(a["brand_id"], key(a["name"]), a["concentration"]): (a["into_name"], a["into_concentration"])
               for a in conn.execute("SELECT * FROM fragrance_aliases")}

    def juice(listing):
        name, concentration = identify(listing["name"], listing["brand"])
        for _ in range(10):  # follow merges of merges; the cap guards against a loop
            target = aliases.get((listing["brand_id"], key(name), concentration or ""))
            if target is None:
                break
            name, concentration = target[0], target[1] or None
        return name, concentration

    return juice


def merge(conn, brand_id: int, name: str, concentration: str | None, into_name: str, into_concentration: str | None) -> None:
    """The fragrance read as name/concentration is the same juice as into_name/into_concentration.
    Earlier merges into it, and your decision about it, move over too."""
    source, target = (key(name), concentration or ""), (key(into_name), into_concentration or "")
    if source == target:
        return
    conn.execute("UPDATE fragrance_aliases SET into_name = ?, into_concentration = ? "
                 "WHERE brand_id = ? AND into_name = ? AND into_concentration = ?", (*target, brand_id, *source))
    conn.execute("INSERT OR REPLACE INTO fragrance_aliases VALUES (?, ?, ?, ?, ?)", (brand_id, *source, *target))
    conn.execute("DELETE FROM fragrance_aliases WHERE name = into_name AND concentration = into_concentration")
    for d in conn.execute("SELECT * FROM fragrances WHERE brand_id = ? AND concentration IS ?", (brand_id, concentration)).fetchall():
        if key(d["name"]) == source[0]:
            taken = any(key(t["name"]) == target[0] for t in conn.execute(
                "SELECT name FROM fragrances WHERE brand_id = ? AND concentration IS ?", (brand_id, into_concentration)))
            if taken:
                conn.execute("DELETE FROM fragrances WHERE id = ?", (d["id"],))
            else:
                conn.execute("UPDATE fragrances SET name = ?, concentration = ? WHERE id = ?", (target[0], into_concentration, d["id"]))


def split(conn, brand_id: int, name: str, concentration: str | None) -> None:
    """Undo a merge: listings read as name/concentration are their own fragrance again."""
    conn.execute("DELETE FROM fragrance_aliases WHERE brand_id = ? AND name = ? AND concentration = ?",
                 (brand_id, key(name), concentration or ""))


def matcher(conn):
    """Returns match(listing) -> the decision covering that catalog row, or None."""
    decisions = defaultdict(list)
    for d in conn.execute("SELECT * FROM fragrances"):
        decisions[key(d["name"])].append(d)
    juice = resolver(conn)

    def match(listing):
        name, concentration = juice(listing)
        for d in decisions.get(key(name), []):
            brand_ok = d["brand_id"] is None or d["brand_id"] == listing["brand_id"]
            if brand_ok and (d["concentration"] is None or d["concentration"] == concentration):
                return d
        return None

    return match


def decided(decision) -> bool:
    """Whether a fragrance decision overrides the brand's status."""
    return decision is not None and decision["status"] != "default"


def alerting(listing, decision) -> bool:
    """Whether changes to this listing reach Telegram."""
    return decision["status"] == "wishlist" if decided(decision) else listing["status"] == "follow"


def hidden(listing, decision) -> bool:
    """Left out of Stock, Changes and alerts."""
    return decision["status"] == "ignore" if decided(decision) else listing["status"] == "ignore"


def save(conn, brand_id: int | None, name: str, concentration: str | None,
         status: str | None = None, owned: bool | None = None, note: str | None = None) -> None:
    """Set the status and/or collection flag of a fragrance, keeping what isn't given.
    A fragrance back on default and not owned is forgotten."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    existing = next((d for d in conn.execute(
        "SELECT * FROM fragrances WHERE brand_id IS ? AND concentration IS ?", (brand_id, concentration))
        if key(d["name"]) == key(name)), None)
    status = status or (existing["status"] if existing else "default")
    owned = owned if owned is not None else bool(existing and existing["owned"])
    note = note if note is not None else (existing["note"] if existing else None)
    if existing:
        conn.execute("DELETE FROM fragrances WHERE id = ?", (existing["id"],))
    if status != "default" or owned:
        conn.execute(
            """INSERT INTO fragrances (id, brand_id, name, concentration, status, owned, note, size, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (existing["id"] if existing else None, brand_id, " ".join(name.upper().split()), concentration,
             status, int(owned), note, existing["size"] if existing else None,
             existing["created_at"] if existing else datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def set_size(conn, fragrance_id: int, size: str | None) -> None:
    """The size you'd buy ("100 ml", "100 ml tester"); None buys the cheapest."""
    conn.execute("UPDATE fragrances SET size = ? WHERE id = ?", (size, fragrance_id))
