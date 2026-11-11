"""The fragrance catalogue: every fragrance suppliers list, how a listing is matched to one,
and your decisions about each.

A fragrance goes on one of your lists, or on none ('default'). Its list wins over its brand's
status: leave Memo on default but wishlist Ithaque, or follow Amouage but ignore Outlands.
  wishlist  what you want to buy: alerts when it's new, back in stock or cheaper
  filler    you wouldn't mind owning it, e.g. to reach a supplier's minimum order; never alerts
  ignore    hidden everywhere, never alerts
  default   the brand's status applies (brands are follow | ignore | default)
Separately, `owned` puts a fragrance in your collection. It doesn't change alerts.

A listing is matched once, when it first appears, by reading the fragrance name out of the
supplier's product name: "AMOUAGE BEACH HUT MAN EDP 100 ML VAPO" -> "BEACH HUT MAN", EDP. The
name ends where the concentration or the size starts. That reading is looked up in
fragrance_names, so a name you merged into another fragrance lands there. Step 2 of
docs/spec.md replaces the reading with Claude parsing.
"""

import re

from app.db import now

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


AUDIENCE_WORDS = [  # who a fragrance is for, when a supplier's name says it
    ("unisex", re.compile(r"\bUNISEX\b")),
    ("woman", re.compile(r"\b(WOMAN|WOMEN|FEMME|HER|DONNA|MUJER|LADY|LADIES)\b")),
    ("man", re.compile(r"\b(MAN|MEN|HOMME|HIM|UOMO|HOMBRE)\b")),
]
AUDIENCES = ("man", "woman", "unisex")


def read_audience(name: str) -> str | None:
    """"AMOUAGE BEACH HUT MAN EDP 100 ML" -> "man"; None when the name doesn't say."""
    text = name.upper()
    for audience, pattern in AUDIENCE_WORDS:
        if pattern.search(text):
            return audience
    return None


def learn_audience(conn, fragrance_id: int, audience: str | None) -> None:
    """A supplier says who a fragrance is for: kept unless it's known already."""
    if audience:
        conn.execute("UPDATE fragrances SET audience = ? WHERE id = ? AND audience IS NULL", (audience, fragrance_id))


def set_audience(conn, fragrance_id: int, audience: str | None) -> None:
    """You say who it's for (None: unknown)."""
    if audience not in AUDIENCES + (None,):
        raise ValueError(f"unknown audience {audience!r}")
    conn.execute("UPDATE fragrances SET audience = ? WHERE id = ?", (audience, fragrance_id))


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


def find_or_create(conn, brand_id: int, name: str, concentration: str | None) -> int:
    """The fragrance a name reads as (after your merges), created if it's new. Returns its id."""
    found = conn.execute(
        "SELECT fragrance_id FROM fragrance_names WHERE brand_id = ? AND name = ? AND concentration = ?",
        (brand_id, key(name), concentration or "")).fetchone()
    if found:
        return found["fragrance_id"]
    fragrance_id = conn.execute(
        "INSERT INTO fragrances (brand_id, name, concentration, created_at) VALUES (?, ?, ?, ?)",
        (brand_id, " ".join(name.upper().split()), concentration, now())).lastrowid
    conn.execute("INSERT INTO fragrance_names VALUES (?, ?, ?, ?)", (brand_id, key(name), concentration or "", fragrance_id))
    return fragrance_id


def by_ean(conn, eans) -> int | None:
    """The fragrance you added one of these EANs to, if any."""
    for ean in eans:
        if ean:
            found = conn.execute("SELECT fragrance_id FROM fragrance_eans WHERE ean = ?", (ean,)).fetchone()
            if found:
                return found["fragrance_id"]
    return None


def add_ean(conn, fragrance_id: int, ean: str) -> None:
    """This EAN is this fragrance: its listings move here now, and later ones land here. An EAN
    added to another fragrance before moves over."""
    conn.execute("INSERT OR REPLACE INTO fragrance_eans VALUES (?, ?, ?)", (ean, fragrance_id, now()))
    conn.execute("UPDATE listings SET fragrance_id = ? WHERE ? IN (ean, ean2, ean3)", (fragrance_id, ean))
    prune(conn)  # the fragrance they came from, if that left it empty and undecided


def remove_ean(conn, ean: str) -> None:
    """Stop matching by this EAN. Listings already attached stay where they are."""
    conn.execute("DELETE FROM fragrance_eans WHERE ean = ?", (ean,))


def assign(conn, brand_id: int, listing_name: str, spelling: str) -> int:
    """The fragrance a supplier listing is: read its name, then find or create it."""
    return find_or_create(conn, brand_id, *identify(listing_name, spelling))


def set_status(conn, fragrance_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    conn.execute("UPDATE fragrances SET status = ? WHERE id = ?", (status, fragrance_id))


def set_owned(conn, fragrance_id: int, owned: bool) -> None:
    conn.execute("UPDATE fragrances SET owned = ? WHERE id = ?", (int(owned), fragrance_id))


def set_size(conn, fragrance_id: int, size: str | None) -> None:
    """The size you'd buy ("100 ml", "100 ml tester"); None buys the cheapest."""
    conn.execute("UPDATE fragrances SET size = ? WHERE id = ?", (size, fragrance_id))


def set_note(conn, fragrance_id: int, note: str | None) -> None:
    conn.execute("UPDATE fragrances SET note = ? WHERE id = ?", (note, fragrance_id))


def merge(conn, fragrance_id: int, into_id: int) -> None:
    """fragrance_id is the same juice as into_id: its names and listings move over, and so do
    your decisions about it where into_id has none."""
    if fragrance_id == into_id:
        return
    source = conn.execute("SELECT * FROM fragrances WHERE id = ?", (fragrance_id,)).fetchone()
    conn.execute(
        """UPDATE fragrances SET
             status = CASE WHEN status = 'default' THEN ? ELSE status END,
             owned = max(owned, ?), size = coalesce(size, ?), note = coalesce(note, ?),
             audience = coalesce(audience, ?)
           WHERE id = ?""", (source["status"], source["owned"], source["size"], source["note"], source["audience"], into_id))
    conn.execute("UPDATE fragrance_names SET fragrance_id = ? WHERE fragrance_id = ?", (into_id, fragrance_id))
    conn.execute("UPDATE listings SET fragrance_id = ? WHERE fragrance_id = ?", (into_id, fragrance_id))
    conn.execute("UPDATE fragrance_eans SET fragrance_id = ? WHERE fragrance_id = ?", (into_id, fragrance_id))
    # What you said this one isn't, the merged fragrance isn't either.
    conn.execute(
        """INSERT OR IGNORE INTO not_same SELECT min(?, other), max(?, other) FROM (
             SELECT other_id AS other FROM not_same WHERE fragrance_id = ?
             UNION SELECT fragrance_id FROM not_same WHERE other_id = ?) WHERE other != ?""",
        (into_id, into_id, fragrance_id, fragrance_id, into_id))
    conn.execute("DELETE FROM not_same WHERE ? IN (fragrance_id, other_id)", (fragrance_id,))
    conn.execute("DELETE FROM fragrances WHERE id = ?", (fragrance_id,))


# Same brand, at least one EAN in common, not marked as different. Same name first: those are
# usually suppliers disagreeing about the concentration.
SUGGESTIONS = """
WITH codes AS (
    SELECT fragrance_id, ean FROM listings WHERE ean != ''
    UNION SELECT fragrance_id, ean2 FROM listings WHERE ean2 != ''
    UNION SELECT fragrance_id, ean3 FROM listings WHERE ean3 != ''),
pairs AS (
    SELECT a.fragrance_id AS a_id, b.fragrance_id AS b_id, min(a.ean) AS ean
    FROM codes a JOIN codes b ON b.ean = a.ean AND b.fragrance_id > a.fragrance_id
    GROUP BY a.fragrance_id, b.fragrance_id)
SELECT p.a_id, p.b_id, p.ean, br.name AS brand_name, fa.name = fb.name AS same_name
FROM pairs p
JOIN fragrances fa ON fa.id = p.a_id
JOIN fragrances fb ON fb.id = p.b_id
JOIN brands br ON br.id = fa.brand_id
WHERE fa.brand_id = fb.brand_id
  AND NOT EXISTS (SELECT 1 FROM not_same n WHERE n.fragrance_id = p.a_id AND n.other_id = p.b_id)
ORDER BY same_name DESC, br.name, fa.name
"""


def suggestions(conn) -> list:
    """Pairs of fragrances that might be the same juice, for you to confirm or reject."""
    return conn.execute(SUGGESTIONS).fetchall()


def mark_not_same(conn, fragrance_id: int, other_id: int) -> None:
    """You said these two are different fragrances: stop suggesting them."""
    conn.execute("INSERT OR IGNORE INTO not_same VALUES (?, ?)",
                 (min(fragrance_id, other_id), max(fragrance_id, other_id)))


def rename(conn, fragrance_id: int, name: str, concentration: str | None) -> int:
    """Correct a fragrance's name or concentration when a supplier has it wrong. If the
    corrected fragrance exists already, this one merges into it. Returns the fragrance's id.

    The supplier's wrong reading keeps pointing here, so their listings, current and future,
    stay on the corrected fragrance."""
    brand_id = conn.execute("SELECT brand_id FROM fragrances WHERE id = ?", (fragrance_id,)).fetchone()["brand_id"]
    existing = conn.execute(
        "SELECT fragrance_id FROM fragrance_names WHERE brand_id = ? AND name = ? AND concentration = ?",
        (brand_id, key(name), concentration or "")).fetchone()
    if existing and existing["fragrance_id"] != fragrance_id:
        merge(conn, fragrance_id, existing["fragrance_id"])
        return existing["fragrance_id"]
    conn.execute("UPDATE fragrances SET name = ?, concentration = ? WHERE id = ?",
                 (" ".join(name.upper().split()), concentration, fragrance_id))
    conn.execute("INSERT OR IGNORE INTO fragrance_names VALUES (?, ?, ?, ?)",
                 (brand_id, key(name), concentration or "", fragrance_id))
    return fragrance_id


def split(conn, fragrance_id: int, name: str, concentration: str) -> int:
    """Undo a merge: listings read as name/concentration become a fragrance of their own again.
    Returns its id."""
    target = conn.execute("SELECT * FROM fragrances WHERE id = ?", (fragrance_id,)).fetchone()
    conn.execute("DELETE FROM fragrance_names WHERE brand_id = ? AND name = ? AND concentration = ?",
                 (target["brand_id"], name, concentration))
    new_id = find_or_create(conn, target["brand_id"], name, concentration or None)
    for listing in conn.execute("SELECT * FROM listings WHERE fragrance_id = ?", (fragrance_id,)).fetchall():
        reading, read_concentration = identify(listing["name"], listing["brand"])
        if (key(reading), read_concentration or "") == (name, concentration):
            conn.execute("UPDATE listings SET fragrance_id = ? WHERE supplier = ? AND sku = ?",
                         (new_id, listing["supplier"], listing["sku"]))
    return new_id


def prune(conn) -> None:
    """Forget fragrances nothing lists and you made no decision about (left over after a brand
    split or merge, or after their listings moved to an EAN you added elsewhere)."""
    unused = """SELECT id FROM fragrances f WHERE status = 'default' AND owned = 0 AND note IS NULL
                AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.fragrance_id = f.id)
                AND NOT EXISTS (SELECT 1 FROM fragrance_eans e WHERE e.fragrance_id = f.id)"""
    conn.execute(f"DELETE FROM fragrance_names WHERE fragrance_id IN ({unused})")
    conn.execute(f"DELETE FROM fragrances WHERE id IN ({unused})")
