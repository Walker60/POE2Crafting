"""Global trade-pricing settings (league + POESESSID), editable via the web
UI's Trade settings panel in addition to the POE2CRAFT_TRADE_LEAGUE/
POE2CRAFT_POESESSID environment variables. See
`poe2craft.pricing.config.TradeConfig.load` for the precedence rules and
docs/data_provenance.md for the plaintext-local-file tradeoff this makes.

Global, not per-session -- unlike everything in web.crafting, these routes
aren't scoped to a session id."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from poe2craft.pricing.leagues import list_poe2_leagues
from poe2craft.pricing.settings_store import TradeSettingsStore
from poe2craft.pricing.transport import RequestsTransport
from poe2craft.web.deps import get_trade_settings_store
from poe2craft.web.schemas import TradeSettingsResponse, TradeSettingsUpdateRequest

router = APIRouter(prefix="/api/trade-settings", tags=["trade-settings"])


def _build_response(store: TradeSettingsStore) -> TradeSettingsResponse:
    config = store.current()
    active_leagues: list[str] | None = None
    active_leagues_error: str | None = None
    try:
        active_leagues = list_poe2_leagues(RequestsTransport())
    except Exception as exc:  # noqa: BLE001 -- a transient failure to list leagues must never block reading/saving your own settings
        active_leagues_error = str(exc)
    return TradeSettingsResponse(
        league=config.league,
        poesessid_set=bool(config.poesessid),
        active_leagues=active_leagues,
        active_leagues_error=active_leagues_error,
    )


@router.get("", response_model=TradeSettingsResponse)
def get_settings(store: TradeSettingsStore = Depends(get_trade_settings_store)) -> TradeSettingsResponse:
    return _build_response(store)


@router.put("", response_model=TradeSettingsResponse)
def update_settings(
    req: TradeSettingsUpdateRequest, store: TradeSettingsStore = Depends(get_trade_settings_store)
) -> TradeSettingsResponse:
    store.update(league=req.league, poesessid=req.poesessid, clear_poesessid=req.clear_poesessid)
    return _build_response(store)
