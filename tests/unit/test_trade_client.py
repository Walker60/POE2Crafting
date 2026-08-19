"""TradeClient.search()/fetch() -- query/response shape handling, /fetch
batching over 10 ids, and the loud-failure posture on an unexpected shape.
Never touches the real network -- see pricing_fakes.FakeTransport and
tests/conftest.py's repo-wide backstop."""
import pytest

from poe2craft.pricing.config import TradeConfig
from poe2craft.pricing.errors import RateLimitExceeded, TradeAPIError
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.pricing.transport import RateLimiter
from pricing_fakes import FakeResponse, FakeTransport

CONFIG = TradeConfig(poesessid="deadbeef", league="Standard")


def _client(transport: FakeTransport) -> TradeClient:
    return TradeClient(CONFIG, transport, rate_limiter=RateLimiter(sleep=lambda _: None))


def test_search_parses_id_and_result_list():
    transport = FakeTransport([FakeResponse(200, {"id": "abc123", "result": ["r1", "r2", "r3"]})])
    result = _client(transport).search({"query": {}})
    assert result.search_id == "abc123"
    assert result.result_ids == ("r1", "r2", "r3")


def test_search_sends_league_in_url_and_cookie_header():
    transport = FakeTransport([FakeResponse(200, {"id": "abc", "result": []})])
    _client(transport).search({"query": {}})
    method, url, body, headers = transport.calls[0]
    assert method == "POST"
    assert url == "https://www.pathofexile.com/api/trade2/search/poe2/Standard"
    assert headers["Cookie"] == "POESESSID=deadbeef"


def test_search_raises_trade_api_error_on_unexpected_shape():
    transport = FakeTransport([FakeResponse(200, {"unexpected": "shape"})])
    with pytest.raises(TradeAPIError):
        _client(transport).search({"query": {}})


def test_search_raises_trade_api_error_on_non_200():
    transport = FakeTransport([FakeResponse(500, {})])
    with pytest.raises(TradeAPIError):
        _client(transport).search({"query": {}})


def _listing_entry(entry_id: str, amount: float, currency: str = "divine") -> dict:
    return {"id": entry_id, "listing": {"price": {"amount": amount, "currency": currency}, "account": {"name": "acc"}}}


def test_fetch_parses_listings_and_skips_none_entries():
    transport = FakeTransport(
        [FakeResponse(200, {"result": [_listing_entry("a", 1.5), None, _listing_entry("b", 2.0, "exalted")]})]
    )
    listings = _client(transport).fetch("search1", ["a", "b", "c"])
    assert [l.id for l in listings] == ["a", "b"]
    assert listings[1].price_currency == "exalted"


def test_fetch_batches_over_ten_ids_into_multiple_calls():
    ids = [f"id{i}" for i in range(15)]
    transport = FakeTransport(
        [
            FakeResponse(200, {"result": [_listing_entry(i, 1.0) for i in ids[:10]]}),
            FakeResponse(200, {"result": [_listing_entry(i, 1.0) for i in ids[10:]]}),
        ]
    )
    listings = _client(transport).fetch("search1", ids)
    assert len(listings) == 15
    assert len(transport.calls) == 2
    assert transport.calls[0][1].count(",") == 9  # 10 ids joined by 9 commas
    assert transport.calls[1][1].count(",") == 4


def test_fetch_raises_trade_api_error_on_unexpected_shape():
    transport = FakeTransport([FakeResponse(200, {"result": [{"id": "a"}]})])  # missing "listing"
    with pytest.raises(TradeAPIError):
        _client(transport).fetch("search1", ["a"])


def test_rate_limited_twice_in_a_row_raises_rate_limit_exceeded():
    transport = FakeTransport([FakeResponse(429, {}, headers={"Retry-After": "1"}), FakeResponse(429, {}, headers={"Retry-After": "1"})])
    with pytest.raises(RateLimitExceeded):
        _client(transport).search({"query": {}})


def test_recovers_after_a_single_rate_limit_response():
    transport = FakeTransport([FakeResponse(429, {}, headers={"Retry-After": "1"}), FakeResponse(200, {"id": "x", "result": []})])
    result = _client(transport).search({"query": {}})
    assert result.search_id == "x"
    assert len(transport.calls) == 2
