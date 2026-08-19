"""Manual-run snapshot of pathofexile.com/trade2's stat-filter catalog
(`/api/trade2/data/stats`) -- the input to
poe2craft.pricing.stat_matching.build_mod_stat_mapping (run
scripts/build_trade_stat_mapping.py next). No POESESSID needed. Never
invoked at package runtime. See docs/data_provenance.md.

Usage: uv run python scripts/fetch_trade_stats.py
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

URL = "https://www.pathofexile.com/api/trade2/data/stats"
DEST = Path(__file__).resolve().parent.parent / "data" / "vendor" / "pathofexile_trade2" / "stats.json"


def main() -> int:
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "poe2craft/0.1 (personal, non-commercial)"})
    resp.raise_for_status()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(resp.json(), indent=2), encoding="utf-8")
    print(f"Wrote {DEST}")
    print("Now run: uv run python scripts/build_trade_stat_mapping.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
