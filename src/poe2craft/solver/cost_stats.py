"""Aggregates repeated policy rollouts into a cost-to-finish *distribution*.
`SolveResult.expected_value` already gives a single average over the abstract
model; this replays the real sampler the same way `playback.run_trajectory`
does for its worked-example role, many times from the same concrete item, and
reports percentiles instead of one number -- "average / median / budget
(9-in-10) / worst-case", the numbers craftgaz's advisor shows under "Cost to
finish from here"."""
from __future__ import annotations

import random
from dataclasses import dataclass

from poe2craft.data.loader import GameData
from poe2craft.domain.items import Item
from poe2craft.solver.featurize import AbstractState, ResolvedTarget
from poe2craft.solver.playback import run_trajectory


@dataclass(frozen=True, slots=True)
class CostSpread:
    n_rollouts: int
    n_samples: int  # successful rollouts only -- cost-to-finish is conditional on finishing
    success_rate: float
    mean: float
    median: float
    p90: float  # "9 in 10 finish within this much"
    worst: float


def _nearest_rank(sorted_values: list[float], fraction: float) -> float:
    idx = min(len(sorted_values) - 1, int(fraction * len(sorted_values)))
    return sorted_values[idx]


def estimate_cost_spread(
    gamedata: GameData,
    target: ResolvedTarget,
    actions: dict[str, object],
    policy: dict[AbstractState, str],
    start_item: Item,
    rng: random.Random,
    n_rollouts: int = 300,
    max_steps: int | None = None,
) -> CostSpread:
    """Rolls out `policy` from `start_item` `n_rollouts` times (each call gets
    fresh random draws from the shared `rng`; `run_trajectory` never mutates
    `start_item` itself, so replaying from the same one every time is safe and
    correctly reflects that item's real filler mods/occupied groups)."""
    if n_rollouts <= 0:
        return CostSpread(n_rollouts=0, n_samples=0, success_rate=0.0, mean=0.0, median=0.0, p90=0.0, worst=0.0)

    steps_cap = max_steps if max_steps is not None else target.max_steps
    costs: list[float] = []
    successes = 0
    for _ in range(n_rollouts):
        traj = run_trajectory(gamedata, target, actions, policy, start_item, rng, steps_cap)
        if traj.success:
            successes += 1
            costs.append(traj.total_cost)

    success_rate = successes / n_rollouts
    if not costs:
        return CostSpread(n_rollouts=n_rollouts, n_samples=0, success_rate=success_rate, mean=0.0, median=0.0, p90=0.0, worst=0.0)

    costs.sort()
    return CostSpread(
        n_rollouts=n_rollouts,
        n_samples=len(costs),
        success_rate=success_rate,
        mean=sum(costs) / len(costs),
        median=_nearest_rank(costs, 0.5),
        p90=_nearest_rank(costs, 0.9),
        worst=costs[-1],
    )
