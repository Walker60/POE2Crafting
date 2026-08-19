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
from poe2craft.domain.actions import ActionKind, CurrencyTier
from poe2craft.domain.essences import EssenceDef
from poe2craft.domain.ids import BaseId
from poe2craft.domain.items import Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix
from poe2craft.engine.pool import build_combined_pool, build_pool, has_room, item_tags
from poe2craft.engine.sampler import roll_new_affix, roll_new_affix_any, roll_values

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


def _omen_suffix(count: int = 1, restrict: Affix | None = None, extra: str | None = None, count_verb: str = "") -> str:
    """Builds the "(Omen: ...)" name suffix for an omen-wrapped action from
    whichever of its modifiers are active, so a combination of modifiers
    (should one ever be constructed) renders sensibly instead of needing a
    separate hardcoded string per combination."""
    parts = []
    if count > 1:
        parts.append(f"{count_verb} {count}".strip())
    if extra:
        parts.append(extra)
    if restrict is not None:
        parts.append(f"{restrict.value}es only")
    return f" (Omen: {', '.join(parts)})" if parts else ""


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
        self.name = "Orb of Alchemy" if priority is None else f"Orb of Alchemy (Omen: max {priority.value}es)"

    def applicable(self, item: Item) -> bool:
        return item.rarity is Rarity.NORMAL

    def cost(self) -> float:
        base = _price(self._gd, "Orb of Alchemy", DEFAULT_COSTS[self.kind])
        if self.priority is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Alchemy", FALLBACK_OMEN_COST)
        if self.priority is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Alchemy", FALLBACK_OMEN_COST)
        return base

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
        name = f"{_TIER_NAME_PREFIX[tier]}Regal Orb"
        extra = "same type as existing" if homogenising else None
        self.name = f"{name}{_omen_suffix(restrict=restrict, extra=extra)}"

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
        if self.restrict is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Coronation", FALLBACK_OMEN_COST)
        if self.restrict is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Coronation", FALLBACK_OMEN_COST)
        if self.homogenising:
            return base + _price(self._gd, "Omen of Homogenising Coronation", FALLBACK_OMEN_COST)
        return base

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
        # this is a near no-op for v1's presence-only abstraction.
        reroll = lambda a: dataclasses.replace(a, values=roll_values(a.value_ranges, rng))
        return dataclasses.replace(
            item,
            prefixes=tuple(reroll(a) for a in item.prefixes),
            suffixes=tuple(reroll(a) for a in item.suffixes),
        )


class AnnulmentAction:
    kind = ActionKind.ANNULMENT

    def __init__(self, gamedata: GameData, restrict: Affix | None = None, count: int = 1):
        self._gd = gamedata
        self.restrict = restrict
        self.count = count
        # Omen of Greater Annulment: removes `count` (2) modifiers instead of
        # 1, falling back to however many candidates actually exist if fewer.
        self.name = f"Orb of Annulment{_omen_suffix(count=count, restrict=restrict, count_verb='removes')}"

    def _candidates(self, item: Item):
        return [a for a in item.affixes if not a.fractured and (self.restrict is None or a.affix is self.restrict)]

    def applicable(self, item: Item) -> bool:
        return item.rarity in (Rarity.MAGIC, Rarity.RARE) and bool(self._candidates(item))

    def cost(self) -> float:
        base = _price(self._gd, "Orb of Annulment", DEFAULT_COSTS[self.kind])
        if self.count > 1:
            return base + _price(self._gd, "Omen of Greater Annulment", FALLBACK_OMEN_COST)
        if self.restrict is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Annulment", FALLBACK_OMEN_COST)
        if self.restrict is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Annulment", FALLBACK_OMEN_COST)
        return base

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
        extra = "lowest level" if pick_lowest else None
        self.name = f"{_TIER_NAME_PREFIX[tier]}Chaos Orb{_omen_suffix(restrict=restrict, extra=extra)}"

    def _candidates(self, item: Item):
        return [a for a in item.affixes if not a.fractured and (self.restrict is None or a.affix is self.restrict)]

    def applicable(self, item: Item) -> bool:
        return item.rarity is Rarity.RARE and bool(self._candidates(item))

    def cost(self) -> float:
        base = _tiered_price(self._gd, "Chaos Orb", self.tier, self.kind)
        if self.pick_lowest:
            return base + _price(self._gd, "Omen of Whittling", FALLBACK_OMEN_COST)
        if self.restrict is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Erasure", FALLBACK_OMEN_COST)
        if self.restrict is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Erasure", FALLBACK_OMEN_COST)
        return base

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
        name = f"{_TIER_NAME_PREFIX[tier]}Exalted Orb"
        extra = "same type as existing" if homogenising else None
        self.name = f"{name}{_omen_suffix(count=count, restrict=restrict, extra=extra, count_verb='adds')}"

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
        if self.count > 1:
            return base + _price(self._gd, "Omen of Greater Exaltation", FALLBACK_OMEN_COST)
        if self.homogenising:
            return base + _price(self._gd, "Omen of Homogenising Exaltation", FALLBACK_OMEN_COST)
        if self.restrict is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Exaltation", FALLBACK_OMEN_COST)
        if self.restrict is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Exaltation", FALLBACK_OMEN_COST)
        return base

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
        self.name = essence.name if restrict is None else f"{essence.name}{_omen_suffix(restrict=restrict)}"
        self.grants = essence.per_base.get(base_id, ())
        self.perfect = essence.is_perfect
        if self.perfect:
            self.kind = ActionKind.PERFECT_ESSENCE

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
        if self.restrict is Affix.PREFIX:
            return base + _price(self._gd, "Omen of Sinistral Crystallisation", FALLBACK_OMEN_COST)
        if self.restrict is Affix.SUFFIX:
            return base + _price(self._gd, "Omen of Dextral Crystallisation", FALLBACK_OMEN_COST)
        return base

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
