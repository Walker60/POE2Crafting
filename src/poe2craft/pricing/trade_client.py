"""Client for pathofexile.com/trade2's unofficial search/fetch endpoints.

See docs/data_provenance.md for why these are used despite sitting outside
GGG's documented API, and what's done to keep that contained: opt-in only
(nothing in this module is ever called automatically), the request/response
shapes below follow the well-established convention PoE1's trade API uses
(community-tool consensus, not official docs -- expect to adjust
`_build_query`/the parsing here once verified against a real response, see
the plan's sequencing note), and any shape mismatch raises `TradeAPIError`
loudly rather than silently returning a wrong price.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from poe2craft.pricing.config import TradeConfig
from poe2craft.pricing.errors import RateLimitExceeded, TradeAPIError
from poe2craft.pricing.transport import RateLimiter, Response, Transport

SEARCH_URL = "https://www.pathofexile.com/api/trade2/search/poe2/{league}"
FETCH_URL = "https://www.pathofexile.com/api/trade2/fetch/{ids}"
_FETCH_BATCH_SIZE = 10  # trade2 rejects more than this in one /fetch call, per every community tool's convention


@dataclass(frozen=True)
class SearchResult:
    search_id: str
    result_ids: tuple[str, ...]


@dataclass(frozen=True)
class Listing:
    id: str
    price_amount: float
    price_currency: str  # trade2's internal currency key, e.g. "divine"/"exalted" -- see pricing.currency
    account_name: str


class TradeClient:
    def __init__(self, config: TradeConfig, transport: Transport, rate_limiter: RateLimiter | None = None) -> None:
        self._config = config
        self._transport = transport
        self._rate_limiter = rate_limiter or RateLimiter()

    @property
    def league(self) -> str:
        return self._config.require_league()

    def search(self, query: dict) -> SearchResult:
        url = SEARCH_URL.format(league=self.league)
        response = self._send(self._transport.post, url, json=query, headers=self._config.cookie_header())
        body = self._expect_json(response, "search")
        try:
            return SearchResult(search_id=body["id"], result_ids=tuple(body["result"]))
        except (KeyError, TypeError) as exc:
            raise TradeAPIError(f"unexpected /trade2/search response shape: {body!r}") from exc

    def fetch(self, search_id: str, ids: Sequence[str]) -> list[Listing]:
        listings: list[Listing] = []
        for start in range(0, len(ids), _FETCH_BATCH_SIZE):
            batch = ids[start : start + _FETCH_BATCH_SIZE]
            url = FETCH_URL.format(ids=",".join(batch))
            response = self._send(self._transport.get, url, params={"query": search_id}, headers=self._config.cookie_header())
            body = self._expect_json(response, "fetch")
            try:
                for entry in body["result"]:
                    if entry is None:  # sold/delisted between search and fetch -- not an error
                        continue
                    listing = entry["listing"]
                    price = listing["price"]
                    listings.append(
                        Listing(
                            id=entry["id"],
                            price_amount=float(price["amount"]),
                            price_currency=price["currency"],
                            account_name=listing["account"]["name"],
                        )
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise TradeAPIError(f"unexpected /trade2/fetch response shape: {body!r}") from exc
        return listings

    def _send(self, fn, *args, **kwargs) -> Response:
        self._rate_limiter.wait()
        response = fn(*args, **kwargs)
        retry = self._rate_limiter.observe(response)
        if retry is not None:
            self._rate_limiter.wait()
            response = fn(*args, **kwargs)
            if self._rate_limiter.observe(response) is not None:
                raise RateLimitExceeded("pathofexile.com/trade2 rate-limited this request twice in a row -- backing off")
        return response

    @staticmethod
    def _expect_json(response: Response, endpoint_name: str) -> dict:
        if response.status_code != 200:
            raise TradeAPIError(f"/trade2/{endpoint_name} returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise TradeAPIError(f"/trade2/{endpoint_name} response wasn't valid JSON") from exc
