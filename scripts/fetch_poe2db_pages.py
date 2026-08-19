"""Manual-run refresh of the small, targeted set of poe2db.tw pages this project
needs (omen catalog + currency mechanic descriptions -- the only two things
Craft of Exile's dataset doesn't have at all). Never invoked at package runtime.

Usage: uv run python scripts/fetch_poe2db_pages.py
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

BASE = "https://poe2db.tw/us"
DEST_DIR = Path(__file__).resolve().parent.parent / "data" / "vendor" / "poe2db"
HEADERS = {"User-Agent": "poe2craft/0.1 (personal, non-commercial)"}

# Currency pages relevant to the in-scope action set (see docs/design_notes.md
# for what's out of scope). Page slugs match poe2db.tw's URL convention.
CURRENCY_PAGES = [
    "Orb_of_Transmutation",
    "Orb_of_Augmentation",
    "Orb_of_Alchemy",
    "Regal_Orb",
    "Orb_of_Annulment",
    "Chaos_Orb",
    "Exalted_Orb",
    "Divine_Orb",
    "Fracturing_Orb",
]


def _fetch(slug: str, dest: Path) -> None:
    resp = requests.get(f"{BASE}/{slug}", timeout=30, headers=HEADERS)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resp.text, encoding="utf-8")
    print(f"Wrote {dest} ({len(resp.text) / 1024:.0f} KiB)")
    time.sleep(1)  # be polite -- this is a small, infrequent, manual refresh, not a crawl


def main() -> int:
    _fetch("Omen", DEST_DIR / "omens.html")
    for slug in CURRENCY_PAGES:
        _fetch(slug, DEST_DIR / "currency" / f"{slug}.html")
    print("Now run: uv run python scripts/build_gamedata.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
