"""Maps this project's mod ids to pathofexile.com/trade2's internal stat ids
(e.g. `explicit.stat_3299347043`), so a target/rolled mod can become a trade
search filter. Runs only at build time (`scripts/build_trade_stat_mapping.py`
-> committed `data/compiled/trade_stat_mapping.json`) -- a live crafting
session only ever does a flat dict lookup against that file, never a fuzzy
match, so match quality is a build-time concern, not a runtime surprise.

`ModDef.name` (Craft of Exile's raw template text, e.g. "#% increased
Armour") is expected to be *close* to trade's stat text but not guaranteed
identical -- wording/rounding/pluralization can differ. Text matching here
is deliberately conservative (normalize + exact match on the normalized
form); anything that doesn't match exactly lands in `unmatched`, to be
either accepted as a real gap or added to `_STAT_ID_OVERRIDE` after manual
review -- the same hand-reviewed-override posture this project already uses
for CoE's orphan base ids (`data.coe_parse._ORPHAN_BASE_PATCH`)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from poe2craft.domain.ids import ModId
from poe2craft.domain.mods import ModDef

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parents[3] / "data" / "compiled" / "trade_stat_mapping.json"

_PLACEHOLDER_RE = re.compile(r"[\d#]+")
_NON_WORD_RE = re.compile(r"[^a-z# ]+")

_STAT_ID_OVERRIDE: dict[str, str] = {
    # mod_id -> trade stat_id, for real cases where normalized text matching
    # gets it wrong (different wording, not just different placeholders).
    # Every entry here needs a comment recording why it was added -- an
    # unreviewed bare mapping is worse than an honest "unmatched" gap. Empty
    # until a real build against live trade data surfaces a mismatch to fix.
}


@dataclass(frozen=True)
class StatEntry:
    id: str
    text: str


def normalize(text: str) -> str:
    """Lowercases, collapses any run of digits/`#` placeholders to a single
    `#`, strips everything else that isn't a letter or space, and collapses
    whitespace -- enough to match "#% increased Armour" against "+#% to
    Armour" *only* when the underlying wording is identical; genuinely
    different wording is left for `_STAT_ID_OVERRIDE` to handle by hand."""
    text = text.lower()
    text = _PLACEHOLDER_RE.sub("#", text)
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())


def parse_stats_catalog(raw: dict) -> list[StatEntry]:
    """Parses `GET /api/trade2/data/stats`'s response: `{"result": [{"id":
    <group>, "entries": [{"id": <stat_id>, "text": <template text>}, ...]},
    ...]}`, grouped by mod domain (explicit/implicit/fractured/pseudo/...).
    Flattened across every group -- restricting to just "explicit" risks
    missing a real match for no benefit, since colliding text across groups
    would mean genuinely identical stats anyway."""
    try:
        groups = raw["result"]
        entries = [StatEntry(id=e["id"], text=e["text"]) for group in groups for e in group["entries"]]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected /trade2/data/stats response shape: {raw!r}") from exc
    if not entries:
        raise ValueError("parsed 0 stat entries from /trade2/data/stats -- response shape likely changed")
    return entries


def build_mod_stat_mapping(mods: dict[ModId, ModDef], stats: list[StatEntry]) -> tuple[dict[ModId, str], list[ModId]]:
    """Returns (mod_id -> stat_id mapping, unmatched mod ids) -- report,
    don't crash, mirroring `coe_parse`'s referential-integrity posture."""
    by_normalized: dict[str, str] = {}
    for entry in stats:
        by_normalized.setdefault(normalize(entry.text), entry.id)

    mapping: dict[ModId, str] = {}
    unmatched: list[ModId] = []
    for mod_id, mod in mods.items():
        if str(mod_id) in _STAT_ID_OVERRIDE:
            mapping[mod_id] = _STAT_ID_OVERRIDE[str(mod_id)]
            continue
        stat_id = by_normalized.get(normalize(mod.name))
        if stat_id is not None:
            mapping[mod_id] = stat_id
        else:
            unmatched.append(mod_id)
    return mapping, unmatched


def load_mod_stat_mapping(path: Path | None = None) -> dict[ModId, str]:
    """Loads the committed `data/compiled/trade_stat_mapping.json` built by
    `scripts/build_trade_stat_mapping.py` -- a flat lookup, no matching logic
    at runtime. Raises `FileNotFoundError` with a pointer to that script if
    it hasn't been built yet."""
    path = path or DEFAULT_MAPPING_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} doesn't exist -- run `uv run python scripts/fetch_trade_stats.py` then "
            "`uv run python scripts/build_trade_stat_mapping.py` first."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {ModId(k): v for k, v in raw.items()}
