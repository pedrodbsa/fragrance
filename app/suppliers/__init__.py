"""One module per supplier. Each exposes fetch() -> list[Item] with the supplier's current
in-stock items; anything missing from the list is treated as sold out."""

from app.suppliers import nunu

SUPPLIERS = {
    "nunu": nunu.fetch,
}
