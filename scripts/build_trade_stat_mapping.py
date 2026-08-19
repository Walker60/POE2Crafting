"""Builds data/compiled/trade_stat_mapping.json ({mod_id: trade stat_id}) by
text-matching data/compiled/poe2_gamedata.json's mods against the vendored
trade2 stats catalog (scripts/fetch_trade_stats.py). Kept separate from
poe2_gamedata.json -- a pricing-package concern, not a crafting-mechanics
one. See docs/data_provenance.md and poe2craft.pricing.stat_matching.

Usage: uv run python scripts/build_trade_stat_mapping.py
"""
from __future__ import annotations

import json
from pathlib import Path

from poe2craft.data.loader import load_gamedata
from poe2craft.pricing.stat_matching import DEFAULT_MAPPING_PATH, build_mod_stat_mapping, parse_stats_catalog

STATS_PATH = Path(__file__).resolve().parent.parent / "data" / "vendor" / "pathofexile_trade2" / "stats.json"


def main() -> int:
    if not STATS_PATH.exists():
        print(f"Missing {STATS_PATH} -- run scripts/fetch_trade_stats.py first.")
        return 1

    raw = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    stats = parse_stats_catalog(raw)
    gd = load_gamedata()
    mapping, unmatched = build_mod_stat_mapping(gd.mods, stats)

    DEFAULT_MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_MAPPING_PATH.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {DEFAULT_MAPPING_PATH}: {len(mapping)} mods mapped, {len(unmatched)} unmatched")
    if unmatched:
        print("Unmatched mod ids (no trade stat found by text match -- review before relying on pricing for these):")
        for mid in sorted(unmatched, key=str)[:30]:
            print(f"  {mid}: {gd.mods[mid].name!r}")
        if len(unmatched) > 30:
            print(f"  ... and {len(unmatched) - 30} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
