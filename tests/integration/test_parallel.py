"""`build_mdp(executor=...)`'s parallel path (`solver.parallel`), against the
real compiled gamedata with a real (small) process pool -- this needs actual
OS processes to be a meaningful test, so it lives in integration, not unit."""
import random

import pytest

from poe2craft.data.loader import load_gamedata
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.domain.mods import ModCategory
from poe2craft.engine.omens import all_actions
from poe2craft.solver.featurize import resolve_target, start_state
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.parallel import make_executor
from poe2craft.solver.value_iteration import value_iteration


@pytest.fixture(scope="module")
def gamedata():
    return load_gamedata()


@pytest.fixture(scope="module")
def executor(gamedata):
    ex = make_executor(gamedata, max_workers=4)
    yield ex
    ex.shutdown(wait=True)


def test_parallel_matches_sequential_on_a_deterministic_scenario(gamedata, executor):
    # Same regression case as test_end_to_end.py's essence-exclusive-mod
    # test: Alchemy then a guaranteed essence, exactly 2 deterministic steps,
    # 100% reach probability -- a scenario where the *result* shouldn't
    # depend on exactly which RNG draws happened, even though the parallel
    # path's draw sequence necessarily differs from the sequential one.
    mod_id = ModId("5698")
    base_id = BaseId("45")  # Body Armour (STR)
    assert gamedata.mods[mod_id].category is ModCategory.ESSENCE_ONLY

    spec = TargetSpec(base="Body Armour (STR)", ilvl=80, target_mods=[TargetModSpec(mod_id=str(mod_id))], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata, base_id=base_id)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(3)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=200, executor=executor, base_id=base_id)
    result = value_iteration(mdp, actions, objective="steps")

    assert result.converged
    assert abs(-result.expected_value(s0) - 2.0) < 0.1


def test_parallel_goal_at_start_produces_no_transitions(gamedata, executor):
    # The pitfall called out during design: generating/caching transitions
    # *from* a goal state would corrupt value_iteration's absorbing-state
    # assumption. A target with no target mods at all makes the empty status
    # tuple trivially satisfied, so the start state is already a goal.
    spec = TargetSpec(base="Amulet", ilvl=80, target_mods=[], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    base_id = target.base_id
    actions = all_actions(gamedata, base_id=base_id)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())
    assert s0.is_goal()

    rng = random.Random(1)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=50, executor=executor, base_id=base_id)

    assert mdp.goal_states == {s0}
    assert mdp.transitions == {}
    assert mdp.states == {s0}


def test_build_mdp_rejects_a_mismatched_action_set(gamedata, executor):
    base_id = BaseId("2")  # Amulet
    spec = TargetSpec(base="Amulet", ilvl=80, target_mods=[TargetModSpec(mod_id="5724")], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())
    wrong_actions = all_actions(gamedata, base_id=BaseId("1"))  # Ring, not Amulet -- a real but wrong action set

    with pytest.raises(ValueError, match="mismatched action set"):
        build_mdp(gamedata, target, s0, wrong_actions, random.Random(0), n_trials=10, executor=executor, base_id=base_id)
