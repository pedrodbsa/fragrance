"""One module per supplier. Each exposes a fetch() -> list[Item] with the supplier's current
in-stock items; anything missing from the list is treated as sold out."""

from app.suppliers import fragranta, fragrances_wholesale, nunu, parfumcompany, perfumes_wholesale, romscent, symphonya

SUPPLIERS = {
    "nunu": nunu.fetch,
    "fragrances-wholesale": fragrances_wholesale.fetch,
    "perfumes-wholesale": perfumes_wholesale.fetch,
    "symphonya": symphonya.fetch,
    "parfumcompany": parfumcompany.fetch,
    "fragranta": fragranta.fetch,
    "romscent": romscent.fetch,
}
