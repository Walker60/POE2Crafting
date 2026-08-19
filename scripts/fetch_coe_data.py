"""Manual-run refresh of data/vendor/coe_poe2_data.json. Never invoked at package
runtime -- see docs/data_provenance.md for the scraping stance and refresh
procedure.

Usage: uv run python scripts/fetch_coe_data.py
"""
from __future__ import annotations

from pathlib import Path

import requests

URL = "https://www.craftofexile.com/json/poe2/main/poec_data.json"
DEST = Path(__file__).resolve().parent.parent / "data" / "vendor" / "coe_poe2_data.json"


def main() -> int:
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "poe2craft/0.1 (personal, non-commercial)"})
    resp.raise_for_status()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(resp.content)
    print(f"Wrote {DEST} ({len(resp.content) / 1024:.0f} KiB)")
    print("Now run: uv run python scripts/build_gamedata.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
