"""JSON (de)serialization for a solved policy, so `poe2craft solve` can write a
result that a later `poe2craft simulate --policy result.json` run can load
without re-solving."""
from __future__ import annotations

import json
from pathlib import Path

from poe2craft.domain.items import Rarity
from poe2craft.solver.featurize import AbstractState
from poe2craft.solver.value_iteration import SolveResult


def _state_key(s: AbstractState) -> str:
    return json.dumps(
        {"rarity": s.rarity.value, "prefix": s.prefix_count, "suffix": s.suffix_count, "status": list(s.status)},
        sort_keys=True,
    )


def _state_from_key(key: str) -> AbstractState:
    d = json.loads(key)
    return AbstractState(
        rarity=Rarity(d["rarity"]), prefix_count=d["prefix"], suffix_count=d["suffix"], status=tuple(d["status"])
    )


def save_policy(result: SolveResult, path: Path) -> None:
    payload = {
        "converged": result.converged,
        "iterations": result.iterations,
        "policy": {_state_key(s): action_id for s, action_id in result.policy.items()},
        "value": {_state_key(s): v for s, v in result.value.items()},
    }
    Path(path).write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load_policy(path: Path) -> SolveResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    policy = {_state_from_key(k): v for k, v in payload["policy"].items()}
    value = {_state_from_key(k): v for k, v in payload["value"].items()}
    return SolveResult(value=value, policy=policy, converged=payload["converged"], iterations=payload["iterations"])
