"""Human-readable rendering of states, targets, and solve results."""
from __future__ import annotations

from poe2craft.data.loader import GameData
from poe2craft.solver.featurize import AbstractState, ResolvedTarget
from poe2craft.solver.value_iteration import SolveResult


def format_state(state: AbstractState) -> str:
    # Each digit is a target mod's status: 0 absent, 1 present-but-below-tier
    # (only ever appears for a target with a min_ilvl requirement), 2 satisfied.
    bits = "".join(str(s) for s in state.status)
    return f"[{state.rarity.value.title()}|{bits}|{state.prefix_count}p|{state.suffix_count}s]"


def format_target(target: ResolvedTarget, gamedata: GameData) -> str:
    base_name = gamedata.bases[target.base_id].name
    lines = [f"Base: {base_name} (ilvl {target.ilvl})", "Target mods:"]
    for i, req in enumerate(target.target_mods):
        name = gamedata.mods[req.mod_id].name
        tier_note = f" (min ilvl {req.min_ilvl})" if req.min_ilvl else ""
        lines.append(f"  [{i}] {name}{tier_note}")
    lines.append(f"Objective: minimize {target.objective}")
    return "\n".join(lines)


def format_solve_summary(
    result: SolveResult, target: ResolvedTarget, start: AbstractState, actions: dict[str, object]
) -> str:
    lines = []
    lines.append(f"Converged: {result.converged} ({result.iterations} iterations)")
    lines.append(f"States explored: {len(result.value)} (dead ends: {len(result.dead_ends)})")
    ev = result.expected_value(start)
    unit = "steps" if target.objective == "steps" else "cost"
    lines.append(f"Start state: {format_state(start)}")
    lines.append(f"Expected {unit} to reach target: {-ev:.2f}")
    action_id = result.policy.get(start)
    if action_id is None:
        lines.append("No known path to the target from the start state (unreachable, or start already at goal).")
    else:
        lines.append(f"Recommended next action: {actions[action_id].name}")
    return "\n".join(lines)


def format_trajectory(steps: list[tuple[AbstractState, str | None]], success: bool, actions: dict[str, object] | None = None) -> str:
    lines = []
    for state, action_id in steps:
        if action_id is None:
            action_label = "(goal / no action)"
        elif actions is not None and action_id in actions:
            action_label = actions[action_id].name
        else:
            action_label = action_id
        lines.append(f"  {format_state(state)} -> {action_label}")
    lines.append("SUCCESS" if success else "DID NOT REACH TARGET within max_steps")
    return "\n".join(lines)
