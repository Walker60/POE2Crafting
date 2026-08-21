"""SolveStatusTracker's start/finish/snapshot bookkeeping in isolation --
see web/solve_status.py's module docstring for what this is (and isn't:
no percent-done, just "is one running and for how long")."""
from poe2craft.web.solve_status import SolveStatusTracker


def test_snapshot_is_empty_when_nothing_started():
    tracker = SolveStatusTracker()
    assert tracker.snapshot() == []


def test_start_then_snapshot_shows_the_entry():
    tracker = SolveStatusTracker()
    tracker.start("create_session", "Amulet", "cost", 500)
    snap = tracker.snapshot()
    assert len(snap) == 1
    assert snap[0].kind == "create_session"
    assert snap[0].base_name == "Amulet"
    assert snap[0].objective == "cost"
    assert snap[0].n_trials == 500


def test_finish_removes_the_entry():
    tracker = SolveStatusTracker()
    token = tracker.start("create_session", "Amulet", "cost", 500)
    tracker.finish(token)
    assert tracker.snapshot() == []


def test_finish_on_an_unknown_token_is_a_safe_no_op():
    tracker = SolveStatusTracker()
    tracker.finish("does-not-exist")  # no raise


def test_multiple_concurrent_entries_are_tracked_independently():
    tracker = SolveStatusTracker()
    t1 = tracker.start("create_session", "Amulet", "cost", 500)
    t2 = tracker.start("advance_session", "One Hand Sword", "steps", 300)
    assert {s.kind for s in tracker.snapshot()} == {"create_session", "advance_session"}

    tracker.finish(t1)
    remaining = tracker.snapshot()
    assert len(remaining) == 1
    assert remaining[0].kind == "advance_session"

    tracker.finish(t2)
    assert tracker.snapshot() == []
