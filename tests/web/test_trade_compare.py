"""POST /api/sessions/{id}/trade-compare -- wired entirely through dependency
overrides and a monkeypatched valuation layer, never a real TradeClient or
network call. See src/poe2craft/web/crafting.py's trade_compare route and
docs/data_provenance.md's opt-in-only invariant, which the last test here
checks directly."""
from poe2craft.pricing.valuation import PriceEstimate
from poe2craft.web.deps import get_trade_client, get_trade_stat_mapping


class _FakeTradeClient:
    league = "Standard"


def _create_session(client, objective="cost"):
    resp = client.post(
        "/api/sessions",
        json={
            "base_id": "base1",
            "ilvl": 80,
            "rarity": "normal",
            "current_mods": [],
            "target_mods": [{"mod_id": "p1"}],
            "objective": objective,
            "n_trials": 20,
            "seed": 0,
        },
    )
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _override_trade_deps(app):
    app.dependency_overrides[get_trade_client] = lambda: _FakeTradeClient()
    app.dependency_overrides[get_trade_stat_mapping] = lambda: {}


def test_trade_compare_recommends_the_cheapest_option(app, client, monkeypatch):
    session_id = _create_session(client)
    # Vanishingly cheap buy price, and no usable sell estimate at all -- the
    # only way "buy" can win against "keep_crafting" (which even a toy
    # fixture's real currency costs make comfortably larger than this) is if
    # "sell_and_restart" isn't in the running because sell_value is None.
    buy = PriceEstimate(divine_price=0.0001, n_listings=5, listing_prices_divine=(0.0001, 0.0002))
    sell = PriceEstimate(divine_price=None, n_listings=1, listing_prices_divine=(0.01,), caveats=("fewer than 3 comparable listings",))
    _override_trade_deps(app)
    monkeypatch.setattr("poe2craft.web.crafting.estimate_buy_price", lambda *a, **k: buy)
    monkeypatch.setattr("poe2craft.web.crafting.estimate_sell_value", lambda *a, **k: sell)

    resp = client.post(f"/api/sessions/{session_id}/trade-compare")
    assert resp.status_code == 200
    body = resp.json()
    assert body["league"] == "Standard"
    assert body["buy_price"] == 0.0001
    assert body["sell_and_restart_net_cost"] is None  # no sell estimate -- that leg isn't considered
    assert body["recommendation"] == "buy"


def test_trade_compare_recommends_selling_and_restarting_when_that_nets_a_profit(app, client, monkeypatch):
    session_id = _create_session(client)
    buy = PriceEstimate(divine_price=None, n_listings=0, listing_prices_divine=(), caveats=("no matching listings found",))
    sell = PriceEstimate(divine_price=1000.0, n_listings=5, listing_prices_divine=(1000.0,))
    _override_trade_deps(app)
    monkeypatch.setattr("poe2craft.web.crafting.estimate_buy_price", lambda *a, **k: buy)
    monkeypatch.setattr("poe2craft.web.crafting.estimate_sell_value", lambda *a, **k: sell)

    resp = client.post(f"/api/sessions/{session_id}/trade-compare")
    body = resp.json()
    assert body["sell_and_restart_net_cost"] < 0  # selling for 1000 vastly outweighs re-crafting cost
    assert body["recommendation"] == "sell_and_restart"


def test_trade_compare_requires_cost_objective(app, client):
    session_id = _create_session(client, objective="steps")
    _override_trade_deps(app)  # dependencies resolve before the route body's own objective check runs
    resp = client.post(f"/api/sessions/{session_id}/trade-compare")
    assert resp.status_code == 422


def test_trade_compare_404s_on_unknown_session(app, client):
    app.dependency_overrides[get_trade_client] = lambda: _FakeTradeClient()
    app.dependency_overrides[get_trade_stat_mapping] = lambda: {}
    resp = client.post("/api/sessions/does-not-exist/trade-compare")
    assert resp.status_code == 404


def test_create_and_advance_never_touch_the_trade_client(app, client, monkeypatch):
    """The core invariant this feature must never violate: a live crafting
    session never fires a trade2 request on its own -- only an explicit
    POST to /trade-compare does."""
    calls = []
    app.dependency_overrides[get_trade_client] = lambda: calls.append("get_trade_client") or _FakeTradeClient()

    session_id = _create_session(client)
    client.post(f"/api/sessions/{session_id}/advance", json={"rarity": "normal", "current_mods": []})
    client.get(f"/api/sessions/{session_id}")

    assert calls == []
