"""Learns an empirical transition model P(s'|s,a) by Monte Carlo sampling, then
lazily explores the reachable abstract-state graph via BFS from a start state
-- never by enumerating the full combinatorial state space upfront, which is
what keeps a pure-Python implementation tractable in practice.

Applicability is checked per concretized trial rather than assumed to be a
pure function of the abstract state: most actions' applicability *is*
state-determined (rarity, counts), but a couple (Augmentation, Exalted without
a restriction) also depend on whether anything is eligible given the concrete
item's occupied groups, which can -- vanishingly rarely -- vary across
different fresh fillers for the same abstract state. Trials where an action
turns out inapplicable are simply excluded from that action's estimate rather
than aborting it, so a nearly-always-blocked action naturally comes out with a
near-empty (or empty) transition distribution instead of a crash.
"""
from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from poe2craft.data.loader import GameData
from poe2craft.domain.actions import ActionKind
from poe2craft.domain.ids import BaseId
from poe2craft.solver.featurize import AbstractState, ResolvedTarget, abstractify, concretize, pick_best_candidate

if TYPE_CHECKING:
    from concurrent.futures import ProcessPoolExecutor


@dataclass
class MDP:
    start: AbstractState
    states: set[AbstractState]
    goal_states: set[AbstractState]
    # (state, action_id) -> {state2: probability}. Missing key means "not
    # applicable from this state" (excluded from the action space there).
    transitions: dict[tuple[AbstractState, str], dict[AbstractState, float]] = field(default_factory=dict)


_INAPPLICABLE_PILOT = 30
"""When none of the first `_INAPPLICABLE_PILOT` trials find `action` applicable,
`estimate_transition` stops early rather than burning the rest of `n_trials`
confirming the same thing. Sound for the common case -- most actions' real
game applicability is a pure function of the abstract state (rarity/counts),
so if it's inapplicable once, it's inapplicable for every concretization of
that state, and the pilot only pays a fixed, small cost to discover that. A
few actions' applicability can, rarely, depend on which specific filler mods
a concretization happened to roll (see the module docstring) -- for those,
this is a genuine, deliberate approximation: a true positive would need to be
missed by all 30 pilot draws in a row to be lost, which is only plausible if
its real hit rate is itself tiny, at which point its contribution to the
transition estimate would have been marginal anyway. This trades a small,
bounded amount of estimator accuracy in an already-approximate Monte Carlo
model for a large cut in wasted work on the (typically far more common)
actions that are structurally inapplicable in a given state."""

_ABSTRACTION_DETERMINISTIC_KINDS = frozenset({ActionKind.DIVINE, ActionKind.FRACTURE, ActionKind.ESSENCE})
"""Action kinds whose outcome, once applicable at all, is *always* the same
`AbstractState` -- not an approximation, a proof: `AbstractState`
(`solver.featurize`) never tracks which specific mods are present or any
`fractured` flag, and none of these three ever change mod identity/tier/
counts/rarity (Divine only rerolls numeric values; Fracture only flips a
`fractured` flag `abstractify` never reads; a non-Perfect essence's grants
are a fixed list at fixed tiers -- `ActionKind.ESSENCE`, not
`PERFECT_ESSENCE`, which *does* have a genuinely random removal step and is
deliberately excluded here). So `estimate_transition` below stops sampling
one of these the instant it's confirmed applicable once: every further
applicable trial would just re-derive the identical single outcome, making
`{result: attempted/attempted} == {result: 1.0}` regardless of `attempted`
-- the early exit changes how many trials it takes to get that answer, never
the answer itself. See docs/design_notes.md for the measured effect."""


def estimate_transition(
    gamedata: GameData,
    target: ResolvedTarget,
    state: AbstractState,
    action,
    rng: random.Random,
    n_trials: int,
) -> dict[AbstractState, float]:
    counts: Counter[AbstractState] = Counter()
    attempted = 0
    pilot = min(n_trials, _INAPPLICABLE_PILOT)
    deterministic = getattr(action, "kind", None) in _ABSTRACTION_DETERMINISTIC_KINDS
    for i in range(n_trials):
        item = concretize(gamedata, target, state, rng)
        if action.applicable(item):
            attempted += 1
            if hasattr(action, "reveal_candidates"):
                result = pick_best_candidate(target, state, action.reveal_candidates(item, rng), rng)
            else:
                result = action.outcome(item, rng)
            counts[abstractify(target, result)] += 1
            if deterministic:
                break
        elif i + 1 == pilot and attempted == 0 and pilot < n_trials:
            return {}
    if attempted == 0:
        return {}
    return {s2: c / attempted for s2, c in counts.items()}


def build_mdp(
    gamedata: GameData,
    target: ResolvedTarget,
    start: AbstractState,
    actions: dict[str, object],
    rng: random.Random,
    n_trials: int = 2000,
    executor: ProcessPoolExecutor | None = None,
    base_id: BaseId | None = None,
) -> MDP:
    """`executor`, when given (with `base_id`), runs the Monte Carlo
    estimation across worker processes instead of sequentially -- see
    `solver.parallel.build_mdp_parallel` (imported lazily here to avoid a
    circular import, since that module itself imports `estimate_transition`
    from this one). Every existing caller (the CLI, every test) leaves this
    `None` and gets this function's original, unchanged sequential behaviour;
    only `web.crafting`'s session endpoints opt in."""
    if executor is not None:
        from poe2craft.solver.parallel import build_mdp_parallel

        assert base_id is not None, "build_mdp(executor=...) requires base_id"
        return build_mdp_parallel(gamedata, target, start, actions, rng, n_trials, executor, base_id)

    frontier: deque[AbstractState] = deque([start])
    visited: set[AbstractState] = {start}
    goal_states: set[AbstractState] = set()
    transitions: dict[tuple[AbstractState, str], dict[AbstractState, float]] = {}

    # Memoize per (state, action_id) within this build -- the minimum viable
    # "don't resample the same pair twice" cache. A more aggressive afterstate
    # cache (keyed by the action's *real* dependency, e.g. base+ilvl for
    # essence-guaranteed outcomes, reusable across target specs entirely) is a
    # documented future optimization, not required for correctness here.
    cache: dict[tuple[AbstractState, str], dict[AbstractState, float]] = {}

    while frontier:
        s = frontier.popleft()
        if s.is_goal():
            goal_states.add(s)
            continue
        for action_id, action in actions.items():
            key = (s, action_id)
            if key not in cache:
                cache[key] = estimate_transition(gamedata, target, s, action, rng, n_trials)
            dist = cache[key]
            if not dist:
                continue
            transitions[key] = dist
            for s2 in dist:
                if s2 not in visited:
                    visited.add(s2)
                    frontier.append(s2)

    return MDP(start=start, states=visited, goal_states=goal_states, transitions=transitions)
