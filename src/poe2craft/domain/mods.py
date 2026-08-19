"""Modifier definitions and per-base tier/weight data, as loaded from the compiled gamedata file.

These are frozen and slotted because they end up as dict keys and get compared by the
million during Monte Carlo sampling and value iteration — cheap construction/hashing/
equality matters here far more than it would in a typical data-model class.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from poe2craft.domain.ids import BaseId, GroupKey, ModId


class Affix(str, Enum):
    PREFIX = "prefix"
    SUFFIX = "suffix"
    CORRUPTED = "corrupted"
    SOCKET = "socket"


class ModCategory(str, Enum):
    """Coarse source-category (CoE's `id_mgroup`). Not the mutual-exclusion key -- see
    ModDef.group_keys / GroupKey for that."""

    NORMAL = "normal"
    DESECRATED = "desecrated"
    ESSENCE_ONLY = "essence_only"


# CoE's `id_mgroup` values, mapped to the categories above.
MGROUP_TO_CATEGORY: dict[str, ModCategory] = {
    "1": ModCategory.NORMAL,
    "10": ModCategory.DESECRATED,
    "13": ModCategory.ESSENCE_ONLY,
}

# Mechanics the v1 solver acts on -- only NORMAL-category prefix/suffix mods are
# ever placed in the weighted roll pool. Desecrated/Essence-only/corrupted/socket
# mods are still parsed and carried through the compiled gamedata for future
# extension, just never sampled by engine.pool.
ROLLABLE_CATEGORY = ModCategory.NORMAL
ROLLABLE_AFFIXES = (Affix.PREFIX, Affix.SUFFIX)


def solo_group_key(mod_id: ModId) -> GroupKey:
    """Synthetic exclusion-group key for a mod with no shared `modgroups` family,
    so the same exact mod still can't roll onto an item twice."""
    return GroupKey(f"__solo__{mod_id}")


@dataclass(frozen=True, slots=True)
class ModDef:
    id: ModId
    name: str
    affix: Affix
    category: ModCategory
    group_keys: frozenset[GroupKey]
    hybrid: bool = False
    tags: frozenset[str] = frozenset()
    """Broad category slugs (e.g. "fire", "caster", "life") from CoE's
    `mtypes` data -- only 57% of rollable mods have any. Used for Omen of
    Homogenising Coronation/Exaltation ("same type as an existing modifier"),
    the only thing in this project that needs them."""

    def is_rollable(self) -> bool:
        return self.category is ROLLABLE_CATEGORY and self.affix in ROLLABLE_AFFIXES


@dataclass(frozen=True, slots=True)
class ModTierEntry:
    """One weighted, ilvl-gated tier of a modifier, on one specific base item.

    `value_ranges` holds one (low, high) pair per rollable numeric value the mod
    grants -- most mods have exactly one, hybrid mods can have several rolled
    together (e.g. a combined "+life / +mana" tier).
    """

    mod_id: ModId
    base_id: BaseId
    ilvl: int
    weight: int
    value_ranges: tuple[tuple[float, float], ...]
    tord: int = 0
    alias: str | None = None
