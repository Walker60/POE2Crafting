"""`estimate_transition`'s reveal-and-pick-best branch, for any action
exposing `reveal_candidates` (Desecration is the only real one right now,
but this test uses a synthetic fake action instead of `DesecrationAction`
directly, so it isolates the branch itself from any real reveal mechanics)."""
import random

from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import ModId
from poe2craft.domain.items import Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix
from poe2craft.solver.featurize import resolve_target, start_state
from poe2craft.solver.model_learning import estimate_transition


class _FakeRevealAction:
    """Always applicable; reveals a FIXED set of candidate items via a
    caller-supplied factory rather than randomly sampling anything."""

    def __init__(self, candidates_factory):
        self._factory = candidates_factory

    def applicable(self, item):
        return True

    def reveal_candidates(self, item, rng):
        return self._factory(item)


def test_estimate_transition_always_picks_the_target_satisfying_candidate(gamedata):
    spec = TargetSpec(base="Test Base", ilvl=80, target_mods=[TargetModSpec(mod_id="p3")])
    target = resolve_target(gamedata, spec)
    state = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    satisfying_affix = RolledAffix(
        mod_id=ModId("p3"), affix=Affix.PREFIX, group_keys=frozenset({"groupY"}), value_ranges=(), values=(), ilvl=1
    )
    filler_affix = RolledAffix(
        mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=(), ilvl=1
    )

    def reveal(item):
        satisfying = Item(base_id=item.base_id, ilvl=item.ilvl, rarity=Rarity.RARE, prefixes=(satisfying_affix,))
        filler = Item(base_id=item.base_id, ilvl=item.ilvl, rarity=Rarity.RARE, suffixes=(filler_affix,))
        # The satisfying candidate is neither first nor last -- proves it's
        # chosen by merit, not position.
        return [filler, satisfying, filler]

    action = _FakeRevealAction(reveal)
    rng = random.Random(0)
    dist = estimate_transition(gamedata, target, state, action, rng, n_trials=5)

    assert len(dist) == 1  # every trial converged on the same (goal) outcome
    only_state = next(iter(dist))
    assert only_state.is_goal()


def test_estimate_transition_breaks_ties_randomly_when_nothing_helps(gamedata):
    spec = TargetSpec(base="Test Base", ilvl=80, target_mods=[TargetModSpec(mod_id="p3")])
    target = resolve_target(gamedata, spec)
    state = start_state(gamedata, target, Rarity.NORMAL, frozenset())

    # Different affix TYPES (not just different mods) so the two candidates
    # land on genuinely distinct abstract states (different prefix/suffix
    # counts) despite neither satisfying the target -- lets this test prove
    # the tie-break is actually random, not just non-crashing.
    filler_prefix = RolledAffix(
        mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=(), ilvl=1
    )
    filler_suffix = RolledAffix(
        mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=(), ilvl=1
    )

    def reveal(item):
        a = Item(base_id=item.base_id, ilvl=item.ilvl, rarity=Rarity.RARE, prefixes=(filler_prefix,))
        b = Item(base_id=item.base_id, ilvl=item.ilvl, rarity=Rarity.RARE, suffixes=(filler_suffix,))
        return [a, b]

    action = _FakeRevealAction(reveal)
    rng = random.Random(0)
    dist = estimate_transition(gamedata, target, state, action, rng, n_trials=200)

    # Neither candidate satisfies the target -- both are equally-irrelevant
    # fillers, so a real random tie-break should produce *both* resulting
    # states across 200 trials, not silently always favor one.
    assert len(dist) == 2
    assert not any(s.is_goal() for s in dist)
