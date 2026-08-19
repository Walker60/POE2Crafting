"""Concrete Action implementations for the in-scope currency set (see
docs/design_notes.md for what's excluded and why). Each class satisfies the
`poe2craft.domain.actions.Action` protocol; `build_action_registry(gamedata)`
returns the full set bound to one GameData instance.

Action classification (corrected during research against a naive deterministic/
stochastic split): Transmutation/Augmentation/Alchemy/Regal/Divine are
deterministic in *what kind* of thing happens but still draw random mods --
"deterministic" here means "always succeeds and always produces a new item",
as opposed to Annulment/Chaos/Exalted/Fracture whose very choice of *which*
existing mod is affected is itself random.
"""
from __future__ import annotations

import dataclasses
import random

from poe2craft.data.loader import GameData
from poe2craft.domain.actions import ActionKind, BoneFamily, BoneTier, CurrencyTier
from poe2craft.domain.essences import EssenceDef
from poe2craft.domain.ids import BaseId
from poe2craft.domain.items import Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory
from poe2craft.engine.pool import build_combined_pool, build_desecrated_pool, build_pool, has_room, item_tags
from poe2craft.engine.sampler import roll_new_affix, roll_new_affix_any, roll_values, weighted_sample_without_replacement

FALLBACK_ESSENCE_COST = 0.09
"""Fallback Divine-Orb cost for an essence not in the live price snapshot (53
of 95 essences, as of 2026-08-18). Calibrated as the median of the 42
essences that *are* priced, not a guess."""

FALLBACK_OMEN_COST = 0.06
"""Fallback Divine-Orb cost for an omen this project models but that isn't in
the live price snapshot (12 of the 17 modeled omens, as of 2026-08-18 --
likely just less-traded than the top ~30 by volume, not untradeable).
Calibrated as the median of the 28 omens that *are* priced, not a guess."""

DEFAULT_COSTS: dict[ActionKind, float] = {
    # Divine-Orb-equivalent fallback costs, used only when `GameData.prices`
    # (poe2db.tw's live economy page, see poe2db_parse.parse_economy_divine)
    # has no entry for that exact name -- as of the 2026-08-18 snapshot this
    # is just Fracturing Orb among base currencies (everything else priced
    # below is a real, live quote, not a guess). Calibrated roughly in line
    # with the real prices actually observed for neighboring currencies, not
    # arbitrary round numbers.
    ActionKind.TRANSMUTATION: 0.0006,
    ActionKind.AUGMENTATION: 0.0006,
    ActionKind.ALCHEMY: 0.002,
    ActionKind.REGAL: 0.0015,
    ActionKind.DIVINE: 1.0,
    ActionKind.ANNULMENT: 0.45,
    ActionKind.CHAOS: 0.1,
    ActionKind.EXALTED: 0.003,
    ActionKind.FRACTURE: 0.05,
    ActionKind.ESSENCE: FALLBACK_ESSENCE_COST,
    ActionKind.PERFECT_ESSENCE: FALLBACK_ESSENCE_COST,
    # Real per-bone prices (confirmed via poe2db.tw's economy page for
    # Jawbone/Collarbone at least, 2026-08-19) span a wide range by tier --
    # this only ever applies to whichever specific bone name isn't in the
    # live snapshot (e.g. Rib/Cranium, not yet confirmed priced there), so
    # it's calibrated to the Preserved tier (the "no restriction" baseline)
    # rather than trying to average across Gnawed/Ancient's very different
    # price points.
    ActionKind.DESECRATION: 0.1,
}

MIN_ILVL_BY_TIER: dict[ActionKind, dict[CurrencyTier, int]] = {
    ActionKind.TRANSMUTATION: {CurrencyTier.BASE: 0, CurrencyTier.GREATER: 44, CurrencyTier.PERFECT: 70},
    ActionKind.AUGMENTATION: {CurrencyTier.BASE: 0, CurrencyTier.GREATER: 44, CurrencyTier.PERFECT: 70},
    ActionKind.REGAL: {CurrencyTier.BASE: 0, CurrencyTier.GREATER: 35, CurrencyTier.PERFECT: 50},
    ActionKind.CHAOS: {CurrencyTier.BASE: 0, CurrencyTier.GREATER: 35, CurrencyTier.PERFECT: 50},
    ActionKind.EXALTED: {CurrencyTier.BASE: 0, CurrencyTier.GREATER: 35, CurrencyTier.PERFECT: 50},
}
"""Minimum modifier level a tiered currency's roll is restricted to -- confirmed
against poe2db.tw's "Minimum Modifier Level" field for each item, 2026-08-18
(quoted directly, not inferred): Transmutation/Augmentation share 0/44/70
(Normal->Magic->Rare items are lower level), Regal/Chaos/Exalted share 0/35/50
(they act on higher-level Magic/Rare items). Base tier has no floor."""

TIER_COST_MULTIPLIER: dict[CurrencyTier, float] = {CurrencyTier.BASE: 1.0, CurrencyTier.GREATER: 3.0, CurrencyTier.PERFECT: 15.0}
"""Fallback relative price multiplier per tier, used only in `_tiered_price`'s
last-resort branch (a base-currency name has a real price but neither its
Greater nor Perfect variant does -- doesn't happen for any currency this
project models as of 2026-08-18, but kept as a safety net)."""

_TIER_NAME_PREFIX: dict[CurrencyTier, str] = {CurrencyTier.BASE: "", CurrencyTier.GREATER: "Greater ", CurrencyTier.PERFECT: "Perfect "}


def _price(gamedata: GameData, name: str, fallback: float) -> float:
    """Divine-Orb cost of one use of `name`, from the live poe2db.tw economy
    snapshot if traded there, else `fallback`."""
    return gamedata.prices.get(name, fallback)


def _tiered_price(gamedata: GameData, base_currency_name: str, tier: CurrencyTier, kind: ActionKind) -> float:
    """Like `_price`, but for a name that varies by CurrencyTier (e.g. "Chaos
    Orb" / "Greater Chaos Orb" / "Perfect Chaos Orb"). Falls back through
    progressively rougher estimates: a cheaper tier's own *real* price (Perfect
    is never cheaper than Greater, which is never cheaper than Base) before
    reaching for the flat placeholder multiplier, since real neighboring data
    is a better guess than an arbitrary constant. As of 2026-08-18 this only
    ever bottoms out for Perfect Chaos Orb and Perfect Exalted Orb, both of
    which do have a real Greater-tier price to fall back to."""
    name = f"{_TIER_NAME_PREFIX[tier]}{base_currency_name}"
    price = gamedata.prices.get(name)
    if price is not None:
        return price
    if tier is CurrencyTier.PERFECT:
        greater_price = gamedata.prices.get(f"Greater {base_currency_name}")
        if greater_price is not None:
            return greater_price
    if tier is not CurrencyTier.BASE:
        base_price = gamedata.prices.get(base_currency_name)
        if base_price is not None:
            return base_price * TIER_COST_MULTIPLIER[tier]
    return DEFAULT_COSTS[kind] * TIER_COST_MULTIPLIER[tier]


def _with_omen(base_name: str, omen_name: str | None) -> str:
    """Appends an omen-wrapped action's real in-game omen name (e.g. "Omen of
    Sinistral Alchemy") to its base currency name for display -- the same
    name each class's own `cost()` already prices under, not a separately
    invented shorthand, so what's shown is exactly what a player needs to buy
    and use."""
    return base_name if omen_name is None else f"{base_name} ({omen_name})"


def _add_affix(item: Item, new_affix) -> Item:
    if new_affix.affix is Affix.PREFIX:
        return dataclasses.replace(item, prefixes=item.prefixes + (new_affix,))
    return dataclasses.replace(item, suffixes=item.suffixes + (new_affix,))


def _remove_affix(item: Item, removed) -> Item:
    if removed.affix is Affix.PREFIX:
        return dataclasses.replace(item, prefixes=tuple(a for a in item.prefixes if a is not removed))
    return dataclasses.replace(item, suffixes=tuple(a for a in item.suffixes if a is not removed))


def _rolled(gamedata: GameData, mod_id, tier, rng: random.Random) -> RolledAffix:
    mod = gamedata.mods[mod_id]
    return RolledAffix(
        mod_id=mod.id,
        affix=mod.affix,
        group_keys=mod.group_keys,
        value_ranges=tier.value_ranges,
        values=roll_values(tier.value_ranges, rng),
        ilvl=tier.ilvl,
    )


class TransmutationAction:
    kind = ActionKind.TRANSMUTATION

    def __init__(self, gamedata: GameData, tier: CurrencyTier = CurrencyTier.BASE):
        self._gd = gamedata
        self.tier = tier
        self.min_ilvl = MIN_ILVL_BY_TIER[self.kind][tier]
        self.name = f"{_TIER_NAME_PREFIX[tier]}Orb of Transmutation"

    def applicable(self, item: Item) -> bool:
        if item.rarity is not Rarity.NORMAL:
            return False
        # The eligibility/room check must run as-if-already-Magic, since that's
        # the rarity the affix actually gets added under -- checking it while
        # still Normal would always report "no room" (has_room treats Normal
        # as having none).
        post = dataclasses.replace(item, rarity=Rarity.MAGIC)
        return bool(build_combined_pool(self._gd, post, min_ilvl=self.min_ilvl))

    def cost(self) -> float:
        return _tiered_price(self._gd, "Orb of Transmutation", self.tier, self.kind)

    def outcome(self, item: Item, rng: random.Random) -> Item:
        item = dataclasses.replace(item, rarity=Rarity.MAGIC)
        return _add_affix(item, roll_new_affix_any(self._gd, item, rng, min_ilvl=self.min_ilvl))


class AugmentationAction:
    kind = ActionKind.AUGMENTATION

    def __init__(self, gamedata: GameData, tier: CurrencyTier = CurrencyTier.BASE):
        self._gd = gamedata
        self.tier = tier
        self.min_ilvl = MIN_ILVL_BY_TIER[self.kind][tier]
        self.name = f"{_TIER_NAME_PREFIX[tier]}Orb of Augmentation"

    def applicable(self, item: Item) -> bool:
        return item.rarity is Rarity.MAGIC and bool(build_combined_pool(self._gd, item, min_ilvl=self.min_ilvl))

    def cost(self) -> float:
        return _tiered_price(self._gd, "Orb of Augmentation", self.tier, self.kind)

    def outcome(self, item: Item, rng: random.Random) -> Item:
        return _add_affix(item, roll_new_affix_any(self._gd, item, rng, min_ilvl=self.min_ilvl))


class AlchemyAction:
    kind = ActionKind.ALCHEMY

    def __init__(self, gamedata: GameData, priority: Affix | None = None):
        self._gd = gamedata
        # Omen of Sinistral/Dextral Alchemy: the next Alchemy maxes out that
        # affix side first, then fills the remaining slots (still 4 total)
        # from whatever's left -- not a separate roll pool, just an ordering.
        self.priority = priority
        self.name = _with_omen("Orb of Alchemy", self._omen_name())

    def _omen_name(self) -> str | None:
        if self.priority is Affix.PREFIX:
            return "Omen of Sinistral Alchemy"
        if self.priority is Affix.SUFFIX:
            return "Omen of Dextral Alchemy"
        return None

    def applicable(self, item: Item) -> bool:
        return item.rarity is Rarity.NORMAL

    def cost(self) -> float:
        base = _price(self._gd, "Orb of Alchemy", DEFAULT_COSTS[self.kind])
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def outcome(self, item: Item, rng: random.Random) -> Item:
        item = dataclasses.replace(item, rarity=Rarity.RARE)
        remaining = 4
        if self.priority is not None:
            while remaining > 0 and has_room(self._gd, item, self.priority):
                pool = build_pool(self._gd, item, self.priority)
                if not pool:
                    break
                item = _add_affix(item, roll_new_affix(self._gd, item, self.priority, rng))
                remaining -= 1
        for _ in range(remaining):
            pool = build_combined_pool(self._gd, item)
            if not pool:
                break  # base's eligible pool dried up short of 4 -- a real, if rare, edge case
            item = _add_affix(item, roll_new_affix_any(self._gd, item, rng))
        return item


class RegalAction:
    kind = ActionKind.REGAL

    def __init__(
        self,
        gamedata: GameData,
        tier: CurrencyTier = CurrencyTier.BASE,
        restrict: Affix | None = None,
        homogenising: bool = False,
    ):
        self._gd = gamedata
        self.tier = tier
        self.restrict = restrict
        # Omen of Homogenising Coronation: restricts the add to mods sharing a
        # broad category tag with an existing modifier -- inapplicable if the
        # item's current mods (pre-transition, from its Magic state) have no
        # tags at all, since there's then no "existing modifier" type to match.
        self.homogenising = homogenising
        self.min_ilvl = MIN_ILVL_BY_TIER[self.kind][tier]
        self.name = _with_omen(f"{_TIER_NAME_PREFIX[tier]}Regal Orb", self._omen_name())

    def _omen_name(self) -> str | None:
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Coronation"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Coronation"
        if self.homogenising:
            return "Omen of Homogenising Coronation"
        return None

    def _required_tags(self, item: Item) -> frozenset[str] | None:
        return item_tags(self._gd, item) or None if self.homogenising else None

    def applicable(self, item: Item) -> bool:
        if item.rarity is not Rarity.MAGIC:
            return False
        if self.homogenising and not item_tags(self._gd, item):
            return False
        # Same as TransmutationAction: check room/eligibility as-if-already-Rare,
        # since Rare's (usually larger) caps are what apply when the affix is
        # actually added, not Magic's 1-prefix/1-suffix cap.
        post = dataclasses.replace(item, rarity=Rarity.RARE)
        required_tags = self._required_tags(item)
        if self.restrict is not None:
            return has_room(self._gd, post, self.restrict) and bool(
                build_pool(self._gd, post, self.restrict, min_ilvl=self.min_ilvl, required_tags=required_tags)
            )
        return bool(build_combined_pool(self._gd, post, min_ilvl=self.min_ilvl, required_tags=required_tags))

    def cost(self) -> float:
        base = _tiered_price(self._gd, "Regal Orb", self.tier, self.kind)
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def outcome(self, item: Item, rng: random.Random) -> Item:
        required_tags = self._required_tags(item)
        item = dataclasses.replace(item, rarity=Rarity.RARE)
        if self.restrict is not None:
            new_affix = roll_new_affix(self._gd, item, self.restrict, rng, min_ilvl=self.min_ilvl, required_tags=required_tags)
        else:
            new_affix = roll_new_affix_any(self._gd, item, rng, min_ilvl=self.min_ilvl, required_tags=required_tags)
        return _add_affix(item, new_affix)


class DivineAction:
    name = "Divine Orb"
    kind = ActionKind.DIVINE

    def __init__(self, gamedata: GameData):
        self._gd = gamedata

    def applicable(self, item: Item) -> bool:
        return item.rarity in (Rarity.MAGIC, Rarity.RARE) and bool(item.affixes)

    def cost(self) -> float:
        return _price(self._gd, "Divine Orb", DEFAULT_COSTS[self.kind])

    def outcome(self, item: Item, rng: random.Random) -> Item:
        # Rerolls each existing affix's numeric value within its own already-
        # assigned tier -- mod identity never changes. See docs/design_notes.md:
        # this is a near no-op for v1's presence-only abstraction. Fractured
        # mods are skipped -- confirmed a Divine Orb can't even re-randomise
        # a fractured mod's value, the roll you fractured is permanent.
        reroll = lambda a: a if a.fractured else dataclasses.replace(a, values=roll_values(a.value_ranges, rng))
        return dataclasses.replace(
            item,
            prefixes=tuple(reroll(a) for a in item.prefixes),
            suffixes=tuple(reroll(a) for a in item.suffixes),
        )


class AnnulmentAction:
    kind = ActionKind.ANNULMENT

    def __init__(
        self,
        gamedata: GameData,
        restrict: Affix | None = None,
        count: int = 1,
        restrict_category: ModCategory | None = None,
    ):
        self._gd = gamedata
        self.restrict = restrict
        self.count = count
        # Omen of Light: restricts removal to Desecrated modifiers only --
        # meaningless combined with restrict/count (the registry never
        # constructs it that way), a separate axis from the affix-type and
        # count omens.
        self.restrict_category = restrict_category
        # Omen of Greater Annulment: removes `count` (2) modifiers instead of
        # 1, falling back to however many candidates actually exist if fewer.
        self.name = _with_omen("Orb of Annulment", self._omen_name())

    def _omen_name(self) -> str | None:
        if self.count > 1:
            return "Omen of Greater Annulment"
        if self.restrict_category is ModCategory.DESECRATED:
            return "Omen of Light"
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Annulment"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Annulment"
        return None

    def _candidates(self, item: Item):
        return [
            a
            for a in item.affixes
            if not a.fractured
            and (self.restrict is None or a.affix is self.restrict)
            and (self.restrict_category is None or self._gd.mods[a.mod_id].category is self.restrict_category)
        ]

    def applicable(self, item: Item) -> bool:
        return item.rarity in (Rarity.MAGIC, Rarity.RARE) and bool(self._candidates(item))

    def cost(self) -> float:
        base = _price(self._gd, "Orb of Annulment", DEFAULT_COSTS[self.kind])
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def outcome(self, item: Item, rng: random.Random) -> Item:
        for _ in range(self.count):
            candidates = self._candidates(item)
            if not candidates:
                break
            removed = rng.choice(candidates)
            item = _remove_affix(item, removed)
        return item


class ChaosAction:
    kind = ActionKind.CHAOS

    def __init__(
        self,
        gamedata: GameData,
        tier: CurrencyTier = CurrencyTier.BASE,
        restrict: Affix | None = None,
        pick_lowest: bool = False,
    ):
        self._gd = gamedata
        self.tier = tier
        self.restrict = restrict
        # Omen of Whittling: removes the lowest-level modifier (deterministic)
        # instead of a uniformly random one.
        self.pick_lowest = pick_lowest
        self.min_ilvl = MIN_ILVL_BY_TIER[self.kind][tier]
        self.name = _with_omen(f"{_TIER_NAME_PREFIX[tier]}Chaos Orb", self._omen_name())

    def _omen_name(self) -> str | None:
        if self.pick_lowest:
            return "Omen of Whittling"
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Erasure"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Erasure"
        return None

    def _candidates(self, item: Item):
        return [a for a in item.affixes if not a.fractured and (self.restrict is None or a.affix is self.restrict)]

    def applicable(self, item: Item) -> bool:
        return item.rarity is Rarity.RARE and bool(self._candidates(item))

    def cost(self) -> float:
        base = _tiered_price(self._gd, "Chaos Orb", self.tier, self.kind)
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def _pick_removal(self, item: Item, rng: random.Random):
        candidates = self._candidates(item)
        if self.pick_lowest:
            lowest = min(a.ilvl for a in candidates)
            candidates = [a for a in candidates if a.ilvl == lowest]  # break ties randomly, not by insertion order
        return rng.choice(candidates)

    def outcome(self, item: Item, rng: random.Random) -> Item:
        removed = self._pick_removal(item, rng)
        item = _remove_affix(item, removed)
        # Open question (docs/design_notes.md): does the replacement preserve
        # the removed mod's affix type? We roll freely from the combined pool,
        # documented as an assumption rather than a confirmed mechanic.
        pool = build_combined_pool(self._gd, item, min_ilvl=self.min_ilvl)
        if not pool:
            return item
        return _add_affix(item, roll_new_affix_any(self._gd, item, rng, min_ilvl=self.min_ilvl))


class ExaltedAction:
    kind = ActionKind.EXALTED

    def __init__(
        self,
        gamedata: GameData,
        restrict: Affix | None = None,
        tier: CurrencyTier = CurrencyTier.BASE,
        count: int = 1,
        homogenising: bool = False,
    ):
        self._gd = gamedata
        self.restrict = restrict
        self.tier = tier
        # Omen of Greater Exaltation: adds `count` (2) modifiers instead of 1,
        # stopping early if the pool/room dries up before reaching count.
        self.count = count
        # Omen of Homogenising Exaltation: restricts the add to mods sharing a
        # broad category tag with an existing modifier -- inapplicable if the
        # item has no mods, or none of them have any tag at all.
        self.homogenising = homogenising
        self.min_ilvl = MIN_ILVL_BY_TIER[self.kind][tier]
        self.name = _with_omen(f"{_TIER_NAME_PREFIX[tier]}Exalted Orb", self._omen_name())

    def _omen_name(self) -> str | None:
        if self.count > 1:
            return "Omen of Greater Exaltation"
        if self.homogenising:
            return "Omen of Homogenising Exaltation"
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Exaltation"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Exaltation"
        return None

    def _required_tags(self, item: Item) -> frozenset[str] | None:
        return item_tags(self._gd, item) or None if self.homogenising else None

    def applicable(self, item: Item) -> bool:
        if item.rarity is not Rarity.RARE:
            return False
        if self.homogenising and not item_tags(self._gd, item):
            return False
        required_tags = self._required_tags(item)
        if self.restrict is not None:
            return has_room(self._gd, item, self.restrict) and bool(
                build_pool(self._gd, item, self.restrict, min_ilvl=self.min_ilvl, required_tags=required_tags)
            )
        return bool(build_combined_pool(self._gd, item, min_ilvl=self.min_ilvl, required_tags=required_tags))

    def cost(self) -> float:
        base = _tiered_price(self._gd, "Exalted Orb", self.tier, self.kind)
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def outcome(self, item: Item, rng: random.Random) -> Item:
        for _ in range(self.count):
            # Recomputed each pass (matters only for Greater Exaltation +
            # Homogenising combined, which the registry doesn't pre-construct
            # but the classes support): a mod added on the first pass could
            # itself introduce a new tag to match against on the second.
            required_tags = self._required_tags(item)
            if self.restrict is not None:
                if not has_room(self._gd, item, self.restrict) or not build_pool(
                    self._gd, item, self.restrict, min_ilvl=self.min_ilvl, required_tags=required_tags
                ):
                    break
                new_affix = roll_new_affix(
                    self._gd, item, self.restrict, rng, min_ilvl=self.min_ilvl, required_tags=required_tags
                )
            else:
                if not build_combined_pool(self._gd, item, min_ilvl=self.min_ilvl, required_tags=required_tags):
                    break
                new_affix = roll_new_affix_any(self._gd, item, rng, min_ilvl=self.min_ilvl, required_tags=required_tags)
            item = _add_affix(item, new_affix)
        return item


class FractureAction:
    name = "Fracturing Orb"
    kind = ActionKind.FRACTURE

    def __init__(self, gamedata: GameData):
        self._gd = gamedata

    def _candidates(self, item: Item):
        return [a for a in item.affixes if not a.fractured]

    def applicable(self, item: Item) -> bool:
        return (
            item.rarity is Rarity.RARE
            and not any(a.fractured for a in item.affixes)
            and bool(self._candidates(item))
        )

    def cost(self) -> float:
        return _price(self._gd, "Fracturing Orb", DEFAULT_COSTS[self.kind])

    def outcome(self, item: Item, rng: random.Random) -> Item:
        target = rng.choice(self._candidates(item))
        fractured = dataclasses.replace(target, fractured=True)

        def swap(a):
            return fractured if a is target else a

        return dataclasses.replace(
            item,
            prefixes=tuple(swap(a) for a in item.prefixes),
            suffixes=tuple(swap(a) for a in item.suffixes),
        )


class EssenceAction:
    """A single essence, bound to one specific base (its guaranteed mod(s) --
    usually one, occasionally 2-3 for hybrid essences -- are base-specific, see
    domain.essences). Non-Perfect tiers (Lesser/Normal/Greater, and the ~11
    uniquely-named essences with no tier variants) require a Magic item and
    guarantee their mod(s) while transitioning it to Rare, like a targeted
    Regal Orb. Perfect tiers require a Rare item, remove one existing random
    non-fractured mod, and guarantee an essence-exclusive mod in its place,
    like a targeted, guaranteed-hit Chaos Orb -- see docs/design_notes.md for
    what's still unconfirmed about exact edge-case behavior.
    """

    kind = ActionKind.ESSENCE

    def __init__(self, gamedata: GameData, essence: EssenceDef, base_id: BaseId, restrict: Affix | None = None):
        self._gd = gamedata
        self.essence = essence
        self.base_id = base_id
        # Omen of Sinistral/Dextral Crystallisation: restricts a Perfect
        # essence's removal step to one affix type. Meaningless for non-Perfect
        # essences (they don't remove anything) -- essence_actions_for only
        # ever constructs this for Perfect essences.
        self.restrict = restrict
        self.name = _with_omen(essence.name, self._omen_name())
        self.grants = essence.per_base.get(base_id, ())
        self.perfect = essence.is_perfect
        if self.perfect:
            self.kind = ActionKind.PERFECT_ESSENCE

    def _omen_name(self) -> str | None:
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Crystallisation"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Crystallisation"
        return None

    def _needed_group_keys(self) -> frozenset:
        keys: set = set()
        for g in self.grants:
            keys |= self._gd.mods[g.mod_id].group_keys
        return frozenset(keys)

    def _fits_after(self, item: Item) -> bool:
        """Would `item` (already missing whatever this essence needs to remove,
        if anything) have room and no group conflict for every grant?"""
        if self._needed_group_keys() & item.occupied_group_keys():
            return False
        needed_prefix = sum(1 for g in self.grants if self._gd.mods[g.mod_id].affix is Affix.PREFIX)
        needed_suffix = sum(1 for g in self.grants if self._gd.mods[g.mod_id].affix is Affix.SUFFIX)
        bg = self._gd.base_group_of(item.base_id)
        return item.prefix_count + needed_prefix <= bg.max_prefix and item.suffix_count + needed_suffix <= bg.max_suffix

    def _removal_candidates(self, item: Item) -> list:
        return [
            a
            for a in item.affixes
            if not a.fractured
            and (self.restrict is None or a.affix is self.restrict)
            and self._fits_after(_remove_affix(item, a))
        ]

    def applicable(self, item: Item) -> bool:
        if not self.grants or item.ilvl < max(g.ilvl for g in self.grants):
            return False
        if self.perfect:
            return item.rarity is Rarity.RARE and bool(self._removal_candidates(item))
        return item.rarity is Rarity.MAGIC and self._fits_after(item)

    def cost(self) -> float:
        base = _price(self._gd, self.essence.name, DEFAULT_COSTS[self.kind])
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def _add_all_grants(self, item: Item, rng: random.Random) -> Item:
        for g in self.grants:
            tier = self._gd.find_tier(self.base_id, g.mod_id, g.ilvl)
            item = _add_affix(item, _rolled(self._gd, g.mod_id, tier, rng))
        return item

    def outcome(self, item: Item, rng: random.Random) -> Item:
        if self.perfect:
            removed = rng.choice(self._removal_candidates(item))
            item = _remove_affix(item, removed)
        else:
            item = dataclasses.replace(item, rarity=Rarity.RARE)
        return self._add_all_grants(item, rng)


def essence_actions_for(gamedata: GameData, base_id: BaseId) -> dict[str, object]:
    """One EssenceAction per essence that has data for this base -- essences
    are base-restricted (e.g. an armour essence has no entry for weapon
    bases), so essences with nothing to grant here are skipped entirely. Perfect
    essences additionally get Sinistral/Dextral Crystallisation variants (the
    only omens that touch essences), since only Perfect essences have a
    removal step to restrict."""
    out = {}
    for essence in gamedata.essences:
        if base_id not in essence.per_base:
            continue
        out[f"essence_{essence.id}"] = EssenceAction(gamedata, essence, base_id)
        if essence.is_perfect:
            out[f"essence_{essence.id}_omen_dextral"] = EssenceAction(gamedata, essence, base_id, restrict=Affix.SUFFIX)
            out[f"essence_{essence.id}_omen_sinistral"] = EssenceAction(gamedata, essence, base_id, restrict=Affix.PREFIX)
    return out


_BONE_FAMILY_BGROUPS: dict[BoneFamily, frozenset[str]] = {
    BoneFamily.JAWBONE: frozenset({"One-Handed Weapons", "Two-Handed Weapons"}),
    BoneFamily.RIB: frozenset({"Body Armours", "Boots", "Gloves", "Helmets"}),
    BoneFamily.COLLARBONE: frozenset({"Jewellery"}),
    BoneFamily.CRANIUM: frozenset({"Jewels"}),
}
# Quiver/Shield/Focus all live in the "Offhands" bgroup in this project's data
# model, but real bones split by slot more finely than that. Quiver -> Jawbone
# (real Jawbones work on "a weapon or quiver") is directly confirmed by
# several current PoE2 guides. Shield/Focus -> Rib is NOT directly confirmed
# anywhere researched (no guide mentions off-hand items by name) -- it's an
# inference from the compiled gamedata itself: every Offhands-bgroup base
# (Focus, Shield x4, and Quiver) has real Desecrated tier data, and Quiver's
# is already explained by Jawbone, so Shield/Focus having it too only makes
# sense if some bone can reach them -- Rib ("armour") is the closest fit,
# since Shields/Focus are conventionally "defensive gear" like Body
# Armour/Helmet/Gloves/Boots even though this project's own bgroup taxonomy
# keeps them separate. Flagged in docs/design_notes.md as an inference, not a
# confirmed mechanic -- revisit if a source specifically documents it.
_JAWBONE_EXTRA_BASE_NAMES = frozenset({"Quiver"})
_RIB_EXTRA_BASE_NAMES = frozenset({"Focus"})
_RIB_EXTRA_BASE_NAME_PREFIXES = ("Shield",)

_BONE_FAMILY_NAME: dict[BoneFamily, str] = {
    BoneFamily.JAWBONE: "Jawbone",
    BoneFamily.RIB: "Rib",
    BoneFamily.COLLARBONE: "Collarbone",
    BoneFamily.CRANIUM: "Cranium",
}
_BONE_TIER_NAME_PREFIX: dict[BoneTier, str] = {BoneTier.GNAWED: "Gnawed", BoneTier.PRESERVED: "Preserved", BoneTier.ANCIENT: "Ancient"}
_BONE_MAX_ITEM_ILVL: dict[BoneTier, int] = {BoneTier.GNAWED: 64}
"""Gnawed bones can only desecrate an item at or below this ilvl -- confirmed
against several current PoE2 guides (poe2db.tw doesn't document Desecration
at all, 2026-08-19). Preserved/Ancient have no such cap (absent from this
dict, so `DesecrationAction` treats them as unrestricted)."""
_BONE_MIN_MOD_ILVL: dict[BoneTier, int] = {BoneTier.ANCIENT: 40}
"""Ancient bones guarantee the revealed mod's own tier requires at least this
ilvl -- the same `min_ilvl` shape as Greater/Perfect currency tiers
(`MIN_ILVL_BY_TIER`), just for bones. Gnawed/Preserved have no such floor."""


def _bone_family_matches(gamedata: GameData, base_id: BaseId, family: BoneFamily) -> bool:
    base_name = gamedata.bases[base_id].name
    if family is BoneFamily.JAWBONE and base_name in _JAWBONE_EXTRA_BASE_NAMES:
        return True
    if family is BoneFamily.RIB and (base_name in _RIB_EXTRA_BASE_NAMES or base_name.startswith(_RIB_EXTRA_BASE_NAME_PREFIXES)):
        return True
    return gamedata.base_group_of(base_id).name in _BONE_FAMILY_BGROUPS[family]


class DesecrationAction:
    """A Desecration bone: reveals 3 random Desecrated-category modifiers
    (6 with Omen of Abyssal Echoes, which lets you reroll the presented
    options once) and the player picks whichever one to actually apply --
    the first action in this project where the outcome depends on a choice
    among several random candidates rather than a single random draw. See
    `solver.model_learning.estimate_transition`'s `reveal_candidates` branch
    for how that choice is modeled (pick whichever candidate helps the
    target most, matching a rational player).

    If the item already has the maximum number of affixes, applying a bone
    removes one random non-fractured affix first to make room -- confirmed
    against several current PoE2 guides, same source as the rest of this
    mechanic (poe2db.tw doesn't document Desecration at all, 2026-08-19)."""

    kind = ActionKind.DESECRATION

    def __init__(
        self,
        gamedata: GameData,
        family: BoneFamily,
        tier: BoneTier,
        restrict: Affix | None = None,
        echoes: bool = False,
    ):
        self._gd = gamedata
        self.family = family
        self.tier = tier
        self.restrict = restrict
        self.echoes = echoes
        self.min_ilvl = _BONE_MIN_MOD_ILVL.get(tier, 0)
        self.max_item_ilvl = _BONE_MAX_ITEM_ILVL.get(tier)
        self._base_name = f"{_BONE_TIER_NAME_PREFIX[tier]} {_BONE_FAMILY_NAME[family]}"
        self.name = _with_omen(self._base_name, self._omen_name())

    def _omen_name(self) -> str | None:
        if self.restrict is Affix.PREFIX:
            return "Omen of Sinistral Necromancy"
        if self.restrict is Affix.SUFFIX:
            return "Omen of Dextral Necromancy"
        if self.echoes:
            return "Omen of Abyssal Echoes"
        return None

    def cost(self) -> float:
        base = _price(self._gd, self._base_name, DEFAULT_COSTS[self.kind])
        omen = self._omen_name()
        return base + _price(self._gd, omen, FALLBACK_OMEN_COST) if omen else base

    def _is_full(self, item: Item) -> bool:
        bg = self._gd.base_group_of(item.base_id)
        return item.prefix_count + item.suffix_count >= bg.max_prefix + bg.max_suffix

    def applicable(self, item: Item) -> bool:
        if item.rarity is not Rarity.RARE:
            return False
        if not _bone_family_matches(self._gd, item.base_id, self.family):
            return False
        if self.max_item_ilvl is not None and item.ilvl > self.max_item_ilvl:
            return False
        if self._is_full(item):
            # Room will be made in reveal_candidates; whether that specific
            # removal happens to open up a non-empty pool can't be known
            # without knowing which affix gets removed, so this only checks
            # that *something* removable exists -- reveal_candidates itself
            # degrades to a safe no-op if the post-removal pool is still
            # empty, the same "pool dried up" precedent AlchemyAction uses.
            return any(not a.fractured for a in item.affixes)
        return bool(build_desecrated_pool(self._gd, item, self.restrict, min_ilvl=self.min_ilvl))

    def _make_room(self, item: Item, rng: random.Random) -> Item:
        if not self._is_full(item):
            return item
        candidates = [a for a in item.affixes if not a.fractured]
        if not candidates:
            return item
        return _remove_affix(item, rng.choice(candidates))

    def reveal_candidates(self, item: Item, rng: random.Random) -> list[Item]:
        item = self._make_room(item, rng)
        pool = build_desecrated_pool(self._gd, item, self.restrict, min_ilvl=self.min_ilvl)
        if not pool:
            return [item]  # nothing eligible even after making room -- rare, but a real no-op rather than a crash
        picks = weighted_sample_without_replacement(pool, 6 if self.echoes else 3, rng)
        return [_add_affix(item, _rolled(self._gd, mod.id, tier, rng)) for mod, tier in picks]


def desecration_actions_for(gamedata: GameData, base_id: BaseId) -> dict[str, object]:
    """One DesecrationAction per (family, tier) whose slot family matches
    this base, plus Sinistral/Dextral Necromancy and Abyssal Echoes wrapped
    onto the Preserved tier (this project's existing convention of wrapping
    omens onto one representative tier rather than cross-producing every
    omen with every tier -- see e.g. `omen_wrapped_actions`'s Regal/Exalted
    omens, all built at CurrencyTier.BASE only)."""
    out: dict[str, object] = {}
    for family in BoneFamily:
        if not _bone_family_matches(gamedata, base_id, family):
            continue
        for tier in BoneTier:
            out[f"desecration_{family.value}_{tier.value}"] = DesecrationAction(gamedata, family, tier)
        out[f"desecration_{family.value}_omen_sinistral"] = DesecrationAction(
            gamedata, family, BoneTier.PRESERVED, restrict=Affix.PREFIX
        )
        out[f"desecration_{family.value}_omen_dextral"] = DesecrationAction(
            gamedata, family, BoneTier.PRESERVED, restrict=Affix.SUFFIX
        )
        out[f"desecration_{family.value}_omen_echoes"] = DesecrationAction(gamedata, family, BoneTier.PRESERVED, echoes=True)
    return out


_TIER_KEY_SUFFIX: dict[CurrencyTier, str] = {CurrencyTier.BASE: "", CurrencyTier.GREATER: "_greater", CurrencyTier.PERFECT: "_perfect"}


def build_action_registry(gamedata: GameData) -> dict[str, object]:
    """Every base (non-omen-wrapped) action, keyed by a stable string id used in
    solver output and the CLI. Omen-wrapped variants are constructed by
    engine.omens.omen_wrapped_actions, not pre-registered here. Transmutation,
    Augmentation, Regal, Chaos, and Exalted each get all 3 currency tiers
    (base/Greater/Perfect, see MIN_ILVL_BY_TIER); the other actions have no
    tiered variant in PoE2 and stay single-instance."""
    registry: dict[str, object] = {
        "alchemy": AlchemyAction(gamedata),
        "divine": DivineAction(gamedata),
        "annulment": AnnulmentAction(gamedata),
        "fracture": FractureAction(gamedata),
    }
    for tier in CurrencyTier:
        suffix = _TIER_KEY_SUFFIX[tier]
        registry[f"transmutation{suffix}"] = TransmutationAction(gamedata, tier=tier)
        registry[f"augmentation{suffix}"] = AugmentationAction(gamedata, tier=tier)
        registry[f"regal{suffix}"] = RegalAction(gamedata, tier=tier)
        registry[f"chaos{suffix}"] = ChaosAction(gamedata, tier=tier)
        registry[f"exalted{suffix}"] = ExaltedAction(gamedata, tier=tier)
    return registry
