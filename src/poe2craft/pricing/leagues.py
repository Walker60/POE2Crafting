"""Discovers real, currently-active PoE2 league names via GGG's *officially
documented* Leagues endpoint (`api.pathofexile.com`) -- a different legal
footing than the unofficial trade2 search/fetch/stats endpoints elsewhere in
this package (see docs/data_provenance.md). Used only to validate a
configured league name against reality; this project never auto-selects
"the" current league -- see `pricing.config.TradeConfig.require_league`."""
from __future__ import annotations

from poe2craft.pricing.errors import TradeAPIError
from poe2craft.pricing.transport import Transport

LEAGUES_URL = "https://api.pathofexile.com/leagues"


def list_poe2_leagues(transport: Transport) -> list[str]:
    """Real, currently-active PoE2 league names, per GGG's documented API.
    No POESESSID needed -- this specific endpoint is public."""
    response = transport.get(LEAGUES_URL, params={"realm": "poe2"})
    if response.status_code != 200:
        raise TradeAPIError(f"leagues endpoint returned HTTP {response.status_code}")
    try:
        body = response.json()
        return [entry["id"] for entry in body]
    except (ValueError, KeyError, TypeError) as exc:
        raise TradeAPIError(f"unexpected /leagues response shape: {body!r}") from exc


def validate_league(transport: Transport, league: str) -> None:
    """Raises `TradeAPIError` naming the real active leagues if `league`
    isn't one of them. Callers should call this once per process/session,
    not per query -- it's a sanity check, not something to spend the rate
    limit budget on repeatedly."""
    leagues = list_poe2_leagues(transport)
    if league not in leagues:
        raise TradeAPIError(f"{league!r} isn't a currently active PoE2 league. Active leagues: {leagues}")
