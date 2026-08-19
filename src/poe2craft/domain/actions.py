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


class CurrencyTier(str, Enum):
    """Greater/Perfect variants of Transmutation, Augmentation, Regal, Chaos,
    and Exalted Orbs restrict the roll to mods whose tier requires at least a
    minimum modifier level -- confirmed per-currency against poe2db.tw's
    "Minimum Modifier Level" field (see engine.apply.MIN_ILVL_BY_TIER)."""

    BASE = "base"
    GREATER = "greater"
    PERFECT = "perfect"


class OmenKind(str, Enum):
    """Confirmed against poe2db.tw's omen catalog (2026-08-18). Not every omen
    poe2db lists is modeled here -- Catalysing Exaltation needs Catalyst
    quality tracking (out of scope), Omen of Light needs Desecrated mod
    support (out of scope), and the 4 Waystone "Chaotic ..." omens need
    Waystone-specific tag data and are a narrower use case -- see
    docs/design_notes.md."""

    DEXTRAL_ANNULMENT = "dextral_annulment"  # next Annulment only removes a suffix
    SINISTRAL_ANNULMENT = "sinistral_annulment"  # next Annulment only removes a prefix
    GREATER_ANNULMENT = "greater_annulment"  # next Annulment removes two modifiers
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
