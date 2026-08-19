"""Loads a user-authored YAML target spec into the validated pydantic
`TargetSpec`, then resolves it against a loaded GameData into the solver's
`ResolvedTarget` + starting `AbstractState`."""
from __future__ import annotations

from pathlib import Path

import yaml

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetSpec
from poe2craft.domain.ids import ModId
from poe2craft.domain.items import Rarity
from poe2craft.solver.featurize import AbstractState, ResolvedTarget, resolve_target, start_state


def load_target_spec(path: Path) -> TargetSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return TargetSpec.model_validate(raw)


def resolve(gamedata: GameData, spec: TargetSpec) -> tuple[ResolvedTarget, AbstractState]:
    target = resolve_target(gamedata, spec)
    start_mod_ids = frozenset(ModId(m) for m in spec.start_mod_ids)
    state0 = start_state(gamedata, target, Rarity(spec.start_rarity), start_mod_ids)
    return target, state0
