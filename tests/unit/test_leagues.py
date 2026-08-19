"""list_poe2_leagues/validate_league against GGG's officially documented
Leagues endpoint -- a different legal footing than the rest of the pricing
package, see poe2craft.pricing.leagues' module docstring."""
import pytest

from poe2craft.pricing.errors import TradeAPIError
from poe2craft.pricing.leagues import list_poe2_leagues, validate_league
from pricing_fakes import FakeResponse, FakeTransport


def test_list_poe2_leagues_parses_ids_and_passes_realm_param():
    transport = FakeTransport([FakeResponse(200, [{"id": "Standard"}, {"id": "Hardcore"}])])
    leagues = list_poe2_leagues(transport)
    assert leagues == ["Standard", "Hardcore"]
    _method, _url, params, _headers = transport.calls[0]
    assert params == {"realm": "poe2"}


def test_list_poe2_leagues_raises_on_non_200():
    transport = FakeTransport([FakeResponse(503, [])])
    with pytest.raises(TradeAPIError):
        list_poe2_leagues(transport)


def test_list_poe2_leagues_raises_on_unexpected_shape():
    transport = FakeTransport([FakeResponse(200, {"not": "a list"})])
    with pytest.raises(TradeAPIError):
        list_poe2_leagues(transport)


def test_validate_league_passes_silently_when_league_is_active():
    transport = FakeTransport([FakeResponse(200, [{"id": "Standard"}])])
    validate_league(transport, "Standard")  # no raise


def test_validate_league_raises_naming_active_leagues_when_not_found():
    transport = FakeTransport([FakeResponse(200, [{"id": "Standard"}, {"id": "Hardcore"}])])
    with pytest.raises(TradeAPIError, match="Standard"):
        validate_league(transport, "SomeTypo")
