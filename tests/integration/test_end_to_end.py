"""Real solves against the full compiled gamedata, across distinct base groups,
proving broad data coverage actually plugs into the solver end-to-end (not just
against hand-built fixtures). Uses a low Monte Carlo trial count to keep this
fast -- these check plausibility/consistency, not tight numeric accuracy."""
import random

import pytest

from poe2craft.data.loader import load_gamedata
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.domain.mods import ModCategory
from poe2craft.engine.omens import all_actions
from poe2craft.solver.featurize import concretize, resolve_target, start_state
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.playback import run_trajectory
from poe2craft.solver.value_iteration import value_iteration


@pytest.fixture(scope="module")
def gamedata():
    return load_gamedata()


def _first_eligible_mod(gamedata, base_name: str, affix: str, max_ilvl: int = 70):
    base = next(b for b in gamedata.bases.values() if b.name == base_name)
    eligible = gamedata.eligible_mods_for_base(base.id)
    for mid, tiers in eligible.items():
        if gamedata.mods[mid].affix.value == affix and any(t.ilvl <= max_ilvl for t in tiers):
            return mid
    raise AssertionError(f"no eligible {affix} mod found for {base_name!r}")


@pytest.mark.parametrize(
    "base_name,affix",
    [
        ("Amulet", "suffix"),  # Jewellery
        ("One Hand Sword", "prefix"),  # One-Handed Weapons
        ("Body Armour (STR)", "prefix"),  # Body Armours
        ("Ruby", "suffix"),  # Jewels
    ],
)
def test_solve_reaches_a_plausible_answer_across_base_groups(gamedata, base_name, affix):
    mod_id = _first_eligible_mod(gamedata, base_name, affix)
    spec = TargetSpec(base=base_name, ilvl=70, target_mods=[TargetModSpec(mod_id=mod_id)], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(42)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=150)
    result = value_iteration(mdp, actions, objective="steps")

    assert result.converged
    assert s0 in result.policy, f"no policy action found for the start state on {base_name}"
    expected_steps = -result.expected_value(s0)
    # A single-mod target should be solvable in a small, plausible number of
    # expected steps -- loose bounds since this is a plausibility check, not a
    # tight numeric one (n_trials=150 keeps this fast, not high-precision).
    assert 1.0 < expected_steps < 60.0


def test_simulated_playthroughs_roughly_track_the_solved_policy(gamedata):
    mod_id = _first_eligible_mod(gamedata, "Amulet", "suffix")
    spec = TargetSpec(base="Amulet", ilvl=70, target_mods=[TargetModSpec(mod_id=mod_id)], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(7)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=300)
    result = value_iteration(mdp, actions, objective="steps")

    successes = 0
    n = 150
    for _ in range(n):
        item = concretize(gamedata, target, s0, rng)
        traj = run_trajectory(gamedata, target, actions, result.policy, item, rng, max_steps=30)
        successes += traj.success
    # With a real single-mod target and up to 30 steps, the vast majority of
    # real playthroughs following the solved policy should reach the goal --
    # a generous bound since this is a sanity check against total breakage
    # (e.g. an abstraction bug that makes the solver's model and the real
    # sampler disagree), not a precise statistical match.
    assert successes / n > 0.6


def test_essence_exclusive_mod_solves_in_exactly_two_deterministic_steps(gamedata):
    """Regression test locking in a real, verified result: mod 5698 ("#%
    increased maximum Life" on Body Armour bases) has weight=0 in the general
    pool -- normal rolling can never produce it -- and is only granted by
    "Perfect Essence of the Body". The optimal policy should be exactly
    Alchemy (cheapest way to a Rare item) then that essence (deterministic
    once applicable), for exactly 2 steps with 100% reach probability."""
    mod_id = ModId("5698")
    base_id = BaseId("45")  # Body Armour (STR)
    assert gamedata.mods[mod_id].category is ModCategory.ESSENCE_ONLY
    assert mod_id not in gamedata.eligible_mods_for_base(base_id)  # confirms it's NOT normally rollable

    spec = TargetSpec(base="Body Armour (STR)", ilvl=80, target_mods=[TargetModSpec(mod_id=str(mod_id))], objective="steps", max_steps=30)
    target = resolve_target(gamedata, spec)
    actions = all_actions(gamedata, base_id=base_id)
    s0 = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    rng = random.Random(3)
    mdp = build_mdp(gamedata, target, s0, actions, rng, n_trials=200)
    result = value_iteration(mdp, actions, objective="steps")

    assert result.converged
    assert abs(-result.expected_value(s0) - 2.0) < 0.1

    successes = 0
    n = 50
    for _ in range(n):
        item = concretize(gamedata, target, s0, rng)
        traj = run_trajectory(gamedata, target, actions, result.policy, item, rng, max_steps=30)
        successes += traj.success
        assert traj.step_count <= 2
    assert successes == n  # deterministic once a Rare item exists -- always succeeds
