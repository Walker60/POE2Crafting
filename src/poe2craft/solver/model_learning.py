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

from poe2craft.data.loader import GameData
from poe2craft.solver.featurize import AbstractState, ResolvedTarget, abstractify, concretize


@dataclass
class MDP:
    start: AbstractState
    states: set[AbstractState]
    goal_states: set[AbstractState]
    # (state, action_id) -> {state2: probability}. Missing key means "not
    # applicable from this state" (excluded from the action space there).
    transitions: dict[tuple[AbstractState, str], dict[AbstractState, float]] = field(default_factory=dict)


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
    for _ in range(n_trials):
        item = concretize(gamedata, target, state, rng)
        if not action.applicable(item):
            continue
        attempted += 1
        result = action.outcome(item, rng)
        counts[abstractify(target, result)] += 1
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
) -> MDP:
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
