"""Statistical correctness of the weighted draw and within-tier value roll,
against a small hand-built fixture pool -- independent of the real vendored
dataset, so these stay fast and isolated from upstream data changes."""
import random
from collections import Counter

from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.sampler import roll_values, weighted_pick

MOD_A = ModDef(id=ModId("A"), name="Mod A", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gA"}))
MOD_B = ModDef(id=ModId("B"), name="Mod B", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gB"}))
MOD_C = ModDef(id=ModId("C"), name="Mod C", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gC"}))

TIER_A = ModTierEntry(mod_id=ModId("A"), base_id=BaseId("X"), ilvl=1, weight=100, value_ranges=((1.0, 1.0),))
TIER_B = ModTierEntry(mod_id=ModId("B"), base_id=BaseId("X"), ilvl=1, weight=300, value_ranges=((1.0, 1.0),))
TIER_C = ModTierEntry(mod_id=ModId("C"), base_id=BaseId("X"), ilvl=1, weight=600, value_ranges=((1.0, 1.0),))

POOL = [(MOD_A, TIER_A), (MOD_B, TIER_B), (MOD_C, TIER_C)]
N = 30_000


def test_weighted_pick_matches_relative_weights():
    # weights 100:300:600 -> expected fractions 0.1 : 0.3 : 0.6
    rng = random.Random(12345)
    counts = Counter()
    for _ in range(N):
        mod, _tier = weighted_pick(POOL, rng)
        counts[mod.id] += 1
    fractions = {mid: c / N for mid, c in counts.items()}
    assert 0.09 < fractions[ModId("A")] < 0.11
    assert 0.29 < fractions[ModId("B")] < 0.31
    assert 0.59 < fractions[ModId("C")] < 0.61


def test_weighted_pick_never_returns_zero_weight_entries():
    zero_weight_tier = ModTierEntry(mod_id=ModId("Z"), base_id=BaseId("X"), ilvl=1, weight=0, value_ranges=())
    mod_z = ModDef(id=ModId("Z"), name="Z", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gZ"}))
    # A zero-weight entry should never win against any positive-weight entry.
    pool = [(mod_z, zero_weight_tier), (MOD_A, TIER_A)]
    rng = random.Random(1)
    for _ in range(500):
        mod, _ = weighted_pick(pool, rng)
        assert mod.id != ModId("Z")


def test_roll_values_stays_within_range():
    rng = random.Random(7)
    ranges = ((10.0, 20.0), (-5.0, -1.0))
    for _ in range(2000):
        values = roll_values(ranges, rng)
        assert 10.0 <= values[0] <= 20.0
        assert -5.0 <= values[1] <= -1.0
