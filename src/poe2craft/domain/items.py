"""Item state: bases/base-groups (static reference data) and the Item itself (a crafting
state). Item and RolledAffix are deliberately denormalized -- each RolledAffix carries its
own group-exclusion keys and value ranges rather than requiring a gamedata lookup to
resolve them, since these objects are constructed and hashed by the million during
Monte Carlo model learning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from poe2craft.domain.ids import BaseGroupId, BaseId, GroupKey, ModId
from poe2craft.domain.mods import Affix


class Rarity(str, Enum):
    NORMAL = "normal"
    MAGIC = "magic"
    RARE = "rare"


@dataclass(frozen=True, slots=True)
class BaseGroup:
    """One of CoE's `bgroups` (Body Armours, Boots, Jewellery, Jewels, ...)."""

    id: BaseGroupId
    name: str
    max_affix: int
    max_sockets: int

    @property
    def max_prefix(self) -> int:
        return self.max_affix // 2

    @property
    def max_suffix(self) -> int:
        return self.max_affix // 2


@dataclass(frozen=True, slots=True)
class BaseItemDef:
    """One of CoE's `bases` (e.g. "Body Armour (STR)", "Amulet", "Ruby")."""

    id: BaseId
    name: str
    bgroup_id: BaseGroupId
    is_jewellery: bool


@dataclass(frozen=True, slots=True)
class RolledAffix:
    mod_id: ModId
    affix: Affix
    group_keys: frozenset[GroupKey]
    value_ranges: tuple[tuple[float, float], ...]
    values: tuple[float, ...]
    fractured: bool = False
    ilvl: int = 0
    """The tier's ilvl requirement this affix was actually rolled at -- needed
    for Omen of Whittling (Chaos Orb removes the *lowest-level* modifier, a
    deterministic choice rather than a random one). Defaults to 0 so
    hand-built test fixtures that don't care about it don't need to set it."""


@dataclass(frozen=True, slots=True)
class Item:
    base_id: BaseId
    ilvl: int
    rarity: Rarity
    prefixes: tuple[RolledAffix, ...] = field(default_factory=tuple)
    suffixes: tuple[RolledAffix, ...] = field(default_factory=tuple)
    corrupted: bool = False

    @property
    def affixes(self) -> tuple[RolledAffix, ...]:
        return self.prefixes + self.suffixes

    @property
    def prefix_count(self) -> int:
        return len(self.prefixes)

    @property
    def suffix_count(self) -> int:
        return len(self.suffixes)

    @property
    def mod_ids(self) -> frozenset[ModId]:
        return frozenset(a.mod_id for a in self.affixes)

    def occupied_group_keys(self) -> frozenset[GroupKey]:
        return frozenset(g for a in self.affixes for g in a.group_keys)

    def has_group(self, group_keys: frozenset[GroupKey]) -> bool:
        return bool(self.occupied_group_keys() & group_keys)
