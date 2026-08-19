"""Parses targeted poe2db.tw HTML pages for things Craft of Exile's dataset
doesn't have at all: the omen catalog, currency mechanic descriptions, and
(see `parse_economy_divine`) live currency/omen/essence prices in Divine Orb
terms.

The omen catalog and currency-mechanic parsers are Phase 2 of the project
plan and are intentionally stubs until then -- `scripts/build_gamedata.py`
calls these functions only when the corresponding vendored HTML files exist
under data/vendor/poe2db/, so Phase 1 (bases/mods/tiers from Craft of Exile)
works end-to-end without this module doing anything yet.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


def parse_omens(html: str) -> list[dict]:
    """Parse poe2db.tw's omen listing page into
    [{id, name, modifies, effect}, ...]. `modifies` should be an ActionKind value
    (see poe2craft.domain.actions.ActionKind) -- mapping omen names to the action
    they wrap is inherently a hand-maintained lookup (poe2db's text doesn't tag
    this structurally), refined once the real page is fetched in Phase 2.
    """
    soup = BeautifulSoup(html, "lxml")
    del soup  # placeholder -- real extraction lands in Phase 2
    return []


def parse_currency_pages(pages: dict[str, str]) -> list[dict]:
    """Parse a {page_stem: html} map of individual poe2db.tw currency pages into
    [{action_kind, display_name, description, deterministic}, ...]."""
    out: list[dict] = []
    del pages
    return out


_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_economy_divine(html: str) -> dict[str, float]:
    """Parses poe2db.tw's "Economy_divine" page: a live-updated table of every
    traded currency/omen/essence/unique paired against Divine Orb, as
    "<24h Value> <name> <-> 1 Divine Orb <24h volume traded>". "24h Value" is
    how many units of that item trade for 1 Divine Orb -- confirmed against a
    known real-world ratio (Chaos Orb came back ~10 per Divine, matching
    expectations; a naive wrong-column read earlier in this project's
    research gave a nonsensical ~685,000 per Divine, which is how this was
    caught and fixed before landing here).

    Returns {name: divine_cost}, i.e. already inverted (divine_cost = 1 /
    units_per_divine) so callers get "how much this one use costs in Divine
    Orb terms" directly. Names are exactly as displayed (e.g. "Chaos Orb",
    "Greater Chaos Orb", "Omen of Whittling", "Perfect Essence of the Body"),
    matching this project's own Action.name strings for the currencies/omens
    it models. Rows this project doesn't otherwise use (unique items, runes,
    other omens/essences) are still returned -- harmless, just unused."""
    prices: dict[str, float] = {}
    for row in _ROW_RE.findall(html):
        text = _TAG_RE.sub("|", row)
        parts = [p.strip() for p in re.sub(r"\|+", "|", text).strip("|").split("|") if p.strip()]
        if len(parts) < 4 or parts[2] != "1" or parts[3] != "Divine Orb":
            continue
        try:
            units_per_divine = float(parts[0].replace(",", ""))
        except ValueError:
            continue
        if units_per_divine <= 0:
            continue
        prices.setdefault(parts[1], 1.0 / units_per_divine)
    prices.setdefault("Divine Orb", 1.0)
    return prices
