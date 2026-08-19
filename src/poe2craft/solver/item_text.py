"""Parses a Path of Exile 2 item's clipboard export text (hover the item
in-game, Ctrl+C or Ctrl+Alt+C, paste here) into the pieces `item_from_report`
needs: base, ilvl, rarity, and (mod_id, tier_ilvl) pairs.

Two things make this inherently best-effort rather than exact, documented in
depth in the project plan:

1. `GameData.bases` only has archetype-level entries ("Amulet", "Body Armour
   (STR/DEX)") -- a real item's specific base-type name almost never matches
   one of those literally. Resolution goes through `Item Class:` (+ a
   `Requirements:` Str/Dex/Int heuristic for the armour slots that split by
   attribute) rather than the item's own flavour name in most cases.
2. Some archetypes can't be told apart at all from pasted text with the data
   this project has (Wand/Staff split by damage-type element, since we don't
   have a specific-base-name -> element mapping). These come back as
   `ambiguous_bases` for the caller to ask the user to pick manually, rather
   than silently guessing -- the same "never silently wrong" philosophy as
   `item_from_report`/`ConcretizeError` elsewhere in this package.

Unmatched mod lines are surfaced in `unmatched_lines`, not dropped -- often
implicits (which this project doesn't model at all) or a genuine data gap,
either way something a human should glance at before trusting the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import BaseItemDef, Rarity
from poe2craft.domain.mods import Affix, ModDef

_NUM_RE = r"([+-]?\d+(?:\.\d+)?)"
_TRAILING_PARENS_RE = re.compile(r"((?:\s*\([^()]*\))+)\s*$")
_TIER_ANNOTATION_RE = re.compile(r"\(\s*tier\s*:\s*(\d+)\s*\)", re.IGNORECASE)
_IMPLICIT_RE = re.compile(r"\(\s*implicit\s*\)", re.IGNORECASE)
_FOOTER_KEYWORDS = {"corrupted", "unidentified", "mirrored", "unmodifiable", "duplicated"}
_IRREGULAR_PLURALS = {"staves": "staff", "foci": "focus", "warstaves": "warstaff"}


class ItemTextParseError(ValueError):
    """Raised only for genuinely unrecoverable input (empty text, an
    unmodeled Unique, no recognizable header) -- everything else that's
    merely ambiguous or partial is reported back via `ParsedItem` fields
    instead, since partial information is still useful to a caller pre-
    filling a form."""


@dataclass
class ParsedItem:
    base_id: BaseId | None = None
    base_name: str | None = None
    ilvl: int | None = None
    rarity: Rarity | None = None
    mod_reports: list[tuple[ModId, int]] = field(default_factory=list)
    ambiguous_bases: list[BaseItemDef] = field(default_factory=list)
    unmatched_lines: list[str] = field(default_factory=list)


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = [[]]
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if line.startswith("---"):
            blocks.append([])
        elif line:
            blocks[-1].append(line)
    return [b for b in blocks if b]


def _strip_annotations(line: str) -> tuple[str, int | None, bool]:
    """Returns (core text, tier number if a "(Tier: N)" suffix was present,
    whether an "(implicit)" suffix was present)."""
    m = _TRAILING_PARENS_RE.search(line)
    if not m:
        return line, None, False
    trailer = m.group(1)
    core = line[: m.start()].strip()
    tier_m = _TIER_ANNOTATION_RE.search(trailer)
    is_implicit = bool(_IMPLICIT_RE.search(trailer))
    return core, (int(tier_m.group(1)) if tier_m else None), is_implicit


def _compile_mod_pattern(name: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in name.split("#")]
    return re.compile("^" + _NUM_RE.join(parts) + "$")


def _stem_of(base_name: str) -> str:
    m = re.match(r"^(.*) \([A-Z/]+\)$", base_name)
    if m:
        return m.group(1)
    m = re.match(r"^(?:Chaos|Fire|Ice|Lightning|Physical) (Wand|Staff)$", base_name)
    if m:
        return m.group(1)
    return base_name


def _resolve_base_by_name(gamedata: GameData, header_lines: list[str]) -> BaseItemDef | None:
    by_name = {b.name.lower(): b for b in gamedata.bases.values()}
    for ln in header_lines:
        base = by_name.get(ln.lower())
        if base is not None:
            return base
    return None


def _parse_requirement_attrs(blocks: list[list[str]]) -> frozenset[str]:
    for block in blocks:
        if block[0].lower().startswith("requirements"):
            attrs = set()
            for ln in block[1:]:
                for attr in ("Str", "Dex", "Int"):
                    if ln.lower().startswith(attr.lower() + ":"):
                        attrs.add(attr.upper())
            return frozenset(attrs)
    return frozenset()


def _resolve_base_by_class(
    gamedata: GameData, blocks: list[list[str]], item_class_line: str
) -> tuple[BaseItemDef | None, list[BaseItemDef]]:
    stems: dict[str, list[BaseItemDef]] = {}
    by_bgroup: dict[str, list[BaseItemDef]] = {}
    for base in gamedata.bases.values():
        stems.setdefault(_stem_of(base.name).lower(), []).append(base)
        bgroup_name = gamedata.base_group_of(base.id).name
        by_bgroup.setdefault(bgroup_name.lower(), []).append(base)

    cls = item_class_line.split(":", 1)[1].strip().lower()
    for candidate in (cls, _IRREGULAR_PLURALS.get(cls, cls), cls.rstrip("s")):
        bases = stems.get(candidate)
        if bases:
            if len(bases) == 1:
                return bases[0], []
            attrs = _parse_requirement_attrs(blocks)
            if attrs:
                for base in bases:
                    m = re.search(r"\(([A-Z/]+)\)$", base.name)
                    if m and frozenset(m.group(1).split("/")) == attrs:
                        return base, []
            return None, bases

    bases = by_bgroup.get(cls)
    if bases:
        return (bases[0], []) if len(bases) == 1 else (None, bases)
    return None, []


def _compile_mod_index(gamedata: GameData, base_id: BaseId) -> list[tuple[ModDef, re.Pattern[str]]]:
    index = []
    for mod_id, tiers in gamedata.all_tiers_by_base.get(base_id, {}).items():
        if not tiers:
            continue
        mod = gamedata.mods.get(mod_id)
        if mod is None or mod.affix not in (Affix.PREFIX, Affix.SUFFIX):
            continue
        index.append((mod, _compile_mod_pattern(mod.name)))
    return index


def _match_tier_by_value(
    gamedata: GameData, base_id: BaseId, mod_id: ModId, max_ilvl: int, values: tuple[float, ...]
) -> int | None:
    candidates = [
        t for t in gamedata.all_tiers_by_base.get(base_id, {}).get(mod_id, []) if t.ilvl <= max_ilvl
    ]
    matches = [
        t
        for t in candidates
        if len(t.value_ranges) == len(values)
        and all(lo - 1e-6 <= v <= hi + 1e-6 for (lo, hi), v in zip(t.value_ranges, values))
    ]
    if not matches:
        return None
    return max(matches, key=lambda t: t.ilvl).ilvl


def _parse_mod_lines(gamedata: GameData, result: ParsedItem, lines: list[str]) -> None:
    assert result.base_id is not None
    index = _compile_mod_index(gamedata, result.base_id)
    max_ilvl = result.ilvl if result.ilvl is not None else 10**9
    for raw_line in lines:
        core, tier_num, is_implicit = _strip_annotations(raw_line)
        if is_implicit:
            continue  # known and intentionally unmodeled -- not a parse failure
        matched = False
        for mod, pattern in index:
            m = pattern.match(core)
            if not m:
                continue
            values = tuple(float(g) for g in m.groups())
            tier_ilvl = None
            if tier_num is not None:
                ranks = gamedata.tier_ranks(result.base_id, mod.id)
                if 1 <= tier_num <= len(ranks):
                    tier_ilvl = ranks[tier_num - 1].ilvl
            if tier_ilvl is None:
                tier_ilvl = _match_tier_by_value(gamedata, result.base_id, mod.id, max_ilvl, values)
            if tier_ilvl is None:
                continue  # text matches the mod, but no tier explains the rolled value(s)
            result.mod_reports.append((mod.id, tier_ilvl))
            matched = True
            break
        if not matched:
            result.unmatched_lines.append(raw_line)


def _find_mod_lines(blocks: list[list[str]]) -> list[str]:
    """Real PoE item text always orders: header -> (property/requirements
    blocks) -> Item Level -> (implicit) -> explicit mods -> (footer). Anchoring
    on the Item Level block lets this skip past damage/requirement blocks
    without having to enumerate every possible property keyword. When that
    anchor is missing (hand-written/partial text), fall back to just the last
    remaining block, rather than every block after the header -- much less
    likely to accidentally sweep in a property block with no anchor to rule
    it out."""
    ilvl_block_idx = None
    for i, block in enumerate(blocks):
        if len(block) == 1 and block[0].lower().startswith("item level:"):
            ilvl_block_idx = i
            break

    candidates: list[list[str]] = []
    for block in blocks[(ilvl_block_idx + 1 if ilvl_block_idx is not None else 1) :]:
        if len(block) == 1 and block[0].strip().lower() in _FOOTER_KEYWORDS:
            break
        if block[0].lower().startswith("note:"):
            break
        if block[0].lower().startswith("requirements"):
            continue
        candidates.append(block)

    if ilvl_block_idx is not None:
        return [ln for block in candidates for ln in block]
    return candidates[-1] if candidates else []


def parse_item_text(gamedata: GameData, text: str, base_id: BaseId | None = None) -> ParsedItem:
    if not text or not text.strip():
        raise ItemTextParseError("no item text provided")

    blocks = _split_blocks(text)
    if not blocks:
        raise ItemTextParseError("couldn't find any content in the pasted text")
    header = blocks[0]

    rarity: Rarity | None = None
    item_class_line: str | None = None
    for ln in header:
        low = ln.lower()
        if low.startswith("rarity:"):
            raw = low.split(":", 1)[1].strip()
            if raw == "unique":
                raise ItemTextParseError("Unique items aren't modeled by this solver")
            try:
                rarity = Rarity(raw)
            except ValueError:
                raise ItemTextParseError(f"unrecognized rarity {raw!r}") from None
        elif low.startswith("item class:"):
            item_class_line = ln

    result = ParsedItem(rarity=rarity)

    for block in blocks:
        if len(block) == 1 and block[0].lower().startswith("item level:"):
            try:
                result.ilvl = int(block[0].split(":", 1)[1].strip())
            except ValueError:
                pass

    if base_id is not None:
        base = gamedata.bases.get(base_id)
        if base is not None:
            result.base_id = base.id
            result.base_name = base.name
    else:
        base = _resolve_base_by_name(gamedata, header)
        ambiguous: list[BaseItemDef] = []
        if base is None and item_class_line is not None:
            base, ambiguous = _resolve_base_by_class(gamedata, blocks, item_class_line)
        if base is not None:
            result.base_id = base.id
            result.base_name = base.name
        else:
            result.ambiguous_bases = ambiguous

    if result.base_id is not None and rarity is not None and rarity is not Rarity.NORMAL:
        mod_lines = _find_mod_lines(blocks)
        if mod_lines:
            _parse_mod_lines(gamedata, result, mod_lines)

    return result
