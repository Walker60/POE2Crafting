"""HTTP transport for `trade_client.py`/`leagues.py` -- `RequestsTransport`
is the *only* class in this codebase that performs a real network call to
pathofexile.com. Everything above it takes a `Transport`, so tests (and
anything else that must never touch the live API) substitute a fake -- see
tests/conftest.py's repo-wide network-block fixture, which exists precisely
because this is the one place that could otherwise leak a real call."""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Protocol

import requests

USER_AGENT = "poe2craft/0.1 (personal, non-commercial; see docs/data_provenance.md)"

_FALLBACK_DELAY_SECONDS = 1.0
"""Used before a request and whenever a response carries no parseable
rate-limit header at all. trade2's rate-limit headers aren't officially
documented (see docs/data_provenance.md) -- this is a conservative floor,
not a tuned value, and real responses are expected to shrink or grow it via
`RateLimiter.observe`."""


class Response(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> Any: ...


class Transport(Protocol):
    def get(self, url: str, *, params: dict | None = None, headers: Mapping[str, str] | None = None) -> Response: ...

    def post(self, url: str, *, json: dict, headers: Mapping[str, str] | None = None) -> Response: ...


def _parse_retry_delay(headers: Mapping[str, str]) -> float | None:
    """Scans for the standard `Retry-After` header plus anything shaped like
    GGG's documented rate-limit headers on their *other* APIs (comma-separated
    `hits:period:restricted_seconds` triples under an `X-Rate-Limit-*` name) --
    without assuming exact header names, since trade2's aren't published.
    Returns the longest wait implied by anything that parsed, or None."""
    delays: list[float] = []
    retry_after = headers.get("Retry-After")
    if retry_after is not None:
        try:
            delays.append(float(retry_after))
        except ValueError:
            pass
    for name, value in headers.items():
        if not name.lower().startswith("x-rate-limit"):
            continue
        for triple in value.split(","):
            parts = triple.split(":")
            if len(parts) != 3:
                continue
            try:
                _hits, _period, restricted = (int(p) for p in parts)
            except ValueError:
                continue
            if restricted > 0:
                delays.append(float(restricted))
    return max(delays) if delays else None


class RateLimiter:
    """Tracks the delay to apply before the *next* request, learned from the
    previous response's headers. Generic and conservative rather than
    hardcoding trade2-specific limits -- see module docstring."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep, fallback_delay: float = _FALLBACK_DELAY_SECONDS) -> None:
        self._sleep = sleep
        self._fallback_delay = fallback_delay
        self._next_delay = fallback_delay

    def wait(self) -> None:
        self._sleep(self._next_delay)

    def observe(self, response: Response) -> float | None:
        """Updates the delay for the next call from this response's headers.
        Returns the parsed retry delay when this response was itself
        rate-limited (HTTP 429), else None."""
        parsed = _parse_retry_delay(response.headers)
        if response.status_code == 429:
            retry = parsed if parsed is not None else self._fallback_delay
            self._next_delay = retry
            return retry
        self._next_delay = parsed if parsed is not None else self._fallback_delay
        return None


class RequestsTransport:
    """Thin `requests` wrapper -- exists so `TradeClient`/`leagues.py` depend
    on the `Transport` protocol, not `requests` directly. See module
    docstring: this is the one class allowed to touch the real network."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._session = requests.Session()
        self._timeout = timeout

    def get(self, url: str, *, params: dict | None = None, headers: Mapping[str, str] | None = None) -> requests.Response:
        return self._session.get(url, params=params, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=self._timeout)

    def post(self, url: str, *, json: dict, headers: Mapping[str, str] | None = None) -> requests.Response:
        return self._session.post(url, json=json, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=self._timeout)
