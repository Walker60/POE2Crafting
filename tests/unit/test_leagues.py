"""list_poe2_leagues/validate_league against trade2's data/leagues endpoint
-- see poe2craft.pricing.leagues' module docstring for why this replaced
GGG's officially documented Leagues endpoint (it turned out to silently
ignore the realm filter and always return PoE1 data)."""
import pytest

from poe2craft.pricing.errors import TradeAPIError
from poe2craft.pricing.leagues import list_poe2_leagues, validate_league
from pricing_fakes import FakeResponse, FakeTransport


def _leagues_body(*entries: tuple[str, str]) -> dict:
    return {"result": [{"id": eid, "realm": realm, "text": eid} for eid, realm in entries]}


def test_list_poe2_leagues_parses_ids():
    transport = FakeTransport([FakeResponse(200, _leagues_body(("Standard", "poe2"), ("Hardcore", "poe2")))])
    leagues = list_poe2_leagues(transport)
    assert leagues == ["Standard", "Hardcore"]


def test_list_poe2_leagues_filters_out_non_poe2_realms():
    # A real, observed shape from this endpoint: PoE1 entries can appear
    # alongside PoE2 ones -- must not leak into "PoE2 leagues".
    transport = FakeTransport([FakeResponse(200, _leagues_body(("Runes of Aldur", "poe2"), ("Settlers", "pc")))])
    leagues = list_poe2_leagues(transport)
    assert leagues == ["Runes of Aldur"]


def test_list_poe2_leagues_raises_on_non_200():
    transport = FakeTransport([FakeResponse(503, {})])
    with pytest.raises(TradeAPIError):
        list_poe2_leagues(transport)


def test_list_poe2_leagues_raises_on_unexpected_shape():
    transport = FakeTransport([FakeResponse(200, {"not": "the expected shape"})])
    with pytest.raises(TradeAPIError):
        list_poe2_leagues(transport)


def test_validate_league_passes_silently_when_league_is_active():
    transport = FakeTransport([FakeResponse(200, _leagues_body(("Standard", "poe2")))])
    validate_league(transport, "Standard")  # no raise


def test_validate_league_raises_naming_active_leagues_when_not_found():
    transport = FakeTransport([FakeResponse(200, _leagues_body(("Standard", "poe2"), ("Hardcore", "poe2")))])
    with pytest.raises(TradeAPIError, match="Standard"):
        validate_league(transport, "SomeTypo")
