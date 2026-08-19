"""Greater/Perfect currency tiers: the min-ilvl floor confirmed against
poe2db.tw (see engine.apply.MIN_ILVL_BY_TIER), tested against a small
hand-built fixture with mods at a spread of ilvl requirements."""
import random

import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.actions import CurrencyTier
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.apply import ExaltedAction, RegalAction, TransmutationAction

BASE_ID = BaseId("b1")


@pytest.fixture
def tiered_gamedata() -> GameData:
    low_mod = ModDef(id=ModId("low"), name="Low Mod", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gLow"}))
    high_mod = ModDef(id=ModId("high"), name="High Mod", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gHigh"}))
    prefix_mod = ModDef(id=ModId("pfx"), name="Prefix Mod", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gPfx"}))

    # "low" is always below any Greater/Perfect floor; "high" sits exactly at
    # Greater's 44 floor (and below Perfect's 70), so it's the one mod that
    # distinguishes Base-tier eligibility from Greater-tier eligibility.
    low_tier = ModTierEntry(mod_id=ModId("low"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())
    high_tier = ModTierEntry(mod_id=ModId("high"), base_id=BASE_ID, ilvl=44, weight=100, value_ranges=())
    pfx_tier = ModTierEntry(mod_id=ModId("pfx"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())

    tiers_by_base = {BASE_ID: {ModId("low"): [low_tier], ModId("high"): [high_tier], ModId("pfx"): [pfx_tier]}}

    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("low"): low_mod, ModId("high"): high_mod, ModId("pfx"): prefix_mod},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )


def test_base_tier_has_no_ilvl_floor(tiered_gamedata):
    action = TransmutationAction(tiered_gamedata, tier=CurrencyTier.BASE)
    assert action.min_ilvl == 0
    item = Item(base_id=BASE_ID, ilvl=1, rarity=Rarity.NORMAL)
    assert action.applicable(item)  # the low-ilvl mod alone is enough


def test_greater_tier_requires_min_ilvl_44(tiered_gamedata):
    action = TransmutationAction(tiered_gamedata, tier=CurrencyTier.GREATER)
    assert action.min_ilvl == 44
    assert action.name == "Greater Orb of Transmutation"

    too_low_item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.NORMAL)  # neither tier reaches ilvl 44 yet
    assert not action.applicable(too_low_item)

    high_enough_item = Item(base_id=BASE_ID, ilvl=44, rarity=Rarity.NORMAL)
    assert action.applicable(high_enough_item)
    result = action.outcome(high_enough_item, random.Random(0))
    assert result.suffixes[0].mod_id == ModId("high")  # "low" (ilvl 1) is excluded by the floor


def test_perfect_tier_costs_more_than_greater_which_costs_more_than_base(tiered_gamedata):
    base = TransmutationAction(tiered_gamedata, tier=CurrencyTier.BASE)
    greater = TransmutationAction(tiered_gamedata, tier=CurrencyTier.GREATER)
    perfect = TransmutationAction(tiered_gamedata, tier=CurrencyTier.PERFECT)
    assert base.cost() < greater.cost() < perfect.cost()


def test_regal_checks_room_as_if_already_rare_not_magic(tiered_gamedata):
    """Regression test for a real bug found during implementation: checking
    pool/room eligibility while the item is still Magic (1-prefix/1-suffix cap)
    instead of as-if-already-Rare (here, 3-prefix/3-suffix) would wrongly
    report inapplicable whenever the Magic item's relevant affix side is
    already at Magic's cap but still open under Rare's larger one."""
    existing_suffix = RolledAffix(mod_id=ModId("low"), affix=Affix.SUFFIX, group_keys=frozenset({"gLow"}), value_ranges=(), values=())
    magic_item = Item(base_id=BASE_ID, ilvl=44, rarity=Rarity.MAGIC, suffixes=(existing_suffix,))
    action = RegalAction(tiered_gamedata, tier=CurrencyTier.GREATER)
    # Magic's suffix cap (1) is already full, and the only other eligible mod
    # at the Greater floor ("high") is itself a suffix -- a check performed
    # under Magic's cap would find no room and wrongly report inapplicable.
    assert action.applicable(magic_item)
    result = action.outcome(magic_item, random.Random(1))
    assert result.rarity is Rarity.RARE
    assert any(a.mod_id == ModId("high") for a in result.suffixes)


def test_exalted_omen_restriction_combines_with_ilvl_floor(tiered_gamedata):
    action = ExaltedAction(tiered_gamedata, restrict=Affix.SUFFIX, tier=CurrencyTier.GREATER)
    rare_item = Item(base_id=BASE_ID, ilvl=44, rarity=Rarity.RARE)
    assert action.applicable(rare_item)
    result = action.outcome(rare_item, random.Random(2))
    assert result.suffixes[0].mod_id == ModId("high")
    assert "Greater Exalted Orb" in action.name
    assert "suffixes only" in action.name
