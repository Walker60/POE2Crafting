"""Shared fake Transport for pricing-package unit tests -- never a real
`requests` call (see tests/conftest.py's repo-wide network-block backstop)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeResponse:
    status_code: int
    _json: Any
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return self._json


class FakeTransport:
    """Returns each queued response in order, regardless of GET vs POST --
    matches how `TradeClient`/`leagues.py` call the transport strictly
    sequentially. Records every call for assertions."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> FakeResponse:
        self.calls.append(("GET", url, params, headers))
        return self._responses.pop(0)

    def post(self, url: str, *, json: dict, headers: dict | None = None) -> FakeResponse:
        self.calls.append(("POST", url, json, headers))
        return self._responses.pop(0)
