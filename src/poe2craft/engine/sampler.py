"""The actual random draws: picking one (mod, tier) from a weighted pool, and
rolling numeric values within a tier's ranges. Kept separate from pool.py so
"what's possible and how likely" (pool construction) and "actually draw one"
(sampling) can be tested independently.
"""
from __future__ import annotations

import random

from poe2craft.data.loader import GameData
from poe2craft.domain.items import Item, RolledAffix
from poe2craft.domain.mods import Affix
from poe2craft.engine.pool import NoEligibleModsError, PoolEntry, build_combined_pool, build_pool


def weighted_pick(pool: list[PoolEntry], rng: random.Random) -> PoolEntry:
    if not pool:
        raise NoEligibleModsError("empty pool")
    total = sum(tier.weight for _, tier in pool)
    r = rng.uniform(0, total)
    upto = 0.0
    for entry in pool:
        upto += entry[1].weight
        if upto >= r:
            return entry
    return pool[-1]  # floating-point fallback, negligible probability


def weighted_sample_without_replacement(pool: list[PoolEntry], k: int, rng: random.Random) -> list[PoolEntry]:
    """`k` weighted draws from `pool` with no repeats -- what a Desecration
    bone's "reveal 3 (or 6, with Omen of Abyssal Echoes) candidates" actually
    does; a real reveal never shows the same (mod, tier) twice. Returns fewer
    than `k` entries if the pool is smaller than `k` (draws everything once)
    rather than raising -- an exhausted-pool edge case the caller (a small
    base's Desecrated pool for one affix side) can hit legitimately."""
    working = list(pool)
    picks: list[PoolEntry] = []
    for _ in range(min(k, len(working))):
        pick = weighted_pick(working, rng)
        picks.append(pick)
        working.remove(pick)
    return picks


def roll_values(tier_value_ranges: tuple[tuple[float, float], ...], rng: random.Random) -> tuple[float, ...]:
    return tuple(rng.uniform(lo, hi) for lo, hi in tier_value_ranges)


def roll_new_affix(
    gamedata: GameData,
    item: Item,
    affix: Affix,
    rng: random.Random,
    min_ilvl: int = 0,
    required_tags: frozenset[str] | None = None,
) -> RolledAffix:
    """Draw one brand-new affix (mod + tier + rolled values) eligible for `item`
    right now. Raises NoEligibleModsError if nothing is eligible -- callers
    should check `pool.has_room` and non-empty eligibility before relying on
    this succeeding. `min_ilvl` restricts to Greater/Perfect-tier mods;
    `required_tags` restricts to mods sharing a broad category (Omen of
    Homogenising Coronation/Exaltation)."""
    pool = build_pool(gamedata, item, affix, min_ilvl=min_ilvl, required_tags=required_tags)
    return _draw(pool, rng)


def roll_new_affix_any(
    gamedata: GameData, item: Item, rng: random.Random, min_ilvl: int = 0, required_tags: frozenset[str] | None = None
) -> RolledAffix:
    """Like roll_new_affix, but draws from the combined prefix+suffix pool
    (respecting each side's own room cap) -- used by actions that add "one
    random affix" without specifying which type, e.g. Transmutation/Alchemy/
    Exalted Orb."""
    pool = build_combined_pool(gamedata, item, min_ilvl=min_ilvl, required_tags=required_tags)
    return _draw(pool, rng)


def _draw(pool: list[PoolEntry], rng: random.Random) -> RolledAffix:
    mod, tier = weighted_pick(pool, rng)
    return RolledAffix(
        mod_id=mod.id,
        affix=mod.affix,
        group_keys=mod.group_keys,
        value_ranges=tier.value_ranges,
        values=roll_values(tier.value_ranges, rng),
        ilvl=tier.ilvl,
    )
