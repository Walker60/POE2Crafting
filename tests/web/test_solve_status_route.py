"""GET /api/solve-status against the real (non-overridden) SolveStatusTracker
wiring -- manipulates app.state.solve_status directly rather than racing a
real concurrent solve, since the tracker's own start/finish/snapshot logic
is already covered in isolation by tests/unit/test_solve_status.py; this
just proves the route serializes that state correctly end to end."""
import time


def test_solve_status_empty_when_nothing_running(client):
    resp = client.get("/api/solve-status")
    assert resp.status_code == 200
    assert resp.json() == {"in_progress": []}


def test_solve_status_reports_an_in_progress_entry(app, client):
    tracker = app.state.solve_status
    token = tracker.start("create_session", "Test Base", "cost", 500)
    try:
        time.sleep(0.05)
        resp = client.get("/api/solve-status")
        body = resp.json()
        assert len(body["in_progress"]) == 1
        entry = body["in_progress"][0]
        assert entry["kind"] == "create_session"
        assert entry["base_name"] == "Test Base"
        assert entry["objective"] == "cost"
        assert entry["n_trials"] == 500
        assert entry["running_for_seconds"] > 0
    finally:
        tracker.finish(token)

    assert client.get("/api/solve-status").json() == {"in_progress": []}
