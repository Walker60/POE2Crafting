"""In-memory crafting sessions: a solve is expensive (Monte Carlo BFS + value
iteration), but `build_mdp`'s BFS covers every state reachable from the start
via the modeled action set, not just the literal start -- so once solved, the
whole interactive "report new state" loop is normally just a fast dict lookup
against the same `SolveResult`, not a re-solve per step. See
docs/design_notes.md (once written) for the fallback when a reported state
isn't in that reachable set.

A single global lock, not per-session locks: for a personal, single-user tool
this exists to protect against a double-click or a duplicate browser tab
racing on the *same* session, not real concurrent load. `GameData` itself is
frozen/read-only and shared across all sessions without any locking."""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field

from poe2craft.domain.items import Item
from poe2craft.solver.featurize import AbstractState, ResolvedTarget
from poe2craft.solver.value_iteration import SolveResult

SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours of inactivity


@dataclass
class Session:
    session_id: str
    target: ResolvedTarget
    actions: dict[str, object]
    result: SolveResult
    current_state: AbstractState
    current_item: Item
    rng: random.Random
    n_trials: int
    history: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


class SessionStore:
    """No persistence across process restarts -- acceptable for a personal,
    single-user, no-DB tool (see the plan this was built from)."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self,
        target: ResolvedTarget,
        actions: dict[str, object],
        result: SolveResult,
        current_state: AbstractState,
        current_item: Item,
        rng: random.Random,
        n_trials: int,
    ) -> Session:
        session = Session(
            session_id=str(uuid.uuid4()),
            target=target,
            actions=actions,
            result=result,
            current_state=current_state,
            current_item=current_item,
            rng=rng,
            n_trials=n_trials,
        )
        with self._lock:
            self._evict_expired_locked()
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            self._evict_expired_locked()
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_used_at = time.time()
            return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def _evict_expired_locked(self) -> None:
        """Caller must already hold `self._lock` -- `threading.Lock` isn't
        reentrant, so this never acquires it itself."""
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_used_at > SESSION_TTL_SECONDS]
        for sid in expired:
            del self._sessions[sid]
