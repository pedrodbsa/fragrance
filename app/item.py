from dataclasses import dataclass


@dataclass
class Item:
    """One in-stock product as a supplier lists it, in the same shape for every supplier."""

    sku: str
    name: str
    brand: str
    ean: str | None
    ean2: str | None
    ean3: str | None
    qty: int
    price: float
    flagged_new: bool
    audience: str | None = None  # man | woman | unisex, when the supplier says; else read from the name
