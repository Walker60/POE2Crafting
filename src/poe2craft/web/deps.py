"""FastAPI dependencies -- all just pull off `app.state`, set once at startup
in `web.app.create_app` (GameData is loaded once, not per request)."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

from fastapi import Request

from poe2craft.data.loader import GameData
from poe2craft.pricing.config import TradeConfig
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.pricing.transport import RequestsTransport
from poe2craft.web.session import SessionStore


def get_gamedata(request: Request) -> GameData:
    return request.app.state.gamedata


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_executor(request: Request) -> ProcessPoolExecutor | None:
    """`None` when the process pool is disabled or failed its startup health
    check -- callers must treat that as "solve sequentially," not an error."""
    return request.app.state.executor


def get_trade_client(request: Request) -> TradeClient:
    """Built lazily on first use, not at server startup -- constructing this
    never requires POE2CRAFT_POESESSID/POE2CRAFT_TRADE_LEAGUE to be set, and
    never performs a network call by itself (see docs/data_provenance.md:
    this whole subsystem must only ever fire on an explicit user action, and
    a real trade2 request only happens once a route actually calls
    `.search()`/`.fetch()`, not from constructing the client)."""
    client = getattr(request.app.state, "trade_client", None)
    if client is None:
        client = TradeClient(TradeConfig.from_env(), RequestsTransport())
        request.app.state.trade_client = client
    return client


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
