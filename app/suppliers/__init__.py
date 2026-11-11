"""One module per supplier. Each exposes a fetch() -> list[Item] with the supplier's current
in-stock items; anything missing from the list is treated as sold out."""

from app.suppliers import nunu, wholesale_fragrances

SUPPLIERS = {
    "nunu": nunu.fetch,
    "wholesale-fragrances": wholesale_fragrances.fetch_wholesale_fragrances,
    "fragrances-wholesale": wholesale_fragrances.fetch_fragrances_wholesale,
}
