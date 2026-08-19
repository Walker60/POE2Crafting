"""Optional process-pool parallelism for `solver.model_learning.build_mdp`.

Different `(state, action)` pairs in the BFS are fully independent Monte Carlo
estimations -- no shared mutable state, just the same read-only `GameData` and
`ResolvedTarget`. That makes them a natural fit for `ProcessPoolExecutor`
(threads wouldn't help: the hot loop is pure-Python object construction and
dict/list operations, none of which release the GIL).

Deliberately imports only `data.loader`, `domain.ids`, `engine.omens`, and
`solver.featurize`/`solver.model_learning` -- never `web.app` or `cli.main`.
Those two modules run side-effecting code at import time (`web.app` builds a
whole FastAPI app + loads gamedata at module scope; `cli.main` is the actual
process entry point), and a spawned worker process re-imports whatever module
this file lives in -- keeping the import graph narrow means a worker never
has a reason to trigger either of those as a side effect of bootstrapping.

Windows only supports the 'spawn' multiprocessing start method (never
'fork'), which matters here in one specific way: a spawned worker
re-executes the *parent's* `__main__` file (with `run_name="__mp_main__"`,
not `"__main__"`, so an `if __name__ == "__main__":`-guarded block correctly
does not re-run) before importing this module. The installed `poe2craft.exe`
launcher was confirmed (by reading its embedded `__main__.py` directly via
`zipfile`, since these launchers are a native stub with an appended zip
archive) to have exactly that guard, so this is safe through the real
installed entry point -- see `self_test_pool`/the `poe2craft doctor` command
for a standing, re-runnable confirmation of that rather than a one-time check.
"""
from __future__ import annotations

import multiprocessing
import os
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseId
from poe2craft.engine.omens import all_actions
from poe2craft.solver.featurize import AbstractState, ResolvedTarget
from poe2craft.solver.model_learning import MDP, estimate_transition

# Set once per worker process by `_init_worker` -- never mutated after that,
# so no locking is needed despite being module-global (each worker is its own
# process with its own copy, not shared memory).
_worker_gamedata: GameData | None = None
_worker_actions_cache: dict[BaseId, dict[str, object]] = {}


def _init_worker(gamedata: GameData) -> None:
    global _worker_gamedata
    _worker_gamedata = gamedata


def _worker_actions(base_id: BaseId) -> dict[str, object]:
    """Lazily builds and caches this worker's own local action registry --
    rebuilt from the worker's own `GameData` copy rather than ever pickling
    Action objects across the process boundary (they each hold a reference to
    the whole GameData, which would mean re-pickling it per task instead of
    once per worker at pool startup)."""
    actions = _worker_actions_cache.get(base_id)
    if actions is None:
        assert _worker_gamedata is not None, "_worker_actions called before _init_worker"
        actions = all_actions(_worker_gamedata, base_id=base_id)
        _worker_actions_cache[base_id] = actions
    return actions


@dataclass(frozen=True, slots=True)
class TransitionTask:
    """Everything one worker needs for one (state, action) Monte Carlo
    estimate -- deliberately small and cheap to pickle (no GameData, no
    Action objects; those live worker-side, see `_worker_actions`)."""

    state: AbstractState
    action_id: str
    base_id: BaseId
    target: ResolvedTarget
    n_trials: int
    seed: int


def run_transition_task(task: TransitionTask) -> tuple[AbstractState, str, dict[AbstractState, float]]:
    assert _worker_gamedata is not None, "run_transition_task called before _init_worker"
    action = _worker_actions(task.base_id)[task.action_id]
    rng = random.Random(task.seed)
    dist = estimate_transition(_worker_gamedata, task.target, task.state, action, rng, task.n_trials)
    return task.state, task.action_id, dist


def make_executor(gamedata: GameData, max_workers: int) -> ProcessPoolExecutor:
    """`mp_context=` is set explicitly to 'spawn' rather than relying on the
    platform default -- Windows already defaults to spawn, so this changes
    nothing there, but it means this code exercises the same (stricter) spawn
    hazard profile if it's ever run on Linux dev machines or CI too, instead
    of silently getting fork's more forgiving semantics. It also avoids ever
    calling the process-global `multiprocessing.set_start_method`, which
    raises if called more than once per process (e.g. `create_app()` invoked
    repeatedly, as tests do)."""
    ctx = multiprocessing.get_context("spawn")
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx, initializer=_init_worker, initargs=(gamedata,))


def _pid_task(_: int) -> int:
    return os.getpid()


def health_check(executor: ProcessPoolExecutor, timeout: float = 30.0) -> bool:
    """One trivial round-trip through the real pool -- run right after
    creating it in `web.app.create_app`, so a bad environment (e.g. an AV
    product blocking child process creation) degrades to sequential solving
    instead of every subsequent request hanging on a broken pool. Never
    raises -- any failure just means "don't trust this pool"."""
    try:
        executor.submit(_pid_task, 0).result(timeout=timeout)
        return True
    except Exception:
        return False


def self_test_pool(max_workers: int = 4, n_tasks: int = 20) -> tuple[bool, set[int]]:
    """Standalone spawn-safety check, independent of any real `GameData` --
    the thing the `poe2craft doctor` CLI command runs, since that's the only
    way to exercise this through the *real* installed entry point (not
    pytest's own process, which is never what actually launches workers in
    production). Submits more tasks than workers and confirms the distinct
    worker PID count is bounded by `max_workers`, not runaway."""
    try:
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as executor:
            pids = set(executor.map(_pid_task, range(n_tasks)))
        return len(pids) <= max_workers, pids
    except Exception:
        return False, set()


def build_mdp_parallel(
    gamedata: GameData,
    target: ResolvedTarget,
    start: AbstractState,
    actions: dict[str, object],
    rng: random.Random,
    n_trials: int,
    executor: ProcessPoolExecutor,
    base_id: BaseId,
) -> MDP:
    """`model_learning.build_mdp`'s parallel path -- lives here (not in
    model_learning.py) purely to avoid a circular import, since this module
    imports `estimate_transition` from there; `build_mdp` imports this
    function lazily, inside the branch where it's actually needed.

    Processes the BFS wave-by-wave: this shape isn't a style choice, it's
    unavoidable, since wave k+1's tasks are literally defined by wave k's
    Monte Carlo results. Goal states are short-circuited *before* generating
    any tasks for them (matching the sequential path) -- generating and
    caching transitions out of a goal state would silently corrupt
    `value_iteration`'s absorbing-state assumption. Results are gathered in
    submission order (not `as_completed`), so a fixed top-level seed still
    gives reproducible results run-to-run, matching the CLI's documented
    `--seed` promise, even though the exact RNG draw sequence necessarily
    differs from the sequential path (already true, and already within the
    tolerance every existing test uses, after this session's earlier
    inapplicable-action pilot optimization)."""
    expected_ids = set(all_actions(gamedata, base_id=base_id))
    if set(actions) != expected_ids:
        raise ValueError(
            "build_mdp(executor=...) requires `actions` to be exactly "
            f"all_actions(gamedata, base_id={base_id!r}) -- got a mismatched action set, which "
            "would make workers silently compute transitions for the wrong action registry"
        )

    frontier: list[AbstractState] = [start]
    visited: set[AbstractState] = {start}
    goal_states: set[AbstractState] = set()
    transitions: dict[tuple[AbstractState, str], dict[AbstractState, float]] = {}

    while frontier:
        non_goal: list[AbstractState] = []
        for s in frontier:
            if s.is_goal():
                goal_states.add(s)
            else:
                non_goal.append(s)

        tasks = [
            TransitionTask(
                state=s, action_id=action_id, base_id=base_id, target=target, n_trials=n_trials, seed=rng.getrandbits(63)
            )
            for s in non_goal
            for action_id in actions
        ]
        futures = [executor.submit(run_transition_task, t) for t in tasks]
        results = [f.result() for f in futures]

        next_frontier: list[AbstractState] = []
        for s, action_id, dist in results:
            if not dist:
                continue
            transitions[(s, action_id)] = dist
            for s2 in dist:
                if s2 not in visited:
                    visited.add(s2)
                    next_frontier.append(s2)
        frontier = next_frontier

    return MDP(start=start, states=visited, goal_states=goal_states, transitions=transitions)
