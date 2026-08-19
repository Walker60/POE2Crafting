"""Manual-run refresh of data/vendor/poe2db/economy_divine.html -- poe2db.tw's
live currency-exchange-rate page, priced against Divine Orb. Never invoked at
package runtime. See docs/data_provenance.md for the scraping stance.

Usage: uv run python scripts/fetch_coe_prices.py
"""
from __future__ import annotations

from pathlib import Path

import requests

URL = "https://poe2db.tw/us/Economy_divine"
DEST = Path(__file__).resolve().parent.parent / "data" / "vendor" / "poe2db" / "economy_divine.html"


def main() -> int:
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "poe2craft/0.1 (personal, non-commercial)"})
    resp.raise_for_status()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(resp.text, encoding="utf-8")
    print(f"Wrote {DEST} ({len(resp.text) / 1024:.0f} KiB)")
    print("Now run: uv run python scripts/build_gamedata.py")
    print("Note: these are live, moment-to-moment market prices -- expect them to")
    print("drift between refreshes; that's normal, not a bug.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
