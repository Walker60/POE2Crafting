"""Tabular value iteration over a learned MDP: Q(s,a) = R(a) + gamma * sum_s'
P(s'|s,a) V(s'), V(s) = max_a Q(s,a), iterated to convergence. Infinite-horizon
discounted VI was chosen over finite-horizon backward induction (the project's
other documented option) because it produces one *stationary* policy (one best
action per state, independent of how many steps remain) -- matching both the
source article's presentation and what a CLI naturally wants to print, at the
cost of a discount factor that must be close enough to 1 to not distort a
"minimize expected steps/cost" objective in practice.

Dead-end states (no applicable action reaches anywhere, e.g. an item with no
further eligible mods) are given a large fixed negative value up front and
never touched by the recurrence, since they otherwise default to the same 0.0
as a goal state -- which would make neighboring states think stepping into a
dead end is free, silently corrupting their own values.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from poe2craft.solver.featurize import AbstractState
from poe2craft.solver.model_learning import MDP

DEAD_END_VALUE = -1_000_000.0


@dataclass
class SolveResult:
    value: dict[AbstractState, float]
    policy: dict[AbstractState, str]
    converged: bool
    iterations: int
    dead_ends: set[AbstractState] = field(default_factory=set)
    gamma: float = 0.999
    objective: str = "steps"
    """`gamma`/`objective` are the discount factor and reward mode this
    result was actually solved with -- stored (rather than left as
    call-and-forget locals) so a later on-demand Q-value recompute (see
    `q_value`/`q_values_at`, used for the web API's "alternative actions"
    view) reproduces the same numbers the original solve did, not a
    re-guessed default that could silently disagree."""

    def expected_value(self, state: AbstractState) -> float:
        return self.value.get(state, DEAD_END_VALUE)


def _reward(objective: str, action) -> float:
    return -1.0 if objective == "steps" else -action.cost()


def q_value(
    mdp: MDP, actions: dict[str, object], value: dict[AbstractState, float], objective: str, state: AbstractState, action_id: str, gamma: float
) -> float | None:
    """Q(state, action_id) under an already-converged value function -- the
    same formula `value_iteration`'s own loops use, but for a single
    (state, action) pair on demand (e.g. to list runner-up actions) rather
    than every state/action `value_iteration` itself needs every iteration.
    Deliberately a *separate* implementation from those loops rather than a
    shared call: they precompute `rewards` once per solve and call this
    formula every (state, action) pair on every iteration, so paying
    `action.cost()` again per call there (as this standalone version does)
    would reintroduce exactly the kind of per-call overhead this project's
    solver performance work eliminated. `None` when this action has no
    learned transition from `state` at all (never applicable there)."""
    dist = mdp.transitions.get((state, action_id))
    if not dist:
        return None
    reward = _reward(objective, actions[action_id])
    return reward + gamma * sum(p * value.get(s2, DEAD_END_VALUE) for s2, p in dist.items())


def q_values_at(mdp: MDP, actions: dict[str, object], result: SolveResult, state: AbstractState) -> dict[str, float]:
    """Every action's Q-value at `state`, for actions with a learned
    transition from it -- the "what are my options and how good is each"
    view behind the web API's alternative-actions endpoint."""
    out: dict[str, float] = {}
    for action_id in actions:
        q = q_value(mdp, actions, result.value, result.objective, state, action_id, result.gamma)
        if q is not None:
            out[action_id] = q
    return out


def value_iteration(
    mdp: MDP,
    actions: dict[str, object],
    objective: str = "steps",
    gamma: float = 0.999,
    tol: float = 1e-4,
    max_iterations: int = 10_000,
) -> SolveResult:
    dead_ends = {
        s
        for s in mdp.states
        if s not in mdp.goal_states and not any((s, aid) in mdp.transitions for aid in actions)
    }
    value: dict[AbstractState, float] = {
        s: (0.0 if s in mdp.goal_states else DEAD_END_VALUE if s in dead_ends else 0.0) for s in mdp.states
    }
    rewards = {aid: _reward(objective, a) for aid, a in actions.items()}

    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        delta = 0.0
        new_value = dict(value)
        for s in mdp.states:
            if s in mdp.goal_states or s in dead_ends:
                continue
            best_q = None
            for action_id in actions:
                dist = mdp.transitions.get((s, action_id))
                if not dist:
                    continue
                q = rewards[action_id] + gamma * sum(p * value[s2] for s2, p in dist.items())
                if best_q is None or q > best_q:
                    best_q = q
            new_value[s] = best_q if best_q is not None else value[s]
            delta = max(delta, abs(new_value[s] - value[s]))
        value = new_value
        if delta < tol:
            converged = True
            break

    if not converged:
        warnings.warn(
            f"value iteration did not converge after {iterations} iterations (final delta unknown-bounded by tol={tol}); "
            "policy may be inaccurate -- consider raising max_iterations or lowering gamma",
            stacklevel=2,
        )

    policy: dict[AbstractState, str] = {}
    for s in mdp.states:
        if s in mdp.goal_states or s in dead_ends:
            continue
        best_action, best_q = None, None
        for action_id in actions:
            dist = mdp.transitions.get((s, action_id))
            if not dist:
                continue
            q = rewards[action_id] + gamma * sum(p * value[s2] for s2, p in dist.items())
            if best_q is None or q > best_q:
                best_q, best_action = q, action_id
        if best_action is not None:
            policy[s] = best_action

    return SolveResult(
        value=value, policy=policy, converged=converged, iterations=iterations, dead_ends=dead_ends, gamma=gamma, objective=objective
    )
