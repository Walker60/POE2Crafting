"""Where the one secret this package needs (a PoE account session cookie) is
read -- see docs/data_provenance.md for the full credential-handling stance:
read only here from the environment, never logged or `repr()`'d, never a
field on any web request/response model, never guessed at.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from poe2craft.pricing.errors import TradeConfigError


@dataclass(frozen=True)
class TradeConfig:
    poesessid: str | None = field(default=None, repr=False)
    league: str | None = None

    @classmethod
    def from_env(cls) -> "TradeConfig":
        return cls(
            poesessid=os.environ.get("POE2CRAFT_POESESSID") or None,
            league=os.environ.get("POE2CRAFT_TRADE_LEAGUE") or None,
        )

    def require_league(self) -> str:
        if not self.league:
            raise TradeConfigError(
                "No PoE2 trade league configured -- set the POE2CRAFT_TRADE_LEAGUE "
                "environment variable to the exact trade-site league name (e.g. the "
                "current challenge league). This is never guessed automatically: "
                "silently querying the wrong league's economy would be worse than "
                "refusing to run. See poe2craft.pricing.leagues.list_poe2_leagues "
                "for the real current options."
            )
        return self.league

    def cookie_header(self) -> dict[str, str]:
        """Built fresh at each call site from this immutable config -- never
        stored on a request object or logged."""
        return {"Cookie": f"POESESSID={self.poesessid}"} if self.poesessid else {}
