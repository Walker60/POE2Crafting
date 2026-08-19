"""Buy/sell/premium price estimates built on top of `TradeClient`.

Query construction (`_build_query`) was verified live (2026-08-19, logged
out, no POESESSID): the `status`/`stats`/`filters.type_filters.rarity`
shape below returned real results on the first try, but scoping to a base
via the top-level `type` field (an exact base-type name) was rejected with
"Unknown item base type" -- this project's `BaseItemDef.name` values are
generic slot names ("Amulet"), not real trade base-type names. Fixed by
scoping via `filters.type_filters.category` instead (confirmed live for
"accessory.amulet") -- see `poe2craft.pricing.categories` for the mapping
and its own, much larger, unverified-beyond-that-one-entry caveat.

Every estimate here is a market approximation, not an exact appraisal --
see each function's `PriceEstimate.caveats` for what it glosses over."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Item
from poe2craft.pricing.categories import trade_category_for
from poe2craft.pricing.currency import to_divine
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.solver.featurize import ResolvedTarget

_MIN_COMPARABLE_LISTINGS = 3
"""Below this many usable listings, an estimate is "insufficient data"
rather than a number computed from too little to be meaningful."""

_MAX_LISTINGS_CONSIDERED = 20
"""How many /fetch results one query pulls -- bounds rate-limit usage per
estimate; the cheapest-sorted search results are what matters for a buy
price or a realistic clearing price anyway, not an exhaustive listing dump."""


@dataclass(frozen=True)
class PriceEstimate:
    divine_price: float | None
    n_listings: int
    listing_prices_divine: tuple[float, ...]
    caveats: tuple[str, ...] = ()


def _build_query(category: str | None, stat_ids: Sequence[str]) -> dict:
    """Live-verified trade2 query body shape -- see module docstring. Mod
    presence via an `and`-combined stat filter group, restricted to Rare
    items and (when known) one slot category."""
    type_filters: dict = {"rarity": {"option": "rare"}}
    if category is not None:
        type_filters["category"] = {"option": category}
    query = {
        "status": {"option": "online"},
        "stats": [{"type": "and", "filters": [{"id": sid} for sid in stat_ids]}],
        "filters": {"type_filters": {"filters": type_filters}},
    }
    return {"query": query, "sort": {"price": "asc"}}


def _category_and_caveat(gamedata: GameData, base_id: BaseId) -> tuple[str | None, list[str]]:
    category = trade_category_for(gamedata, base_id)
    if category is None:
        base_name = gamedata.bases[base_id].name
        return None, [f"no known trade category for base {base_name!r} -- searched across all item slots, not just this one"]
    return category, []


def _priced_listings(client: TradeClient, gamedata: GameData, query: dict) -> list[float]:
    result = client.search(query)
    ids = result.result_ids[:_MAX_LISTINGS_CONSIDERED]
    if not ids:
        return []
    listings = client.fetch(result.search_id, ids)
    prices = (to_divine(gamedata, l.price_amount, l.price_currency) for l in listings)
    return [p for p in prices if p is not None]


def _mapped_stat_ids(mod_ids: Sequence[ModId], mod_mapping: dict[ModId, str]) -> tuple[list[str], list[ModId]]:
    stat_ids = [mod_mapping[m] for m in mod_ids if m in mod_mapping]
    unmapped = [m for m in mod_ids if m not in mod_mapping]
    return stat_ids, unmapped


def estimate_buy_price(
    client: TradeClient, gamedata: GameData, mod_mapping: dict[ModId, str], target: ResolvedTarget
) -> PriceEstimate:
    """Cheapest currently-listed Rare item matching the target's base and
    (mapped) target mods -- what it'd cost to just buy the goal right now."""
    category, caveats = _category_and_caveat(gamedata, target.base_id)
    mod_ids = [req.mod_id for req in target.target_mods]
    stat_ids, unmapped = _mapped_stat_ids(mod_ids, mod_mapping)
    if unmapped:
        caveats.append(f"{len(unmapped)} target mod(s) have no known trade stat id and weren't filtered on: {unmapped}")

    prices = _priced_listings(client, gamedata, _build_query(category, stat_ids))
    sorted_prices = tuple(sorted(prices))
    if not prices:
        return PriceEstimate(None, 0, sorted_prices, tuple(caveats + ["no matching listings found"]))
    return PriceEstimate(sorted_prices[0], len(prices), sorted_prices, tuple(caveats))


def estimate_sell_value(
    client: TradeClient, gamedata: GameData, mod_mapping: dict[ModId, str], item: Item
) -> PriceEstimate:
    """Approximate value of the item as it actually is right now: median of
    the cheapest comparable listings (a realistic clearing price, not an
    optimistic ask) sharing the item's base and whichever present mods have
    a known trade stat id. Not an exact appraisal -- see caveats."""
    category, caveats = _category_and_caveat(gamedata, item.base_id)
    caveats.insert(0, "approximate: priced against comparable listings sharing the item's mapped mods, not an exact appraisal")
    mod_ids = [a.mod_id for a in item.affixes]
    stat_ids, unmapped = _mapped_stat_ids(mod_ids, mod_mapping)
    if unmapped:
        caveats.append(f"{len(unmapped)} present mod(s) have no known trade stat id and were ignored: {unmapped}")

    prices = _priced_listings(client, gamedata, _build_query(category, stat_ids))
    sorted_prices = tuple(sorted(prices))
    if len(prices) < _MIN_COMPARABLE_LISTINGS:
        return PriceEstimate(
            None, len(prices), sorted_prices, tuple(caveats + [f"fewer than {_MIN_COMPARABLE_LISTINGS} comparable listings"])
        )
    median = statistics.median(sorted_prices[:_MIN_COMPARABLE_LISTINGS])
    return PriceEstimate(median, len(prices), sorted_prices, tuple(caveats))


def mod_premium(client: TradeClient, gamedata: GameData, mod_mapping: dict[ModId, str], base_id: BaseId, mod_id: ModId) -> PriceEstimate:
    """The market's revealed premium for one modifier: median cheapest price
    WITH it present, minus median cheapest price WITHOUT any mod filter, on
    the same base. The standalone "what's this mod worth" research tool --
    also usable to sanity-check `estimate_sell_value`'s heuristic."""
    stat_id = mod_mapping.get(mod_id)
    if stat_id is None:
        return PriceEstimate(None, 0, (), (f"mod {mod_id} has no known trade stat id -- can't query for it",))

    category, category_caveats = _category_and_caveat(gamedata, base_id)
    with_prices = sorted(_priced_listings(client, gamedata, _build_query(category, [stat_id])))
    without_prices = sorted(_priced_listings(client, gamedata, _build_query(category, [])))
    caveats = ("premium = median(cheapest, with mod) - median(cheapest, without any mod filter), same base type", *category_caveats)
    if len(with_prices) < _MIN_COMPARABLE_LISTINGS or len(without_prices) < _MIN_COMPARABLE_LISTINGS:
        return PriceEstimate(
            None, len(with_prices), tuple(with_prices), caveats + ("insufficient listings on one side to compute a premium",)
        )
    premium = statistics.median(with_prices[:_MIN_COMPARABLE_LISTINGS]) - statistics.median(without_prices[:_MIN_COMPARABLE_LISTINGS])
    return PriceEstimate(premium, len(with_prices), tuple(with_prices), caveats)


def recommend(craft_cost: float, buy_price: float | None, sell_and_restart_net_cost: float | None) -> str:
    """The cheapest of the three options, in Divine-Orb terms -- shared by
    the web `/trade-compare` route and the `trade-compare` CLI command so
    the recommendation logic exists in exactly one place. `None` legs (no
    usable price data) simply aren't in the running, never treated as free."""
    options: dict[str, float] = {"keep_crafting": craft_cost}
    if buy_price is not None:
        options["buy"] = buy_price
    if sell_and_restart_net_cost is not None:
        options["sell_and_restart"] = sell_and_restart_net_cost
    return min(options, key=options.get) if options else "insufficient_data"
