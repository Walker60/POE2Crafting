"""FastAPI endpoint tests via TestClient, against the small hand-built
gamedata fixture in conftest.py -- fast, real HTTP requests through the real
app, but no network and no real (large, slow) gamedata."""


def test_list_bases(client):
    resp = client.get("/api/bases")
    assert resp.status_code == 200
    names = {b["name"] for b in resp.json()}
    assert "Test Base" in names


def test_get_base_unknown_404(client):
    assert client.get("/api/bases/nope").status_code == 404


def test_list_mods_filters_by_ilvl(client, gamedata):
    base_id = next(iter(gamedata.bases))
    low = client.get(f"/api/bases/{base_id}/mods", params={"ilvl": 10}).json()
    high = client.get(f"/api/bases/{base_id}/mods", params={"ilvl": 60}).json()
    low_ids = {m["mod_id"] for m in low}
    high_ids = {m["mod_id"] for m in high}
    assert "s2" not in low_ids  # s2's only tier requires ilvl 50
    assert "s2" in high_ids


def test_list_mods_unknown_base_404(client):
    assert client.get("/api/bases/nope/mods").status_code == 404


def test_create_session_happy_path(client):
    resp = client.post(
        "/api/sessions",
        json={
            "base_id": "base1",
            "ilvl": 10,
            "rarity": "normal",
            "current_mods": [],
            "target_mods": [{"mod_id": "p1", "min_ilvl": 0}],
            "objective": "steps",
            "n_trials": 100,
            "seed": 1,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["target_progress"] == [{"mod_id": "p1", "name": "Mod p1", "min_ilvl": 0, "status": "absent"}]
    assert data["recommended_action"] is not None
    assert data["converged"] is True
    assert data["resolved_via"] is None


def test_create_session_unknown_base_404(client):
    resp = client.post(
        "/api/sessions",
        json={"base_id": "nope", "ilvl": 10, "rarity": "normal", "target_mods": [{"mod_id": "p1"}]},
    )
    assert resp.status_code == 404


def test_create_session_unreachable_target_mod_422(client):
    resp = client.post(
        "/api/sessions",
        json={"base_id": "base1", "ilvl": 10, "rarity": "normal", "target_mods": [{"mod_id": "does-not-exist"}]},
    )
    assert resp.status_code == 422


def test_create_session_bad_current_mods_422(client):
    # Normal rarity can't have any mods.
    resp = client.post(
        "/api/sessions",
        json={
            "base_id": "base1",
            "ilvl": 10,
            "rarity": "normal",
            "current_mods": [{"mod_id": "p1", "tier_ilvl": 1}],
            "target_mods": [{"mod_id": "p1"}],
        },
    )
    assert resp.status_code == 422


def test_create_session_bad_rarity_422(client):
    resp = client.post(
        "/api/sessions",
        json={"base_id": "base1", "ilvl": 10, "rarity": "legendary", "target_mods": [{"mod_id": "p1"}]},
    )
    assert resp.status_code == 422


def _setup(client, **overrides):
    body = {
        "base_id": "base1",
        "ilvl": 10,
        "rarity": "normal",
        "current_mods": [],
        "target_mods": [{"mod_id": "p1", "min_ilvl": 0}],
        "objective": "steps",
        "n_trials": 150,
        "seed": 3,
    }
    body.update(overrides)
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_advance_unknown_session_404(client):
    resp = client.post("/api/sessions/does-not-exist/advance", json={"rarity": "normal", "current_mods": []})
    assert resp.status_code == 404


def test_advance_reaching_the_goal_reports_cached_policy(client):
    data = _setup(client)
    session_id = data["session_id"]
    # p1 satisfies the (only) target mod at any tier -- report it present.
    resp = client.post(
        f"/api/sessions/{session_id}/advance",
        json={"rarity": "rare", "current_mods": [{"mod_id": "p1", "tier_ilvl": 1}]},
    )
    assert resp.status_code == 200
    advanced = resp.json()
    assert advanced["is_goal"] is True
    assert advanced["recommended_action"] is None
    assert advanced["estimated_remaining"] == 0.0


def test_advance_on_an_artificially_unseen_state_resolves_fresh(client, app, gamedata):
    """White-box test of the re-solve fallback: rather than relying on a real
    action combination happening not to be sampled (probabilistic, would make
    this test flaky), directly remove the one real, reachable state that this
    test's own `advance()` call below will land on from the session's solved
    value table, to simulate "the BFS never visited this" and confirm
    advance() notices and re-solves rather than crashing or lying.

    Multiple abstract states can satisfy `is_goal()` (e.g. Magic-with-p1 vs.
    Rare-with-p1) -- grabbing an arbitrary one via `next(... if s.is_goal())`
    doesn't reliably match the specific state `advance()` computes below, so
    this derives the exact expected state the same way the endpoint does."""
    from poe2craft.domain.items import Rarity
    from poe2craft.solver.featurize import abstractify, item_from_report

    data = _setup(client)
    session_id = data["session_id"]
    session = app.state.sessions.get(session_id)
    assert session is not None

    reported_item = item_from_report(
        gamedata, session.target.base_id, ilvl=session.target.ilvl, rarity=Rarity.RARE,
        mod_reports=[(session.target.target_mods[0].mod_id, 1)],
    )
    expected_state = abstractify(session.target, reported_item)
    assert expected_state in session.result.value  # sanity: BFS did reach it
    del session.result.value[expected_state]  # simulate "never explored"

    resp = client.post(
        f"/api/sessions/{session_id}/advance",
        json={"rarity": "rare", "current_mods": [{"mod_id": "p1", "tier_ilvl": 1}]},
    )
    assert resp.status_code == 200
    advanced = resp.json()
    assert advanced["resolved_via"] == "resolved_fresh"
    assert advanced["note"]
    assert advanced["is_goal"] is True  # the fresh solve still correctly finds it's the goal

    # The re-solve should have re-added the state -- a second report of the
    # same state now hits the (regenerated) cached policy, not another re-solve.
    resp2 = client.post(
        f"/api/sessions/{session_id}/advance",
        json={"rarity": "rare", "current_mods": [{"mod_id": "p1", "tier_ilvl": 1}]},
    )
    assert resp2.json()["resolved_via"] == "cached_policy"


def test_delete_session_then_get_404(client):
    data = _setup(client)
    session_id = data["session_id"]
    assert client.delete(f"/api/sessions/{session_id}").status_code == 204
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_parse_item_happy_path(client):
    text = (
        "Item Class: Whatever\nRarity: Rare\nTest Base\n--------\n"
        "Item Level: 10\n--------\nMod p1 (Tier: 1)\nMod s1 (Tier: 1)\n--------\n"
    )
    resp = client.post("/api/parse-item", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_id"] == "base1"
    assert data["ilvl"] == 10
    assert data["rarity"] == "rare"
    assert {(m["mod_id"], m["tier_ilvl"]) for m in data["mods"]} == {("p1", 1), ("s1", 1)}
    assert data["unmatched_lines"] == []
    assert data["ambiguous_bases"] == []


def test_parse_item_empty_text_422(client):
    resp = client.post("/api/parse-item", json={"text": "   "})
    assert resp.status_code == 422


def test_parse_item_unique_rarity_422(client):
    text = "Item Class: Whatever\nRarity: Unique\nTest Base\n--------\nItem Level: 10\n"
    resp = client.post("/api/parse-item", json={"text": text})
    assert resp.status_code == 422


def test_cost_spread_happy_path(client):
    data = _setup(client, n_trials=200)
    session_id = data["session_id"]
    resp = client.get(f"/api/sessions/{session_id}/cost-spread", params={"n_rollouts": 20})
    assert resp.status_code == 200
    spread = resp.json()
    assert spread["n_rollouts"] == 20
    assert 0 <= spread["n_samples"] <= 20
    assert 0.0 <= spread["success_rate"] <= 1.0
    if spread["n_samples"] > 0:
        assert spread["median_cost"] <= spread["p90_cost"] <= spread["worst_cost"]


def test_cost_spread_unknown_session_404(client):
    resp = client.get("/api/sessions/does-not-exist/cost-spread")
    assert resp.status_code == 404
