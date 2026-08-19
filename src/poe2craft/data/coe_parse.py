"""Parses the vendored Craft of Exile PoE2 dataset (`poecd={...}` JS-wrapped JSON) into
the normalized intermediate dict shape defined by `poe2craft.data.schemas.GameDataFile`
(minus `omens`/`currency_mechanics`, which only poe2db has -- see poe2db_parse.py).

CoE's raw schema has a few sharp edges, found by inspecting the real file rather than
assumed, that this parser exists specifically to handle:
  - `id_mgroup` (a coarse source-category: 1=normal pool, 10=Desecrated, 13=Essence-only)
    is NOT the mutual-exclusion key -- `modgroups` (a JSON-encoded array of family
    strings, often empty) is. A mod with no family still needs a synthetic solo key so
    it can't roll onto the same item twice.
  - `tiers` is keyed by mod id, then by base id, then a list of {ilvl, weighting,
    nvalues, ...} brackets -- weighting is base-specific, not a single flat number
    per mod. `nvalues` is itself a JSON-encoded list of [low, high] pairs (usually
    one, more for hybrid mods).
"""
from __future__ import annotations

import json
import re
from typing import Any

from poe2craft.domain.ids import ModId
from poe2craft.domain.mods import solo_group_key

_WRAPPER_RE = re.compile(r"^\s*poecd\s*=\s*")


def _strip_wrapper(raw: str) -> dict[str, Any]:
    m = _WRAPPER_RE.match(raw)
    if not m:
        raise ValueError("unexpected CoE payload: missing 'poecd=' wrapper")
    body = raw[m.end():].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def _seq(data: dict, key: str) -> list[dict]:
    val = data.get(key) or {}
    return val.get("seq", [])


AFFIX_VALUES = {"prefix", "suffix", "corrupted", "socket"}
MGROUP_TO_CATEGORY = {"1": "normal", "10": "desecrated", "13": "essence_only"}


def _parse_base_groups(data: dict) -> list[dict]:
    out = []
    for bg in _seq(data, "bgroups"):
        out.append(
            {
                "id": bg["id_bgroup"],
                "name": bg["name_bgroup"],
                "max_affix": int(bg["max_affix"]),
                "max_sockets": int(bg.get("max_sockets") or 0),
            }
        )
    return out


def _parse_bases(data: dict) -> list[dict]:
    out = []
    for b in _seq(data, "bases"):
        out.append(
            {
                "id": b["id_base"],
                "name": b["name_base"],
                "bgroup_id": b["id_bgroup"],
                "is_jewellery": b.get("is_jewellery") == "1",
            }
        )
    return out


# `bases.seq` is missing a handful of base ids that `basemods`/`tiers` reference
# anyway (found by inspecting the real dataset: CoE's own base list hadn't been
# synced with a few patch-0.5 hybrid-attribute armour bases at the time this was
# vendored). Rather than silently dropping those mods' tier data, patch in the
# ones identifiable from their `bitems` name/art (hybrid STR/DEX/INT armour) or
# from their referenced modifier pool (see id 200 below), and park anything
# left over in a synthetic "Unknown" bucket so referential integrity holds
# without inventing false certainty about what they are.
_ORPHAN_BASE_PATCH: dict[str, dict] = {
    "51": {"name": "Body Armour (STR/DEX/INT)", "bgroup_id": "2", "is_jewellery": False},
    "230": {"name": "Helmet (STR/DEX/INT)", "bgroup_id": "4", "is_jewellery": False},
    "231": {"name": "Gloves (STR/DEX/INT)", "bgroup_id": "5", "is_jewellery": False},
    "232": {"name": "Boots (STR/DEX/INT)", "bgroup_id": "3", "is_jewellery": False},
    # Identified 2026-08-19 by cross-referencing `modbases`/`basemods`, not
    # `bitems` (no name/art exists for this one either): every one of id 200's
    # 177 referenced mods carries `id_mgroup` 1 or 10, the same two mgroups
    # Ruby/Emerald/Sapphire (ids 26/27/28, the "Jewels" bgroup) draw from --
    # 172/177 are literally in the union of those three jewels' own mod pools,
    # and the 5 that aren't ("#% increased Weapon Swap Speed", "Aura Skills
    # have #% increased Magnitudes", "#% increased Minion Accuracy Rating",
    # "#% increased Energy Shield Recharge Rate", "#% increased Warcry Buff
    # Effect") are exactly the kind of attribute-agnostic mods an uncoloured
    # jewel (no Str/Dex/Int requirement) would carry that a colour-locked one
    # wouldn't. Treated as a 4th, uncoloured Jewels-bgroup base on that basis.
    "200": {"name": "Jewel (Uncoloured)", "bgroup_id": "9", "is_jewellery": False},
}
# Also identified 2026-08-19 the same way: id 68's entire 32-mod pool is an
# exact subset of Ruby/Emerald/Sapphire's own combined pool (all id_mgroup=10,
# the same mgroup Ruby/Emerald/Sapphire already include) -- it grants nothing
# a real player couldn't already get from one of those three named jewels.
# That, plus no `bitems` name/art and no CoE bases.seq entry at all, makes it
# look like an internal CoE bookkeeping artifact rather than a distinct real
# item -- excluded from `bases` entirely (its tier data is simply never
# surfaced) rather than given a name that would misrepresent it as pickable.
_ORPHAN_BASE_EXCLUDE: frozenset[str] = frozenset({"68"})
_UNKNOWN_BGROUP_ID = "0"


def _patch_orphan_bases(data: dict, bases: list[dict], base_groups: list[dict]) -> None:
    known_ids = {b["id"] for b in bases}
    referenced_ids: set[str] = set(data.get("basemods", {}).keys())
    for per_base in (data.get("tiers") or {}).values():
        referenced_ids.update(per_base.keys())

    orphans = sorted(referenced_ids - known_ids - _ORPHAN_BASE_EXCLUDE, key=int)
    if not orphans:
        return

    needs_unknown_bgroup = any(o not in _ORPHAN_BASE_PATCH for o in orphans)
    if needs_unknown_bgroup and not any(g["id"] == _UNKNOWN_BGROUP_ID for g in base_groups):
        base_groups.append({"id": _UNKNOWN_BGROUP_ID, "name": "Unknown", "max_affix": 6, "max_sockets": 0})

    for oid in orphans:
        patch = _ORPHAN_BASE_PATCH.get(oid)
        if patch:
            bases.append({"id": oid, **patch})
        else:
            bases.append(
                {"id": oid, "name": f"Unknown Base {oid}", "bgroup_id": _UNKNOWN_BGROUP_ID, "is_jewellery": False}
            )


def _parse_group_keys(modgroups_raw: str | None, mod_id: str) -> list[str]:
    if modgroups_raw:
        parsed = json.loads(modgroups_raw)
        if parsed:
            return list(parsed)
    return [solo_group_key(ModId(mod_id))]


def _parse_mtypes_lookup(data: dict) -> dict[str, str]:
    """id_mtype -> poedb_id (a stable slug like "fire"/"caster"/"life_regen"),
    the broad-category data `modifiers.mtypes` references. This is what Omen
    of Homogenising Coronation/Exaltation ("adds a modifier of the same *type*
    as an existing one") actually matches on -- confirmed by resolving real
    examples (e.g. "# Life Regeneration per second" -> ["Life Regen", "Life"])
    against category names that read exactly like PoE's own broad groupings
    (matches the categories Catalysts target, e.g. "attribute", "elemental")."""
    return {t["id_mtype"]: t["poedb_id"] for t in _seq(data, "mtypes")}


def _parse_mod_tags(mtypes_raw: str | None, mtypes_lookup: dict[str, str]) -> list[str]:
    if not mtypes_raw:
        return []
    ids = [x for x in mtypes_raw.split("|") if x]
    return [mtypes_lookup[i] for i in ids if i in mtypes_lookup]


def _parse_mods(data: dict, warnings: list[str]) -> list[dict]:
    mtypes_lookup = _parse_mtypes_lookup(data)
    out = []
    for m in _seq(data, "modifiers"):
        affix = m["affix"]
        if affix not in AFFIX_VALUES:
            warnings.append(f"mod {m['id_modifier']}: unknown affix {affix!r}, skipping")
            continue
        category = MGROUP_TO_CATEGORY.get(m["id_mgroup"])
        if category is None:
            warnings.append(
                f"mod {m['id_modifier']}: unknown id_mgroup {m['id_mgroup']!r}, skipping"
            )
            continue
        out.append(
            {
                "id": m["id_modifier"],
                "name": m["name_modifier"],
                "affix": affix,
                "category": category,
                "group_keys": _parse_group_keys(m.get("modgroups"), m["id_modifier"]),
                "hybrid": m.get("hybrid") == "1",
                "tags": _parse_mod_tags(m.get("mtypes"), mtypes_lookup),
            }
        )
    return out


def _parse_value_ranges(nvalues_raw: str | None) -> list[tuple[float, float]]:
    """`nvalues` holds one entry per rolled value slot on the mod (hybrid mods with
    two independent stats have two slots, e.g. "#% increased Light Radius, #%
    increased Mana Regeneration Rate"). Each slot is inconsistently shaped in the
    raw data, confirmed by cross-referencing against mod names/tiers rather than
    assumed:
      - a ranged slot as its own `[low, high]` list (the common case), or
      - a flat (non-ranging) slot as a bare number.
    This is ambiguous in exactly one shape -- a bare 2-element list with no
    wrapping (e.g. `[1, 100]`) could mean "one range, 1 to 100" or "two flat
    slots, 1 and 100". Cross-referencing against mod names for both readings
    found real examples of the two-flat-slots reading (e.g. a hybrid mod
    granting a flat "#% chance to Bleed" *and* a flat "#% increased Waystones
    found", unrelated numbers, not a range) and no way to distinguish it from a
    true bare range using only this data, so every element is always treated as
    its own slot for consistency. A handful of true single-range mods (e.g.
    "Adds # to # Fire damage") therefore get split into two degenerate flat
    slots instead of one range -- a known, harmless-to-the-solver
    over-approximation (see docs/design_notes.md) since v1's state/action model
    never depends on exact numeric values, only on which mods are present.
    """
    if nvalues_raw is None:
        return []
    parsed = json.loads(nvalues_raw)
    if not parsed:
        return []
    out = []
    for slot in parsed:
        pair = slot if isinstance(slot, list) else [slot]
        if len(pair) >= 2:
            out.append((float(pair[0]), float(pair[1])))
        elif len(pair) == 1:
            out.append((float(pair[0]), float(pair[0])))
    return out


def _parse_tiers(data: dict, warnings: list[str]) -> list[dict]:
    out = []
    tiers = data.get("tiers") or {}
    for mod_id, per_base in tiers.items():
        for base_id, brackets in per_base.items():
            if base_id in _ORPHAN_BASE_EXCLUDE:
                continue  # see _ORPHAN_BASE_EXCLUDE's comment -- deliberately not a real base
            for bracket in brackets:
                try:
                    value_ranges = _parse_value_ranges(bracket["nvalues"])
                except (TypeError, ValueError, KeyError):
                    warnings.append(
                        f"tier mod={mod_id} base={base_id}: bad nvalues {bracket.get('nvalues')!r}"
                    )
                    value_ranges = []
                out.append(
                    {
                        "mod_id": mod_id,
                        "base_id": base_id,
                        "ilvl": int(bracket["ilvl"]),
                        "weight": int(bracket["weighting"]),
                        "value_ranges": value_ranges,
                        "tord": int(bracket.get("tord") or 0),
                        "alias": bracket.get("alias"),
                    }
                )
    return out


def _parse_essences(data: dict, warnings: list[str]) -> list[dict]:
    from poe2craft.domain.essences import split_essence_name

    out = []
    for e in _seq(data, "essences"):
        family, tier_kind = split_essence_name(e["name_essence"])
        try:
            per_base_raw: dict = json.loads(e["tiers"])
        except (TypeError, ValueError, KeyError):
            warnings.append(f"essence {e['id_essence']} ({e['name_essence']!r}): bad tiers field")
            continue
        per_base = {}
        for base_id, outer in per_base_raw.items():
            if len(outer) != 1:
                warnings.append(
                    f"essence {e['id_essence']} base={base_id}: expected exactly one outer tier entry, got {len(outer)}"
                )
                continue
            grants = [{"mod_id": g["mod"], "ilvl": int(g["ilvl"])} for g in outer[0]]
            per_base[base_id] = grants
        out.append(
            {
                "id": e["id_essence"],
                "name": e["name_essence"],
                "family": family,
                "tier_kind": tier_kind.value,
                "per_base": per_base,
            }
        )
    return out


def parse_coe(raw: str) -> dict[str, Any]:
    """Returns a dict with keys base_groups/bases/mods/tiers/essences/
    socketables_raw/catalysts_raw plus a `_warnings` list of non-fatal parse issues
    (bad/unrecognized records that were skipped rather than raising)."""
    data = _strip_wrapper(raw)
    warnings: list[str] = []
    base_groups = _parse_base_groups(data)
    bases = _parse_bases(data)
    _patch_orphan_bases(data, bases, base_groups)
    return {
        "base_groups": base_groups,
        "bases": bases,
        "mods": _parse_mods(data, warnings),
        "tiers": _parse_tiers(data, warnings),
        "essences": _parse_essences(data, warnings),
        "socketables_raw": _seq(data, "socketables"),
        "catalysts_raw": _seq(data, "catalysts"),
        "_warnings": warnings,
    }


def referential_integrity_report(parsed: dict[str, Any]) -> list[str]:
    """Cheap sanity pass: every id a tier references must exist among the parsed
    mods/bases. Returns human-readable problem descriptions; does not raise, since
    upstream community data is known to have occasional gaps."""
    problems: list[str] = []
    mod_ids = {m["id"] for m in parsed["mods"]}
    base_ids = {b["id"] for b in parsed["bases"]}
    bgroup_ids = {g["id"] for g in parsed["base_groups"]}

    for b in parsed["bases"]:
        if b["bgroup_id"] not in bgroup_ids:
            problems.append(f"base {b['id']} ({b['name']}) references missing bgroup {b['bgroup_id']}")

    missing_mod = missing_base = 0
    for t in parsed["tiers"]:
        if t["mod_id"] not in mod_ids:
            missing_mod += 1
        if t["base_id"] not in base_ids:
            missing_base += 1
    if missing_mod:
        problems.append(f"{missing_mod} tier records reference a mod id not in `mods` (likely non-rollable categories not parsed, e.g. corrupted-only defs)")
    if missing_base:
        problems.append(f"{missing_base} tier records reference a base id not in `bases`")
    return problems
