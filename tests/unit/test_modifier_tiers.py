"""Modifier-tier targeting: a TargetModSpec can request a minimum ilvl, and
the abstract state distinguishes ABSENT / present-but-BELOW_TIER / SATISFIED
for that one mod, instead of a plain presence bool. Uses a dedicated fixture
with a mod that has two real tiers (weak ilvl=10, strong ilvl=60) so status
can actually be exercised, unlike the shared conftest.py fixture where every
mod has just one tier."""
import random

import pytest

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.solver.featurize import (
    ModStatus,
    TargetResolutionError,
    abstractify,
    concretize,
    resolve_target,
    start_state,
)

BASE_ID = BaseId("b1")
TIERED_MOD = ModId("tiered")
FILLER_MOD = ModId("filler")


@pytest.fixture
def gamedata() -> GameData:
    tiered = ModDef(id=TIERED_MOD, name="Tiered Mod", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gTiered"}))
    filler = ModDef(id=FILLER_MOD, name="Filler Mod", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gFiller"}))
    weak = ModTierEntry(mod_id=TIERED_MOD, base_id=BASE_ID, ilvl=10, weight=100, value_ranges=())
    strong = ModTierEntry(mod_id=TIERED_MOD, base_id=BASE_ID, ilvl=60, weight=100, value_ranges=())
    filler_tier = ModTierEntry(mod_id=FILLER_MOD, base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())
    tiers_by_base = {BASE_ID: {TIERED_MOD: [weak, strong], FILLER_MOD: [filler_tier]}}
    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={TIERED_MOD: tiered, FILLER_MOD: filler},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )


def _spec(min_ilvl: int, item_ilvl: int = 80) -> TargetSpec:
    return TargetSpec(base="Test Base", ilvl=item_ilvl, target_mods=[TargetModSpec(mod_id=str(TIERED_MOD), min_ilvl=min_ilvl)])


def test_resolve_target_accepts_a_reachable_min_ilvl(gamedata):
    target = resolve_target(gamedata, _spec(min_ilvl=60))
    assert target.target_mods[0].min_ilvl == 60


def test_resolve_target_rejects_an_unreachable_min_ilvl(gamedata):
    with pytest.raises(TargetResolutionError, match="unreachable"):
        resolve_target(gamedata, _spec(min_ilvl=60, item_ilvl=50))  # item too low-level for the strong tier to ever roll

    with pytest.raises(TargetResolutionError):
        resolve_target(gamedata, _spec(min_ilvl=999))  # no tier reaches this at all


def test_abstractify_distinguishes_below_tier_from_satisfied(gamedata):
    target = resolve_target(gamedata, _spec(min_ilvl=60))
    weak_affix = RolledAffix(mod_id=TIERED_MOD, affix=Affix.PREFIX, group_keys=frozenset({"gTiered"}), value_ranges=(), values=(), ilvl=10)
    strong_affix = RolledAffix(mod_id=TIERED_MOD, affix=Affix.PREFIX, group_keys=frozenset({"gTiered"}), value_ranges=(), values=(), ilvl=60)

    absent_item = Item(base_id=BASE_ID, ilvl=80, rarity=Rarity.RARE)
    weak_item = Item(base_id=BASE_ID, ilvl=80, rarity=Rarity.RARE, prefixes=(weak_affix,))
    strong_item = Item(base_id=BASE_ID, ilvl=80, rarity=Rarity.RARE, prefixes=(strong_affix,))

    assert abstractify(target, absent_item).status == (ModStatus.ABSENT,)
    assert abstractify(target, weak_item).status == (ModStatus.BELOW_TIER,)
    assert abstractify(target, strong_item).status == (ModStatus.SATISFIED,)
    assert not abstractify(target, weak_item).is_goal()
    assert abstractify(target, strong_item).is_goal()


def test_concretize_respects_the_requested_status(gamedata):
    target = resolve_target(gamedata, _spec(min_ilvl=60))
    rng = random.Random(0)

    satisfied_state = start_state(gamedata, target, Rarity.RARE, frozenset({TIERED_MOD}))
    # start_state always asserts SATISFIED for a declared starting mod (see
    # its docstring) -- concretizing it must place a qualifying (ilvl>=60) tier.
    for _ in range(20):
        item = concretize(gamedata, target, satisfied_state, rng)
        placed = next(a for a in item.affixes if a.mod_id == TIERED_MOD)
        assert placed.ilvl >= 60
        assert abstractify(target, item).is_goal()

    below_tier_state = type(satisfied_state)(
        rarity=Rarity.RARE, prefix_count=1, suffix_count=0, status=(ModStatus.BELOW_TIER,)
    )
    for _ in range(20):
        item = concretize(gamedata, target, below_tier_state, rng)
        placed = next(a for a in item.affixes if a.mod_id == TIERED_MOD)
        assert placed.ilvl < 60
        assert abstractify(target, item).status == (ModStatus.BELOW_TIER,)


def test_tier_ranks_orders_best_tier_first(gamedata):
    # T1 = highest ilvl requirement = the strongest/rarest tier, matching the
    # in-game "Tier: N" display convention (confirmed with the user earlier
    # in this project) -- NOT ascending-by-ilvl, which is how tiers_by_base/
    # all_tiers_by_base store them internally for the general roll pool.
    ranks = gamedata.tier_ranks(BASE_ID, TIERED_MOD)
    assert [t.ilvl for t in ranks] == [60, 10]


def test_target_with_no_min_ilvl_never_produces_below_tier(gamedata):
    """A plain (untiered) target should behave exactly as before this feature
    -- ABSENT or SATISFIED only, since any tier at all already qualifies."""
    target = resolve_target(gamedata, _spec(min_ilvl=0))
    weak_affix = RolledAffix(mod_id=TIERED_MOD, affix=Affix.PREFIX, group_keys=frozenset({"gTiered"}), value_ranges=(), values=(), ilvl=10)
    item = Item(base_id=BASE_ID, ilvl=80, rarity=Rarity.RARE, prefixes=(weak_affix,))
    assert abstractify(target, item).status == (ModStatus.SATISFIED,)
