"""Essence definitions.

Confirmed by inspecting the real vendored data (not assumed): an essence's
power tier (Lesser/Normal/Greater/Perfect) is encoded entirely in its *name*,
as a completely separate CoE `essences` record per tier -- e.g. "Essence of
Abrasion", "Greater Essence of Abrasion", and "Perfect Essence of Abrasion"
are three distinct ids, each with its own `tiers` mapping. The nested
per-base `tiers` field is NOT a tier-progression list (its outer list is
always length 1 for every essence/base pair in the data) -- it's simply "the
mod(s) this one essence guarantees on this one base", occasionally more than
one mod at once (a handful of essences grant 2-3 mods simultaneously).

Non-Perfect essences (Lesser/Normal/Greater, plus a set of uniquely-named
essences with no tier variants at all, e.g. "Adaptive Alloy") guarantee a mod
from the normal rollable pool (CoE `id_mgroup=1`) -- mechanically like a
targeted Regal Orb. Perfect essences guarantee a mod from a dedicated
essence-only pool (`id_mgroup=13`, 75 mods never obtainable any other way) and
additionally remove one existing random mod first -- mechanically like a
targeted, guaranteed-hit Chaos Orb. Confirmed by checking id_mgroup on the
actual granted mod for essences of each tier.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from poe2craft.domain.ids import BaseId, EssenceId, ModId

_TIER_PREFIXES = {
    "Lesser": "lesser",
    "Greater": "greater",
    "Perfect": "perfect",
}


class EssenceTierKind(str, Enum):
    LESSER = "lesser"
    NORMAL = "normal"
    GREATER = "greater"
    PERFECT = "perfect"


def split_essence_name(name: str) -> tuple[str, EssenceTierKind]:
    """("Greater Essence of Abrasion") -> ("Essence of Abrasion", GREATER).
    A name with no recognized tier prefix (regular "Essence of X" names, and
    the ~11 uniquely-named essences like "Adaptive Alloy") is NORMAL tier with
    itself as the family."""
    first, _, rest = name.partition(" ")
    kind_value = _TIER_PREFIXES.get(first)
    if kind_value is not None and rest:
        return rest, EssenceTierKind(kind_value)
    return name, EssenceTierKind.NORMAL


@dataclass(frozen=True, slots=True)
class EssenceGrant:
    mod_id: ModId
    ilvl: int


@dataclass(frozen=True, slots=True)
class EssenceDef:
    id: EssenceId
    name: str
    family: str
    tier_kind: EssenceTierKind
    per_base: dict[BaseId, tuple[EssenceGrant, ...]]

    @property
    def is_perfect(self) -> bool:
        return self.tier_kind is EssenceTierKind.PERFECT
