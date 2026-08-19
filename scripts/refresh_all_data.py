"""One-shot refresh of every vendored data source, then rebuilds the compiled
gamedata -- the single command to run after a PoE2 patch, or whenever you
want current currency prices. Equivalent to running, in order:

    fetch_coe_data.py -> fetch_poe2db_pages.py -> fetch_coe_prices.py -> build_gamedata.py

Still a manual, user-invoked action -- never run automatically or at package
runtime (see docs/data_provenance.md's scraping stance). If one source fails
to fetch (e.g. a network hiccup), this continues on to the others rather than
aborting, then still rebuilds gamedata from whatever's vendored (old copies
for anything that failed to refresh, fresh for everything else) -- and exits
non-zero so the failure isn't silently missed.

Usage: uv run python scripts/refresh_all_data.py
"""
from __future__ import annotations

import build_gamedata
import fetch_coe_data
import fetch_coe_prices
import fetch_poe2db_pages

STEPS = [
    ("Craft of Exile mod/base/tier dataset", fetch_coe_data.main),
    ("poe2db.tw omen catalog + currency pages", fetch_poe2db_pages.main),
    ("poe2db.tw live economy prices", fetch_coe_prices.main),
]


def main() -> int:
    failed: list[str] = []
    for label, fetch_main in STEPS:
        print(f"=== Refreshing: {label} ===")
        try:
            fetch_main()
        except Exception as exc:  # noqa: BLE001 -- report and keep going, don't let one source block the rest
            print(f"  FAILED: {exc}")
            failed.append(label)
        print()

    print("=== Rebuilding data/compiled/poe2_gamedata.json ===")
    build_gamedata.main()

    if failed:
        print()
        print("Some sources failed to refresh (compiled from whatever was already vendored for these):")
        for label in failed:
            print(f"  - {label}")
        print("Re-run this script to retry just those, or check your network connection.")
        return 1

    print()
    print("All sources refreshed. Re-run the test suite (uv run pytest) -- a patch")
    print("that changes mod weights, bases, or currency mechanics can change solver output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
