"""GET/PUT /api/trade-settings against the real (non-overridden)
TradeSettingsStore/get_trade_client wiring -- unlike test_trade_compare.py,
these deliberately exercise the real dependencies, backed by the `app`
fixture's isolated tmp_path settings file (tests/web/conftest.py). The live
Leagues lookup inside the route is blocked by tests/conftest.py's repo-wide
network fixture, which doubles as a test of the "never blocks on that"
resilience property."""


def test_get_settings_when_nothing_configured(client):
    resp = client.get("/api/trade-settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["league"] is None
    assert body["poesessid_set"] is False
    # The real network is blocked in tests -- this must degrade, not 500.
    assert body["active_leagues"] is None
    assert body["active_leagues_error"]


def test_put_then_get_round_trips_league_and_never_echoes_poesessid(client):
    put_resp = client.put("/api/trade-settings", json={"league": "Standard", "poesessid": "secret-cookie"})
    assert put_resp.status_code == 200
    put_body = put_resp.json()
    assert put_body["league"] == "Standard"
    assert put_body["poesessid_set"] is True
    assert "secret-cookie" not in put_resp.text  # never echoed back, anywhere in the response

    get_body = client.get("/api/trade-settings").json()
    assert get_body["league"] == "Standard"
    assert get_body["poesessid_set"] is True
    assert "secret-cookie" not in client.get("/api/trade-settings").text


def test_put_league_only_does_not_disturb_an_existing_poesessid(client):
    client.put("/api/trade-settings", json={"league": "Standard", "poesessid": "secret-cookie"})
    resp = client.put("/api/trade-settings", json={"league": "HardcoreLeague"})
    assert resp.json()["league"] == "HardcoreLeague"
    assert resp.json()["poesessid_set"] is True  # untouched by the league-only update


def test_clear_poesessid(client):
    client.put("/api/trade-settings", json={"league": "Standard", "poesessid": "secret-cookie"})
    resp = client.put("/api/trade-settings", json={"clear_poesessid": True})
    assert resp.json()["poesessid_set"] is False
    assert resp.json()["league"] == "Standard"  # unrelated field untouched
