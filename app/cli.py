"""Command line, used by the schedule.

  fragrance run                  collect every supplier, then send one digest (the schedule)
  fragrance collect <supplier>   fetch one supplier and record changes, no digest
  fragrance notify               send the digest for whatever is pending
"""

import sys
import traceback

from app.collect import collect
from app.db import collection_failed, connect
from app.upgrades import upgrade
from app.notify import notify
from app.suppliers import SUPPLIERS


def run() -> None:
    """A supplier that fails doesn't stop the others; the digest names it and the exit code
    marks the schedule run as failed in Dokploy."""
    failed = [supplier for supplier in SUPPLIERS if not attempt(supplier)]
    notify(failed)
    if failed:
        sys.exit(1)


def attempt(supplier: str) -> bool:
    """Collect one supplier. A failure is printed and shown on the Suppliers page."""
    try:
        collect(supplier)
        return True
    except Exception as error:
        traceback.print_exc()
        conn = connect()
        with conn:
            collection_failed(conn, supplier, f"{type(error).__name__}: {error}"[:500])
        return False


def main() -> None:
    upgrade(connect())
    match sys.argv[1:]:
        case ["run"]:
            run()
        case ["collect", supplier] if supplier in SUPPLIERS:
            sys.exit(0 if attempt(supplier) else 1)
        case ["notify"]:
            notify([])
        case _:
            sys.exit(f"usage: fragrance run | fragrance collect {{{'|'.join(SUPPLIERS)}}} | fragrance notify")
