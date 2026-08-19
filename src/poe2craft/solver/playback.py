"""Replays a solved policy against the *real* sampler (concrete Items, not the
abstract model) to produce worked examples and to sanity-check the abstract
model's predicted reach-probability against actual empirical outcomes -- the
end-to-end check the project plan calls for, since a wrong sampler or a wrong
abstraction could otherwise silently produce a self-consistent but wrong
solver.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from poe2craft.data.loader import GameData
from poe2craft.domain.items import Item
from poe2craft.solver.featurize import AbstractState, ResolvedTarget, abstractify


@dataclass
class TrajectoryResult:
    steps: list[tuple[AbstractState, str | None]]
    success: bool
    step_count: int
    total_cost: float


def run_trajectory(
    gamedata: GameData,
    target: ResolvedTarget,
    actions: dict[str, object],
    policy: dict[AbstractState, str],
    start_item: Item,
    rng: random.Random,
    max_steps: int,
) -> TrajectoryResult:
    item = start_item
    steps: list[tuple[AbstractState, str | None]] = []
    total_cost = 0.0
    for step_count in range(max_steps):
        state = abstractify(target, item)
        if state.is_goal():
            steps.append((state, None))
            return TrajectoryResult(steps=steps, success=True, step_count=step_count, total_cost=total_cost)
        action_id = policy.get(state)
        steps.append((state, action_id))
        if action_id is None:
            break  # no known action from here -- policy has no route out of this state
        action = actions[action_id]
        if not action.applicable(item):
            break  # policy/engine disagreement on applicability -- stop rather than loop forever
        total_cost += action.cost()
        item = action.outcome(item, rng)
    final_state = abstractify(target, item)
    success = final_state.is_goal()
    if success:
        steps.append((final_state, None))
    return TrajectoryResult(steps=steps, success=success, step_count=len(steps), total_cost=total_cost)
