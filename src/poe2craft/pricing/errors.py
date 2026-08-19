"""Errors for the pricing package. A response that doesn't match what this
client expects must always surface loudly -- pathofexile.com/trade2's
search/fetch/stats endpoints are undocumented (see docs/data_provenance.md),
so a shape mismatch is a real signal something changed, not something to
paper over with a fallback that could silently mis-price an item."""
from __future__ import annotations


class TradeAPIError(Exception):
    """A trade2 (or the official Leagues) endpoint returned something this
    client doesn't know how to interpret -- wrong status code, missing
    field, unparseable body."""


class RateLimitExceeded(TradeAPIError):
    """Rate-limited twice in a row despite backing off -- treated as a hard
    stop rather than retried indefinitely."""


class TradeConfigError(Exception):
    """A live query was attempted without configuration it requires
    (currently: no trade league configured)."""
