"""GET /alternatives, POST /undo, GET /preview/{action_id} -- against the
same hand-built gamedata fixture as tests/web/test_api.py (base1 with p1/p2/
p3 prefixes, s1/s2/s3 suffixes, all weight 100 except hi_ilvl)."""


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


def test_alternatives_unknown_session_404(client):
    assert client.get("/api/sessions/does-not-exist/alternatives").status_code == 404


def test_alternatives_includes_the_recommended_action_flagged(client):
    data = _setup(client)
    session_id = data["session_id"]
    recommended_id = data["recommended_action"]["action_id"]

    resp = client.get(f"/api/sessions/{session_id}/alternatives", params={"top_n": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alternatives"]
    assert body["unit"] == "steps"

    flagged = [a for a in body["alternatives"] if a["is_recommended"]]
    assert len(flagged) == 1
    assert flagged[0]["action_id"] == recommended_id
    # Sorted descending by expected_total (fewer steps left is better for "steps").
    totals = [a["expected_total"] for a in body["alternatives"]]
    assert totals == sorted(totals)


def test_alternatives_respects_top_n(client):
    data = _setup(client)
    session_id = data["session_id"]
    resp = client.get(f"/api/sessions/{session_id}/alternatives", params={"top_n": 1})
    assert len(resp.json()["alternatives"]) == 1


def test_undo_without_any_history_is_409(client):
    data = _setup(client)
    session_id = data["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/undo")
    assert resp.status_code == 409


def test_undo_restores_the_prior_reported_state(client):
    data = _setup(client)
    session_id = data["session_id"]
    assert data["can_undo"] is False

    advanced = client.post(
        f"/api/sessions/{session_id}/advance",
        json={"rarity": "rare", "current_mods": [{"mod_id": "p1", "tier_ilvl": 1}]},
    ).json()
    assert advanced["is_goal"] is True
    assert advanced["can_undo"] is True

    undone = client.post(f"/api/sessions/{session_id}/undo").json()
    assert undone["resolved_via"] == "undo"
    assert undone["is_goal"] is False  # back to the pre-advance (Normal, no mods) state
    assert undone["can_undo"] is False  # that was the only history entry


def test_undo_unknown_session_404(client):
    assert client.post("/api/sessions/does-not-exist/undo").status_code == 404


def test_preview_unknown_session_404(client):
    assert client.get("/api/sessions/does-not-exist/preview/transmutation").status_code == 404


def test_preview_unknown_action_404(client):
    data = _setup(client)
    resp = client.get(f"/api/sessions/{data['session_id']}/preview/does-not-exist")
    assert resp.status_code == 404


def test_preview_available_for_transmutation(client):
    data = _setup(client)  # Normal-rarity start item
    resp = client.get(f"/api/sessions/{data['session_id']}/preview/transmutation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["guaranteed"] == []
    assert body["entries"]
    assert abs(sum(e["probability"] for e in body["entries"]) - 1.0) < 1e-9


def test_preview_unavailable_for_annulment(client):
    data = _setup(client)
    resp = client.get(f"/api/sessions/{data['session_id']}/preview/annulment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["entries"] == []
    assert body["guaranteed"] == []
    assert body["unavailable_reason"]
