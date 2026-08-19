"""Target-relative state featurization -- the trick that keeps the solver's
state space small regardless of the game's overall mod pool (see
docs/design_notes.md "Solver scaling ceiling"). A state is
`(rarity, prefix_count, suffix_count, status-tuple)`, one status code per
target mod -- e.g. `[Rare|2,0,1|3|2]`. Each status is one of:

  0 ABSENT      -- the mod isn't on the item at all
  1 BELOW_TIER  -- present, but rolled at a tier weaker than the mod's
                   requested minimum ilvl
  2 SATISFIED   -- present and (if a minimum ilvl was requested) at or
                   above it

A target mod with no minimum ilvl (`min_ilvl=0`, the common case) can only
ever be ABSENT or SATISFIED -- BELOW_TIER needs nothing more than "present at
all" to already qualify, so that status is simply never produced for it,
which is what keeps ordinary (non-tier) targets exactly as small as before
this was added.

The subtle, easy-to-get-silently-wrong part lives here: Monte Carlo sampling
needs concrete `Item`s, so `concretize()` must fill every slot the abstract
state doesn't pin down with *freshly re-randomized* filler mods on every call
-- reusing one fixed filler across trials would silently bias the estimated
P(s'|s,a), since two items in the same abstract state can have genuinely
different transition probabilities depending on which (invisible-to-the-
abstraction) groups their filler mods occupy.
"""
from __future__ import annotations

import dataclasses
import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetSpec
from poe2craft.domain.ids import BaseId, GroupKey, ModId
from poe2craft.domain.items import Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory
from poe2craft.engine.pool import MAGIC_MAX_PER_AFFIX, build_pool
from poe2craft.engine.sampler import roll_values, weighted_pick


class TargetResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TargetModRequirement:
    mod_id: ModId
    min_ilvl: int = 0  # 0 = any tier satisfies -- no minimum requested


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    base_id: BaseId
    ilvl: int
    target_mods: tuple[TargetModRequirement, ...]  # order defines status-tuple position
    objective: str
    max_steps: int


def resolve_target(gamedata: GameData, spec: TargetSpec) -> ResolvedTarget:
    matches = [b for b in gamedata.bases.values() if b.name == spec.base]
    if not matches:
        raise TargetResolutionError(f"unknown base {spec.base!r}")
    base = matches[0]
    rollable = gamedata.eligible_mods_for_base(base.id)
    all_tiers = gamedata.all_tiers_by_base.get(base.id, {})
    # A target mod is reachable by normal weighted rolling (rollable, above),
    # by some essence guaranteeing it for this base, or -- Desecration bones
    # -- by it being a Desecrated-category mod with tier data for this base
    # (any base a bone's slot family matches can reveal it; a mod only
    # obtainable one of these ways must still be a valid target).
    essence_grantable = {g.mod_id for e in gamedata.essences for g in e.per_base.get(base.id, ())}
    desecrated_reachable = {mid for mid, tiers in all_tiers.items() if tiers and gamedata.mods[mid].category is ModCategory.DESECRATED}

    requirements: list[TargetModRequirement] = []
    seen: set[ModId] = set()
    for tm in spec.target_mods:
        mid = ModId(tm.mod_id)
        if mid not in gamedata.mods:
            raise TargetResolutionError(f"unknown mod id {tm.mod_id!r}")
        if mid not in rollable and mid not in essence_grantable and mid not in desecrated_reachable:
            raise TargetResolutionError(
                f"mod {tm.mod_id!r} ({gamedata.mods[mid].name!r}) is not reachable (rollable, essence-grantable, "
                f"or Desecrated) on base {spec.base!r}"
            )
        if mid in seen:
            raise TargetResolutionError("target_mods contains duplicates")
        seen.add(mid)
        if tm.min_ilvl:
            eligible_tiers = [t for t in all_tiers.get(mid, []) if t.ilvl <= spec.ilvl]
            if not any(t.ilvl >= tm.min_ilvl for t in eligible_tiers):
                raise TargetResolutionError(
                    f"mod {tm.mod_id!r} ({gamedata.mods[mid].name!r}) has no tier reaching "
                    f"min_ilvl={tm.min_ilvl} on an ilvl-{spec.ilvl} {spec.base!r} -- an unreachable target"
                )
        requirements.append(TargetModRequirement(mod_id=mid, min_ilvl=tm.min_ilvl))

    return ResolvedTarget(
        base_id=base.id,
        ilvl=spec.ilvl,
        target_mods=tuple(requirements),
        objective=spec.objective,
        max_steps=spec.max_steps,
    )


class ModStatus(IntEnum):
    ABSENT = 0
    BELOW_TIER = 1
    SATISFIED = 2


@dataclass(frozen=True, slots=True)
class AbstractState:
    rarity: Rarity
    prefix_count: int
    suffix_count: int
    status: tuple[int, ...]

    def is_goal(self) -> bool:
        return all(s == ModStatus.SATISFIED for s in self.status)


def start_state(
    gamedata: GameData, target: ResolvedTarget, start_rarity: Rarity, start_mod_ids: frozenset[ModId]
) -> AbstractState:
    """v1 only supports starting from an empty item or one already carrying a
    subset of the target mods (the CLI's supported inputs) -- prefix/suffix
    counts are derived purely from which target mods are already present. A
    declared starting mod is always treated as SATISFIED, even for a
    tier-targeted requirement: `start_mod_ids` has no way to say what tier
    it's actually at, so declaring it present is taken as asserting it's
    already good enough."""
    status = tuple(
        ModStatus.SATISFIED if req.mod_id in start_mod_ids else ModStatus.ABSENT for req in target.target_mods
    )
    n_prefix = sum(
        1
        for req, s in zip(target.target_mods, status)
        if s == ModStatus.SATISFIED and gamedata.mods[req.mod_id].affix is Affix.PREFIX
    )
    n_suffix = sum(
        1
        for req, s in zip(target.target_mods, status)
        if s == ModStatus.SATISFIED and gamedata.mods[req.mod_id].affix is Affix.SUFFIX
    )
    return AbstractState(rarity=start_rarity, prefix_count=n_prefix, suffix_count=n_suffix, status=status)


def abstractify(target: ResolvedTarget, item: Item) -> AbstractState:
    by_mod_id = {a.mod_id: a for a in item.affixes}
    status = []
    for req in target.target_mods:
        affix = by_mod_id.get(req.mod_id)
        if affix is None:
            status.append(ModStatus.ABSENT)
        elif affix.ilvl >= req.min_ilvl:
            status.append(ModStatus.SATISFIED)
        else:
            status.append(ModStatus.BELOW_TIER)
    return AbstractState(
        rarity=item.rarity, prefix_count=item.prefix_count, suffix_count=item.suffix_count, status=tuple(status)
    )


def pick_best_candidate(target: ResolvedTarget, state: AbstractState, candidates: list[Item], rng: random.Random) -> Item:
    """Models a rational player choosing among several revealed options --
    Desecration's "reveal 3 (or 6, with Omen of Abyssal Echoes), pick 1" is
    the first action in this codebase where the outcome is a *choice* rather
    than a single random draw (see `engine.apply.DesecrationAction`). Used by
    both `solver.model_learning.estimate_transition` (learning the abstract
    transition model) and `solver.playback.run_trajectory` (replaying a
    solved policy against the real sampler) -- any action exposing
    `reveal_candidates` needs the same "pick whichever helps most" logic in
    both places, or the two would disagree about what the policy actually
    does.

    Whichever candidate improves the most currently-unsatisfied target-mod
    statuses wins; ties (including "none of them help at all") are broken
    uniformly at random via `rng`, since the abstraction can't distinguish
    between equally-irrelevant filler picks -- exactly how every other action
    already treats an uncontrolled filler."""
    scored = [
        (sum(1 for new, old in zip(abstractify(target, c).status, state.status) if new > old), c) for c in candidates
    ]
    best_score = max(score for score, _ in scored)
    best = [c for score, c in scored if score == best_score]
    return rng.choice(best)


class ItemReportError(ValueError):
    """Raised when a user's description of their real item's current state
    (`item_from_report`) can't be turned into a valid `Item` -- e.g. it
    violates group exclusion or a rarity's affix cap. This is the first place
    in the codebase building an `Item` from arbitrary external input rather
    than the engine's own controlled sampling/removal logic, so nothing
    upstream already guarantees these invariants hold -- surfaced loudly
    rather than silently constructing a physically impossible item."""


def item_from_report(
    gamedata: GameData,
    base_id: BaseId,
    ilvl: int,
    rarity: Rarity,
    mod_reports: Sequence[tuple[ModId, int]],
) -> Item:
    """Builds a real `Item` directly from a user's description of their
    actual item -- each entry in `mod_reports` is (mod_id, the exact ilvl of
    the tier they say is currently rolled). Unlike `concretize`, nothing here
    is randomized or inferred: the caller is asserting ground truth, so
    `abstractify(target, item_from_report(...))` is how a web GUI turns
    "here's what my item looks like right now" into the solver's state.

    Looked up via `gamedata.find_tier` (the all-categories lookup, same as
    `concretize` uses for target mods), so an essence-exclusive or
    Desecrated current mod can be described too, not just normally-rollable
    ones -- a real item can carry either."""
    if rarity is Rarity.NORMAL and mod_reports:
        raise ItemReportError("a Normal item can't have any modifiers")

    seen: set[ModId] = set()
    prefixes: list[RolledAffix] = []
    suffixes: list[RolledAffix] = []
    occupied: set[GroupKey] = set()
    for mod_id, tier_ilvl in mod_reports:
        if mod_id in seen:
            raise ItemReportError(f"duplicate mod id {mod_id!r} in reported current mods")
        seen.add(mod_id)
        mod = gamedata.mods.get(mod_id)
        if mod is None:
            raise ItemReportError(f"unknown mod id {mod_id!r}")
        if mod.affix not in (Affix.PREFIX, Affix.SUFFIX):
            raise ItemReportError(
                f"mod {mod.name!r} is a {mod.affix.value} modifier, not a prefix or suffix -- "
                "not something this tool tracks as part of an item's affix list"
            )
        try:
            tier = gamedata.find_tier(base_id, mod_id, tier_ilvl)
        except KeyError:
            raise ItemReportError(f"mod {mod.name!r} has no tier at ilvl {tier_ilvl} on base {base_id}") from None
        if tier.ilvl > ilvl:
            # find_tier matches by exact tier ilvl regardless of the item's own
            # ilvl -- physically impossible for a real item (a tier requiring
            # a higher ilvl than the item itself can never have rolled), so
            # this needs its own check rather than relying on find_tier alone.
            raise ItemReportError(
                f"mod {mod.name!r}'s tier requires ilvl {tier.ilvl}, but the item is only ilvl {ilvl}"
            )
        if mod.group_keys & occupied:
            raise ItemReportError(
                f"mod {mod.name!r} shares an exclusion group with another reported mod -- these can't coexist on one item"
            )
        occupied |= mod.group_keys

        values = tuple((lo + hi) / 2 for lo, hi in tier.value_ranges)  # placeholder -- abstractify only reads mod_id/ilvl
        affix = RolledAffix(
            mod_id=mod_id,
            affix=mod.affix,
            group_keys=mod.group_keys,
            value_ranges=tier.value_ranges,
            values=values,
            ilvl=tier.ilvl,
        )
        (prefixes if mod.affix is Affix.PREFIX else suffixes).append(affix)

    if rarity is Rarity.MAGIC:
        max_prefix = max_suffix = MAGIC_MAX_PER_AFFIX
    else:  # RARE -- NORMAL was already rejected above whenever mod_reports is non-empty
        bg = gamedata.base_group_of(base_id)
        max_prefix, max_suffix = bg.max_prefix, bg.max_suffix
    if len(prefixes) > max_prefix:
        raise ItemReportError(f"{len(prefixes)} prefixes reported, but {rarity.value} allows at most {max_prefix}")
    if len(suffixes) > max_suffix:
        raise ItemReportError(f"{len(suffixes)} suffixes reported, but {rarity.value} allows at most {max_suffix}")

    return Item(base_id=base_id, ilvl=ilvl, rarity=rarity, prefixes=tuple(prefixes), suffixes=tuple(suffixes))


class ConcretizeError(RuntimeError):
    """Raised when a state can't be concretized -- e.g. the base's eligible pool
    is too small to fill the requested filler-mod count without collisions, or
    the state's counts are inconsistent with its own present target mods.
    Surfaced loudly rather than silently under-filling, since an under-filled
    concretization would corrupt the estimated transition model (see module
    docstring)."""


def _roll_specific(mod_id: ModId, mod_affix: Affix, group_keys: frozenset, tier, rng: random.Random) -> RolledAffix:
    return RolledAffix(
        mod_id=mod_id,
        affix=mod_affix,
        group_keys=group_keys,
        value_ranges=tier.value_ranges,
        values=roll_values(tier.value_ranges, rng),
        ilvl=tier.ilvl,
    )


def _add(item: Item, new_affix: RolledAffix) -> Item:
    if new_affix.affix is Affix.PREFIX:
        return dataclasses.replace(item, prefixes=item.prefixes + (new_affix,))
    return dataclasses.replace(item, suffixes=item.suffixes + (new_affix,))


def _add_fresh_fillers(
    gamedata: GameData, item: Item, affix: Affix, count: int, exclude_mod_ids: frozenset[ModId], rng: random.Random
) -> Item:
    for _ in range(count):
        pool = [(m, t) for m, t in build_pool(gamedata, item, affix) if m.id not in exclude_mod_ids]
        if not pool:
            raise ConcretizeError(f"ran out of eligible {affix.value} filler mods for base {item.base_id}")
        mod, tier = weighted_pick(pool, rng)
        item = _add(item, _roll_specific(mod.id, mod.affix, mod.group_keys, tier, rng))
    return item


def concretize(gamedata: GameData, target: ResolvedTarget, state: AbstractState, rng: random.Random) -> Item:
    """Build one fresh concrete Item consistent with `state`, re-randomizing
    every filler mod on every call (see module docstring)."""
    item = Item(base_id=target.base_id, ilvl=target.ilvl, rarity=state.rarity)
    # Present target mods are looked up across ALL categories (not just the
    # rollable pool) since a target mod may be essence-exclusive (only ever
    # placed here, in concretize -- never drawn by the general filler pool
    # below, which correctly stays rollable-only).
    tiers_for_base = gamedata.all_tiers_by_base.get(target.base_id, {})

    present = [(req, s) for req, s in zip(target.target_mods, state.status) if s != ModStatus.ABSENT]
    exclude = frozenset(req.mod_id for req in target.target_mods)  # fillers must never accidentally be *any* target mod

    for req, s in present:
        mod = gamedata.mods[req.mod_id]
        if mod.group_keys & item.occupied_group_keys():
            raise ConcretizeError(f"target mod {mod.name!r} shares an exclusion group with another present target mod")
        eligible_tiers = [t for t in tiers_for_base.get(req.mod_id, []) if t.ilvl <= target.ilvl]
        # SATISFIED needs a tier at/above the requested min_ilvl; BELOW_TIER
        # (only ever produced for a mod that *has* a min_ilvl) needs one
        # below it -- concretizing the "wrong" tier for the state's own
        # status would make a later abstractify() disagree with it.
        if s == ModStatus.SATISFIED:
            qualifying = [t for t in eligible_tiers if t.ilvl >= req.min_ilvl]
        else:
            qualifying = [t for t in eligible_tiers if t.ilvl < req.min_ilvl]
        if not qualifying:
            raise ConcretizeError(
                f"mod {mod.name!r} has no ilvl-{target.ilvl}-eligible tier satisfying status {s!r} "
                f"(min_ilvl={req.min_ilvl}) on base {target.base_id}"
            )
        tier = rng.choice(qualifying)
        item = _add(item, _roll_specific(req.mod_id, mod.affix, mod.group_keys, tier, rng))

    remaining_prefix = state.prefix_count - item.prefix_count
    remaining_suffix = state.suffix_count - item.suffix_count
    if remaining_prefix < 0 or remaining_suffix < 0:
        raise ConcretizeError(f"state {state} has fewer prefix/suffix slots than its present target mods need")

    item = _add_fresh_fillers(gamedata, item, Affix.PREFIX, remaining_prefix, exclude, rng)
    item = _add_fresh_fillers(gamedata, item, Affix.SUFFIX, remaining_suffix, exclude, rng)
    return item
