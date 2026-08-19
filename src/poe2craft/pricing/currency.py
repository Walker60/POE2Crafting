"""Converts a trade2 listing's price (amount + trade2's internal currency
key, e.g. 3x "divine") into the Divine-Orb terms the rest of this project
already prices everything in (`GameData.prices`, `engine.apply`'s action
costs, the solver's `objective="cost"` expected value) -- so a market price
and a craft-cost estimate are directly comparable."""
from __future__ import annotations

from poe2craft.data.loader import GameData

_TRADE_CURRENCY_KEY_TO_PRICE_NAME: dict[str, str] = {
    "exalted": "Exalted Orb",
    "chaos": "Chaos Orb",
    "regal": "Regal Orb",
    "alch": "Orb of Alchemy",
    "annul": "Orb of Annulment",
    "vaal": "Vaal Orb",
}
"""trade2's internal currency filter keys -> this project's own price-table
display names (`GameData.prices`). Not exhaustive -- only currencies a rare
item listing is realistically priced in; anything else means `to_divine`
returns None rather than guessing a rate."""


def to_divine(gamedata: GameData, amount: float, currency_key: str) -> float | None:
    """None when this currency isn't one this project has a real Divine-Orb
    rate for -- callers must drop that listing from any aggregate, not
    silently coerce it to some assumed rate."""
    if currency_key == "divine":
        return amount
    price_name = _TRADE_CURRENCY_KEY_TO_PRICE_NAME.get(currency_key)
    if price_name is None:
        return None
    rate = gamedata.prices.get(price_name)
    if rate is None:
        return None
    return amount * rate
