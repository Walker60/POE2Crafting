"""`solver.cost_stats.estimate_cost_spread` against the real compiled
gamedata, reusing the same essence-exclusive-mod scenario as
`test_end_to_end.py::test_essence_exclusive_mod_solves_in_exactly_two_deterministic_steps`
(Alchemy then a guaranteed essence, exactly 2 deterministic steps, 100% reach
probability) -- real action costs, but a fully deterministic outcome, so this
is exactly the case to check the aggregation logic itself rather than solver
plausibility (already covered by test_end_to_end.py)."""
import random

import pytest

from poe2craft.data.loader import load_gamedata
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.engine.omens import all_actions
from poe2craft.solver.cost_stats import estimate_cost_spread
from poe2craft.solver.featurize import concretize, resolve_target, start_state
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.value_iteration import value_iteration


@pytest.fixture(scope="module")
def gamedata():
    return load_gamedata()


def test_deterministic_two_step_craft_has_a_degenerate_zero_spread(gamedata):
    mod_id = ModId("5698")  # "#% increased maximum Life" -- essence-only, Perfect Essence of the Body grants it
    base_id = BaseId("45")  # Body Armour (STR)

    spec = TargetSpec(base="Body Armour (STR)", ilvl=80, target_mods=[TargetModSpec(mod_id=str(mod_id))], objective="cost", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata, base_id=base_id)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(3)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=200)
    result = value_iteration(mdp, actions, objective="cost")
    assert result.converged

    start_item = concretize(gamedata, target, s0, rng)
    spread = estimate_cost_spread(gamedata, target, actions, result.policy, start_item, rng, n_rollouts=30)

    assert spread.n_rollouts == 30
    assert spread.n_samples == 30
    assert spread.success_rate == 1.0
    # Every rollout takes the same 2 deterministic actions (Alchemy, then the
    # guaranteed essence) -- action cost doesn't depend on the RNG draw, so
    # the whole distribution should collapse to one value.
    assert spread.mean == pytest.approx(spread.median)
    assert spread.median == pytest.approx(spread.p90)
    assert spread.p90 == pytest.approx(spread.worst)
    assert spread.mean > 0.0


def test_percentiles_are_monotonic_on_a_noisier_target(gamedata):
    base = next(b for b in gamedata.bases.values() if b.name == "Amulet")
    eligible = gamedata.eligible_mods_for_base(base.id)
    mod_id = next(mid for mid, tiers in eligible.items() if gamedata.mods[mid].affix.value == "suffix" and any(t.ilvl <= 70 for t in tiers))

    spec = TargetSpec(base="Amulet", ilvl=70, target_mods=[TargetModSpec(mod_id=str(mod_id))], objective="cost", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(11)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=200)
    result = value_iteration(mdp, actions, objective="cost")
    assert result.converged

    start_item = concretize(gamedata, target, s0, rng)
    spread = estimate_cost_spread(gamedata, target, actions, result.policy, start_item, rng, n_rollouts=200)

    assert spread.success_rate > 0.5  # a real single-mod target should mostly succeed within 30 steps
    assert spread.median <= spread.p90 <= spread.worst
    assert spread.mean > 0.0


def test_n_rollouts_zero_is_a_safe_no_op(gamedata):
    base_id = BaseId("45")
    mod_id = ModId("5698")
    spec = TargetSpec(base="Body Armour (STR)", ilvl=80, target_mods=[TargetModSpec(mod_id=str(mod_id))], objective="cost", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata, base_id=base_id)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())
    rng = random.Random(3)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=50)
    result = value_iteration(mdp, actions, objective="cost")
    start_item = concretize(gamedata, target, s0, rng)

    spread = estimate_cost_spread(gamedata, target, actions, result.policy, start_item, rng, n_rollouts=0)
    assert spread == estimate_cost_spread(gamedata, target, actions, result.policy, start_item, rng, n_rollouts=0)
    assert spread.n_samples == 0
    assert spread.success_rate == 0.0
