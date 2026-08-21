"""FastAPI dependencies -- all just pull off `app.state`, set once at startup
in `web.app.create_app` (GameData is loaded once, not per request)."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

from fastapi import Request

from poe2craft.data.loader import GameData
from poe2craft.pricing.settings_store import TradeSettingsStore
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.pricing.transport import RequestsTransport
from poe2craft.web.session import SessionStore

if TYPE_CHECKING:
    # Deferred to avoid a cycle: web.solve_status's router imports
    # get_solve_status_tracker from this module.
    from poe2craft.web.solve_status import SolveStatusTracker


def get_gamedata(request: Request) -> GameData:
    return request.app.state.gamedata


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_executor(request: Request) -> ProcessPoolExecutor | None:
    """`None` when the process pool is disabled or failed its startup health
    check -- callers must treat that as "solve sequentially," not an error."""
    return request.app.state.executor


def get_trade_settings_store(request: Request) -> TradeSettingsStore:
    return request.app.state.trade_settings


def get_trade_client(request: Request) -> TradeClient:
    """A fresh `TradeClient` per request, built from whatever the trade
    settings store currently resolves to (env vars, overlaid by anything
    saved via the web UI's Trade settings panel -- see
    `pricing.config.TradeConfig.load`). Deliberately not cached on
    `app.state` the way `get_trade_stat_mapping` is: a cached client would
    keep using stale settings after a `PUT /api/trade-settings` until the
    server restarted. Only the underlying `requests.Session` (via
    `RequestsTransport`) is reused across requests -- constructing a new
    `TradeClient` wrapper around it is cheap, and this never performs a
    network call by itself (see docs/data_provenance.md: this whole
    subsystem must only ever fire on an explicit user action, and a real
    trade2 request only happens once a route actually calls
    `.search()`/`.fetch()`, not from constructing the client)."""
    transport = getattr(request.app.state, "trade_transport", None)
    if transport is None:
        transport = RequestsTransport()
        request.app.state.trade_transport = transport
    settings: TradeSettingsStore = request.app.state.trade_settings
    return TradeClient(settings.current(), transport)


def get_solve_status_tracker(request: Request) -> "SolveStatusTracker":
    return request.app.state.solve_status


def get_trade_stat_mapping(request: Request) -> dict:
    """Loaded lazily and cached on `app.state` -- see
    poe2craft.pricing.stat_matching.load_mod_stat_mapping. Tests override
    this dependency directly rather than relying on the real compiled file
    existing."""
    mapping = getattr(request.app.state, "trade_stat_mapping", None)
    if mapping is None:
        from poe2craft.pricing.stat_matching import load_mod_stat_mapping

        mapping = load_mod_stat_mapping()
        request.app.state.trade_stat_mapping = mapping
    return mapping
