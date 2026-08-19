"""Discovers real, currently-active PoE2 league names.

Originally used GGG's officially documented Leagues endpoint
(`api.pathofexile.com/leagues`) with a `realm=poe2` filter -- that turned
out to be a real bug, not just a lower-risk source: verified live (2026-08),
that endpoint silently ignores the `realm` parameter entirely and *always*
returns PoE1 leagues (every entry tagged `"realm": "pc"`), including
whatever PoE1's own current league happens to be, mislabeled as a PoE2
option. Switched to `GET /api/trade2/data/leagues` -- an unofficial trade2
endpoint like the rest of this package (not the "materially different,
GGG-sanctioned" endpoint this module previously claimed; see
docs/data_provenance.md, which has been corrected to match), but one that
actually returns real, `realm: "poe2"`-tagged league ids (confirmed live:
"Runes of Aldur" as the current challenge league, not the *expansion* name
"Return of the Ancients" that's sometimes used interchangeably -- PoE2
patches and leagues don't always share a name)."""
from __future__ import annotations

from poe2craft.pricing.errors import TradeAPIError
from poe2craft.pricing.transport import Transport

LEAGUES_URL = "https://www.pathofexile.com/api/trade2/data/leagues"


def list_poe2_leagues(transport: Transport) -> list[str]:
    """Real, currently-active PoE2 league names. No POESESSID needed."""
    response = transport.get(LEAGUES_URL)
    if response.status_code != 200:
        raise TradeAPIError(f"leagues endpoint returned HTTP {response.status_code}")
    try:
        body = response.json()
        return [entry["id"] for entry in body["result"] if entry.get("realm") == "poe2"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TradeAPIError(f"unexpected trade2 leagues response shape: {body!r}") from exc


def validate_league(transport: Transport, league: str) -> None:
    """Raises `TradeAPIError` naming the real active leagues if `league`
    isn't one of them. Callers should call this once per process/session,
    not per query -- it's a sanity check, not something to spend the rate
    limit budget on repeatedly."""
    leagues = list_poe2_leagues(transport)
    if league not in leagues:
        raise TradeAPIError(f"{league!r} isn't a currently active PoE2 league. Active leagues: {leagues}")
