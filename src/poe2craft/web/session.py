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
from poe2craft.solver.model_learning import MDP
from poe2craft.solver.value_iteration import SolveResult

SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours of inactivity

MAX_HISTORY_ENTRIES = 50
"""Caps `Session.history` so a very long crafting session (many `advance`
calls) can't grow it unboundedly -- the oldest entry is dropped first, same
trade-off a normal in-game "undo" buffer makes."""


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """A snapshot of the state/item at a past point in the session, so
    `/undo` can restore exactly what the item looked like then. Deliberately
    doesn't try to resurrect the *banner* (`resolved_via`/`note`) that was
    shown at that point -- `/undo`'s own response always reports
    `resolved_via="undo"`, a clear enough signal on its own."""

    state: AbstractState
    item: Item


@dataclass
class Session:
    session_id: str
    target: ResolvedTarget
    actions: dict[str, object]
    result: SolveResult
    mdp: MDP
    current_state: AbstractState
    current_item: Item
    rng: random.Random
    n_trials: int
    history: list[HistoryEntry] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def push_history(self) -> None:
        """Snapshots the *current* state/item before the caller overwrites
        them -- called by `advance_session` right before mutating
        `current_state`/`current_item`, never after."""
        self.history.append(HistoryEntry(state=self.current_state, item=self.current_item))
        del self.history[:-MAX_HISTORY_ENTRIES]

    def pop_history(self) -> HistoryEntry | None:
        return self.history.pop() if self.history else None


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
        mdp: MDP,
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
            mdp=mdp,
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
