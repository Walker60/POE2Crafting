"""Action *shapes* -- enums and the structural Action/OmenModifier protocols.

Concrete outcome logic (the actual weighted sampling, mod removal, etc.) lives in
`poe2craft.engine`, which builds a registry of objects satisfying the `Action`
protocol below. Keeping the shape here and the behavior in engine/ mirrors the
data/domain vs. simulation split in the project plan.
"""
from __future__ import annotations

import random
from enum import Enum
from typing import Protocol

from poe2craft.domain.items import Item


class ActionKind(str, Enum):
    TRANSMUTATION = "transmutation"
    AUGMENTATION = "augmentation"
    ALCHEMY = "alchemy"
    REGAL = "regal"
    DIVINE = "divine"
    ANNULMENT = "annulment"
    CHAOS = "chaos"
    EXALTED = "exalted"
    FRACTURE = "fracture"
    ESSENCE = "essence"
    PERFECT_ESSENCE = "perfect_essence"
    DESECRATION = "desecration"


class BoneFamily(str, Enum):
    """Which gear-slot family a Desecration bone targets -- confirmed against
    several current PoE2 guides (poe2db.tw doesn't document Desecration at
    all, 2026-08-19): Jawbone = one/two-handed weapons + Quiver, Rib = Body
    Armour/Boots/Gloves/Helmets, Collarbone = Amulet/Ring/Belt, Cranium =
    Jewels. See docs/design_notes.md."""

    JAWBONE = "jawbone"
    RIB = "rib"
    COLLARBONE = "collarbone"
    CRANIUM = "cranium"


class BoneTier(str, Enum):
    """Gnawed (cheap, only usable on an item ilvl<=64) -> Preserved (no
    restriction) -> Ancient (guarantees the revealed mod's own tier requires
    ilvl>=40) -- the same shape as CurrencyTier's Base/Greater/Perfect, just
    named differently for bones."""

    GNAWED = "gnawed"
    PRESERVED = "preserved"
    ANCIENT = "ancient"


class CurrencyTier(str, Enum):
    """Greater/Perfect variants of Transmutation, Augmentation, Regal, Chaos,
    and Exalted Orbs restrict the roll to mods whose tier requires at least a
    minimum modifier level -- confirmed per-currency against poe2db.tw's
    "Minimum Modifier Level" field (see engine.apply.MIN_ILVL_BY_TIER)."""

    BASE = "base"
    GREATER = "greater"
    PERFECT = "perfect"


class OmenKind(str, Enum):
    """Confirmed against poe2db.tw's omen catalog (2026-08-18) for everything
    except the Desecration-related entries, which poe2db doesn't document at
    all -- those were confirmed against several current PoE2 guides instead
    (2026-08-19, see docs/design_notes.md). Not every omen is modeled --
    Catalysing Exaltation needs Catalyst quality tracking (out of scope), the
    4 Waystone "Chaotic ..." omens need Waystone-specific tag data (out of
    scope), and Omen of Blackblooded/Liege/Sovereign (restricts a Desecration
    reveal to "Lich" modifiers) has no confirmed tag data to classify those
    mods by -- see docs/design_notes.md."""

    DEXTRAL_ANNULMENT = "dextral_annulment"  # next Annulment only removes a suffix
    SINISTRAL_ANNULMENT = "sinistral_annulment"  # next Annulment only removes a prefix
    GREATER_ANNULMENT = "greater_annulment"  # next Annulment removes two modifiers
    LIGHT = "light"  # next Annulment only removes a Desecrated modifier
    DEXTRAL_EXALTATION = "dextral_exaltation"  # next Exalted Orb only adds a suffix
    SINISTRAL_EXALTATION = "sinistral_exaltation"  # next Exalted Orb only adds a prefix
    GREATER_EXALTATION = "greater_exaltation"  # next Exalted Orb adds two modifiers
    SINISTRAL_ALCHEMY = "sinistral_alchemy"  # next Alchemy maxes out prefixes
    DEXTRAL_ALCHEMY = "dextral_alchemy"  # next Alchemy maxes out suffixes
    SINISTRAL_CORONATION = "sinistral_coronation"  # next Regal Orb only adds a prefix
    DEXTRAL_CORONATION = "dextral_coronation"  # next Regal Orb only adds a suffix
    HOMOGENISING_CORONATION = "homogenising_coronation"  # next Regal Orb adds a mod of the same type as an existing one
    HOMOGENISING_EXALTATION = "homogenising_exaltation"  # next Exalted Orb adds a mod of the same type as an existing one
    SINISTRAL_ERASURE = "sinistral_erasure"  # next Chaos Orb only removes a prefix
    DEXTRAL_ERASURE = "dextral_erasure"  # next Chaos Orb only removes a suffix
    WHITTLING = "whittling"  # next Chaos Orb removes the lowest-level modifier
    SINISTRAL_CRYSTALLISATION = "sinistral_crystallisation"  # next Perfect Essence only removes a prefix
    DEXTRAL_CRYSTALLISATION = "dextral_crystallisation"  # next Perfect Essence only removes a suffix
    SINISTRAL_NECROMANCY = "sinistral_necromancy"  # next Desecration reveal only shows prefixes
    DEXTRAL_NECROMANCY = "dextral_necromancy"  # next Desecration reveal only shows suffixes
    ABYSSAL_ECHOES = "abyssal_echoes"  # next Desecration reveal can be rerolled once before picking


class Action(Protocol):
    """Structural protocol every action (and omen-wrapped action) satisfies."""

    name: str
    kind: ActionKind

    def applicable(self, item: Item) -> bool:
        """Whether this action can legally be used on `item` right now."""
        ...

    def cost(self) -> float:
        """Relative currency cost, for the cost-minimizing solver objective."""
        ...

    def outcome(self, item: Item, rng: random.Random) -> Item:
        """Draw one concrete outcome. Deterministic actions always return the same
        item; stochastic actions draw from the real game's distribution -- callers
        wanting the *distribution* call this repeatedly (see solver.model_learning)."""
        ...
