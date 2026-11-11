"""Command line, used by the schedule.

  fragrance run                  collect every supplier, then send one digest (the schedule)
  fragrance collect <supplier>   fetch one supplier and record changes, no digest
  fragrance notify               send the digest for whatever is pending
"""

import sys
import traceback

from app.collect import collect
from app.db import connect, upgrade
from app.notify import notify
from app.suppliers import SUPPLIERS


def run() -> None:
    """A supplier that fails doesn't stop the others; the digest names it and the exit code
    marks the schedule run as failed in Dokploy."""
    failed = []
    for supplier in SUPPLIERS:
        try:
            collect(supplier)
        except Exception:
            traceback.print_exc()
            failed.append(supplier)
    notify(failed)
    if failed:
        sys.exit(1)


def main() -> None:
    upgrade(connect())
    match sys.argv[1:]:
        case ["run"]:
            run()
        case ["collect", supplier] if supplier in SUPPLIERS:
            collect(supplier)
        case ["notify"]:
            notify([])
        case _:
            sys.exit(f"usage: fragrance run | fragrance collect {{{'|'.join(SUPPLIERS)}}} | fragrance notify")
