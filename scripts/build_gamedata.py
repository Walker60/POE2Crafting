"""Manual-run build step: data/vendor/* -> data/compiled/poe2_gamedata.json.

Never invoked at package runtime -- run this by hand after refreshing a vendored
source (see docs/data_provenance.md for the refresh procedure).

Usage: uv run python scripts/build_gamedata.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from poe2craft.data.coe_parse import parse_coe, referential_integrity_report  # noqa: E402
from poe2craft.data.poe2db_parse import parse_currency_pages, parse_economy_divine, parse_omens  # noqa: E402
from poe2craft.data.schemas import GameDataFile  # noqa: E402

VENDOR = ROOT / "data" / "vendor"
COMPILED = ROOT / "data" / "compiled" / "poe2_gamedata.json"

COE_URL = "https://www.craftofexile.com/json/poe2/main/poec_data.json"
POE2DB_OMENS_URL = "https://poe2db.tw/us/Omen"
POE2DB_CURRENCY_URL = "https://poe2db.tw/us/Currency"
POE2DB_ECONOMY_URL = "https://poe2db.tw/us/Economy_divine"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    coe_path = VENDOR / "coe_poe2_data.json"
    raw = coe_path.read_text(encoding="utf-8")
    parsed = parse_coe(raw)
    warnings = parsed.pop("_warnings")
    for w in warnings:
        print(f"[coe_parse warning] {w}")

    problems = referential_integrity_report(parsed)
    for p in problems:
        print(f"[integrity] {p}")

    omens: list[dict] = []
    currency_mechanics: list[dict] = []
    omens_dir = VENDOR / "poe2db"
    if (omens_dir / "omens.html").exists():
        omens = parse_omens((omens_dir / "omens.html").read_text(encoding="utf-8"))
    currency_dir = omens_dir / "currency"
    if currency_dir.exists():
        pages = {p.stem: p.read_text(encoding="utf-8") for p in currency_dir.glob("*.html")}
        currency_mechanics = parse_currency_pages(pages)

    prices: dict[str, float] = {}
    economy_path = omens_dir / "economy_divine.html"
    if economy_path.exists():
        prices = parse_economy_divine(economy_path.read_text(encoding="utf-8"))

    sources = [
        {
            "name": "Craft of Exile PoE2 dataset",
            "url": COE_URL,
            "fetched_at": datetime.fromtimestamp(coe_path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "sha256": sha256_of(coe_path),
        }
    ]
    if omens:
        omens_path = omens_dir / "omens.html"
        sources.append(
            {
                "name": "poe2db.tw omen catalog",
                "url": POE2DB_OMENS_URL,
                "fetched_at": datetime.fromtimestamp(omens_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "sha256": sha256_of(omens_path),
            }
        )
    if prices:
        sources.append(
            {
                "name": "poe2db.tw live economy (Divine Orb terms)",
                "url": POE2DB_ECONOMY_URL,
                "fetched_at": datetime.fromtimestamp(economy_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "sha256": sha256_of(economy_path),
            }
        )

    gamedata = {
        "meta": {
            "built_at": datetime.now(tz=timezone.utc).isoformat(),
            "sources": sources,
        },
        "base_groups": parsed["base_groups"],
        "bases": parsed["bases"],
        "mods": parsed["mods"],
        "tiers": parsed["tiers"],
        "omens": omens,
        "currency_mechanics": currency_mechanics,
        "essences": parsed["essences"],
        "socketables_raw": parsed["socketables_raw"],
        "catalysts_raw": parsed["catalysts_raw"],
        "prices": prices,
    }

    # Validate against our own schema before writing -- catches drift between this
    # build script and the loader early, rather than at first `poe2craft` run.
    validated = GameDataFile.model_validate(gamedata)

    COMPILED.parent.mkdir(parents=True, exist_ok=True)
    COMPILED.write_text(
        json.dumps(json.loads(validated.model_dump_json()), indent=1, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {COMPILED} ({COMPILED.stat().st_size / 1024:.0f} KiB)")
    print(f"  base_groups={len(gamedata['base_groups'])} bases={len(gamedata['bases'])} "
          f"mods={len(gamedata['mods'])} tiers={len(gamedata['tiers'])} "
          f"omens={len(omens)} currency_mechanics={len(currency_mechanics)} "
          f"essences={len(parsed['essences'])} prices={len(prices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
