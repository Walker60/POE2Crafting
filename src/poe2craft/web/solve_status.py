"""Tracks in-progress solves (a `build_mdp` + `value_iteration` pair) so
`GET /api/solve-status` -- and `make solve-status` -- can answer "is
something actually running right now, and for how long" without watching a
browser spinner or guessing from CPU usage. A real solve can take anywhere
from a couple of seconds to a couple of minutes with no progress reporting
inside it, so this is deliberately coarse (started/still-running/how-long),
not a percentage-done estimate `build_mdp`'s lazy BFS has no way to give.

Same posture as `web.session.SessionStore`: one process-lifetime tracker on
`app.state`, one lock (not fine-grained), sized for a personal, single-user
tool where the realistic concurrency is "a second browser tab," not real
load."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends

from poe2craft.web.deps import get_solve_status_tracker
from poe2craft.web.schemas import InProgressSolveInfo, SolveStatusResponse

router = APIRouter(tags=["solve-status"])


@dataclass(frozen=True, slots=True)
class InProgressSolve:
    id: str
    kind: str  # "create_session" | "advance_session" | "trade_compare_restart"
    base_name: str
    objective: str
    n_trials: int
    started_at: float = field(default_factory=time.time)


class SolveStatusTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_progress: dict[str, InProgressSolve] = {}

    def start(self, kind: str, base_name: str, objective: str, n_trials: int) -> str:
        """Returns a token -- pass it to `finish` when the solve completes
        (successfully or not; callers should use `try/finally`)."""
        entry = InProgressSolve(id=str(uuid.uuid4()), kind=kind, base_name=base_name, objective=objective, n_trials=n_trials)
        with self._lock:
            self._in_progress[entry.id] = entry
        return entry.id

    def finish(self, token: str) -> None:
        with self._lock:
            self._in_progress.pop(token, None)

    def snapshot(self) -> list[InProgressSolve]:
        with self._lock:
            return list(self._in_progress.values())


@router.get("/api/solve-status", response_model=SolveStatusResponse)
def get_solve_status(tracker: SolveStatusTracker = Depends(get_solve_status_tracker)) -> SolveStatusResponse:
    now = time.time()
    return SolveStatusResponse(
        in_progress=[
            InProgressSolveInfo(
                kind=s.kind, base_name=s.base_name, objective=s.objective, n_trials=s.n_trials, running_for_seconds=now - s.started_at
            )
            for s in tracker.snapshot()
        ]
    )
