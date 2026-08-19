"""Builds the flat weighted (mod, tier) pool eligible to roll into one affix slot
on an item right now. This is the single place group-exclusion/ilvl-gating/
base-eligibility rules are applied, so engine.apply and solver.model_learning
both see the same eligibility logic.

The real PoE weighting model draws mod *and* tier together from one flat pool
across every currently-ilvl-unlocked tier of every eligible mod -- not "pick the
mod first, then pick a tier" -- which matters because a low tier of a common mod
can still roll on a high-ilvl item. See docs/design_notes.md.
"""
from __future__ import annotations

from poe2craft.data.loader import GameData
from poe2craft.domain.items import Item, Rarity
from poe2craft.domain.mods import Affix, ModDef, ModTierEntry

PoolEntry = tuple[ModDef, ModTierEntry]

# Magic items always cap at 1 prefix / 1 suffix regardless of base group -- only
# Rare items use the base group's max_affix (3/3 on most slots, fewer on Jewels/
# Charms/Flasks). This is a system-wide rule, not base-group-dependent.
MAGIC_MAX_PER_AFFIX = 1


class NoEligibleModsError(RuntimeError):
    """Raised when an action needs to roll a new affix but nothing is eligible
    (e.g. every group-compatible mod is already ilvl-locked out, or the base has
    no more room). Callers should treat this as `applicable() -> False` having
    been wrong, or as a real dead end worth surfacing rather than swallowing."""


def build_pool(
    gamedata: GameData, item: Item, affix: Affix, min_ilvl: int = 0, required_tags: frozenset[str] | None = None
) -> list[PoolEntry]:
    """`min_ilvl` restricts the pool to tiers requiring at least that modifier
    level -- used by Greater/Perfect currency variants (see
    engine.apply.MIN_ILVL_BY_TIER), which bias toward stronger rolls rather
    than changing how many affixes get added. Base-tier currencies pass the
    default 0 (no restriction beyond the item's own ilvl gate).

    `required_tags`, when given, restricts to mods sharing at least one broad
    category tag with it (e.g. "fire", "life") -- used by Omen of
    Homogenising Coronation/Exaltation. Only ~57% of rollable mods have any
    tag at all, so this can legitimately empty the pool; only ~half of *those*
    mods would ever satisfy an overlap even among tagged mods, since sharing
    *a* tag isn't guaranteed just because both are tagged.

    The affix/ilvl/tags filtering (everything except group-exclusion) is
    cached on `gamedata` via `rollable_entries` -- see its docstring. Only the
    group-exclusion filter below actually needs to run fresh every call, since
    it's the only part that depends on this specific item's current mods."""
    entries = gamedata.rollable_entries(item.base_id, affix, item.ilvl, min_ilvl, required_tags)
    occupied = item.occupied_group_keys()
    if not occupied:
        return entries  # nothing to exclude -- safe to hand back the cached list as-is (no caller mutates it)
    return [(mod, tier) for mod, tier in entries if not (mod.group_keys & occupied)]


def has_room(gamedata: GameData, item: Item, affix: Affix) -> bool:
    if item.rarity is Rarity.MAGIC:
        cap = MAGIC_MAX_PER_AFFIX
    elif item.rarity is Rarity.RARE:
        bg = gamedata.base_group_of(item.base_id)
        cap = bg.max_prefix if affix is Affix.PREFIX else bg.max_suffix
    else:
        return False
    count = item.prefix_count if affix is Affix.PREFIX else item.suffix_count
    return count < cap


def build_combined_pool(
    gamedata: GameData, item: Item, min_ilvl: int = 0, required_tags: frozenset[str] | None = None
) -> list[PoolEntry]:
    """Prefix and suffix pools merged into one flat weighted list, respecting
    each affix type's own room cap -- this is what "add one random affix,
    either type" (Transmutation, Alchemy, Exalted, ...) actually draws from, so
    the prefix/suffix split isn't a separate 50/50 coin flip but follows the
    real relative pool weights."""
    pool: list[PoolEntry] = []
    if has_room(gamedata, item, Affix.PREFIX):
        pool.extend(build_pool(gamedata, item, Affix.PREFIX, min_ilvl=min_ilvl, required_tags=required_tags))
    if has_room(gamedata, item, Affix.SUFFIX):
        pool.extend(build_pool(gamedata, item, Affix.SUFFIX, min_ilvl=min_ilvl, required_tags=required_tags))
    return pool


def build_desecrated_pool(
    gamedata: GameData, item: Item, affix: Affix | None = None, min_ilvl: int = 0
) -> list[PoolEntry]:
    """Like `build_pool`/`build_combined_pool`, but draws from the
    `ModCategory.DESECRATED` pool (ground/corpse-reveal mods, never in the
    general roll pool) instead of the NORMAL-only rollable one -- what a
    Desecration bone action's "reveal 3 candidates" actually samples from.
    `affix=None` returns both sides (each still gated by `has_room`,
    matching `build_combined_pool`'s shape); pass a specific `Affix` to
    restrict one side only (Omen of Sinistral/Dextral Necromancy)."""
    sides = (affix,) if affix is not None else (Affix.PREFIX, Affix.SUFFIX)
    occupied = item.occupied_group_keys()
    pool: list[PoolEntry] = []
    for side in sides:
        if not has_room(gamedata, item, side):
            continue
        entries = gamedata.desecrated_entries(item.base_id, side, item.ilvl, min_ilvl)
        pool.extend((mod, tier) for mod, tier in entries if not (mod.group_keys & occupied))
    return pool


def item_tags(gamedata: GameData, item: Item) -> frozenset[str]:
    """Union of every current affix's broad category tags -- the "existing
    modifier" side of Omen of Homogenising Coronation/Exaltation."""
    tags: set[str] = set()
    for a in item.affixes:
        tags |= gamedata.mods[a.mod_id].tags
    return frozenset(tags)
