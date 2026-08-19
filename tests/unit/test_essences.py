"""EssenceAction correctness against a small hand-built fixture (independent of
the real vendored dataset): one non-Perfect essence guaranteeing a normal-pool
mod, one Perfect essence guaranteeing an essence-exclusive mod."""
import random

import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.essences import EssenceDef, EssenceGrant, EssenceTierKind, split_essence_name
from poe2craft.domain.ids import BaseGroupId, BaseId, EssenceId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.apply import EssenceAction

BASE_ID = BaseId("b1")


@pytest.mark.parametrize(
    "name,expected_family,expected_kind",
    [
        ("Essence of Battle", "Essence of Battle", EssenceTierKind.NORMAL),
        ("Greater Essence of Battle", "Essence of Battle", EssenceTierKind.GREATER),
        ("Lesser Essence of Battle", "Essence of Battle", EssenceTierKind.LESSER),
        ("Perfect Essence of Battle", "Essence of Battle", EssenceTierKind.PERFECT),
        ("Adaptive Alloy", "Adaptive Alloy", EssenceTierKind.NORMAL),
    ],
)
def test_split_essence_name(name, expected_family, expected_kind):
    family, kind = split_essence_name(name)
    assert family == expected_family
    assert kind is expected_kind


@pytest.fixture
def essence_gamedata() -> GameData:
    normal_mod = ModDef(id=ModId("normal1"), name="Normal Mod", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gNormal"}))
    filler_mod = ModDef(id=ModId("filler1"), name="Filler Mod", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gFiller"}))
    exclusive_mod = ModDef(id=ModId("exclusive1"), name="Exclusive Mod", affix=Affix.PREFIX, category=ModCategory.ESSENCE_ONLY, group_keys=frozenset({"gExclusive"}))

    normal_tier = ModTierEntry(mod_id=ModId("normal1"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=((1.0, 2.0),))
    filler_tier = ModTierEntry(mod_id=ModId("filler1"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=((1.0, 2.0),))
    exclusive_tier = ModTierEntry(mod_id=ModId("exclusive1"), base_id=BASE_ID, ilvl=1, weight=0, value_ranges=((5.0, 5.0),))

    all_tiers_by_base = {BASE_ID: {ModId("normal1"): [normal_tier], ModId("filler1"): [filler_tier], ModId("exclusive1"): [exclusive_tier]}}
    tiers_by_base = {BASE_ID: {ModId("normal1"): [normal_tier], ModId("filler1"): [filler_tier]}}

    regular_essence = EssenceDef(
        id=EssenceId("e1"), name="Essence of Testing", family="Essence of Testing", tier_kind=EssenceTierKind.NORMAL,
        per_base={BASE_ID: (EssenceGrant(mod_id=ModId("normal1"), ilvl=1),)},
    )
    perfect_essence = EssenceDef(
        id=EssenceId("e2"), name="Perfect Essence of Testing", family="Essence of Testing", tier_kind=EssenceTierKind.PERFECT,
        per_base={BASE_ID: (EssenceGrant(mod_id=ModId("exclusive1"), ilvl=1),)},
    )

    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("normal1"): normal_mod, ModId("filler1"): filler_mod, ModId("exclusive1"): exclusive_mod},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=all_tiers_by_base,
        essences=[regular_essence, perfect_essence],
    )


def test_regular_essence_requires_magic_and_guarantees_its_mod(essence_gamedata):
    essence = essence_gamedata.essences[0]
    action = EssenceAction(essence_gamedata, essence, BASE_ID)
    assert action.kind.value == "essence"

    normal_item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.NORMAL)
    assert not action.applicable(normal_item)  # essences never act on Normal items

    magic_item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC)
    assert action.applicable(magic_item)
    result = action.outcome(magic_item, random.Random(0))
    assert result.rarity is Rarity.RARE
    assert result.prefixes[0].mod_id == ModId("normal1")


def test_essence_not_applicable_below_required_ilvl(essence_gamedata):
    essence = essence_gamedata.essences[0]
    action = EssenceAction(essence_gamedata, essence, BASE_ID)
    too_low = Item(base_id=BASE_ID, ilvl=0, rarity=Rarity.MAGIC)  # grant requires ilvl>=1
    assert not action.applicable(too_low)


def test_essence_not_applicable_on_unsupported_base(essence_gamedata):
    essence = essence_gamedata.essences[0]
    action = EssenceAction(essence_gamedata, essence, BaseId("other_base"))
    assert action.grants == ()
    item = Item(base_id=BaseId("other_base"), ilvl=10, rarity=Rarity.MAGIC)
    assert not action.applicable(item)


def test_perfect_essence_removes_one_mod_and_adds_the_exclusive_mod(essence_gamedata):
    essence = essence_gamedata.essences[1]
    action = EssenceAction(essence_gamedata, essence, BASE_ID)
    assert action.perfect
    assert action.kind.value == "perfect_essence"

    normal_affix = RolledAffix(mod_id=ModId("normal1"), affix=Affix.PREFIX, group_keys=frozenset({"gNormal"}), value_ranges=(), values=())
    filler_affix = RolledAffix(mod_id=ModId("filler1"), affix=Affix.SUFFIX, group_keys=frozenset({"gFiller"}), value_ranges=(), values=())
    rare_item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.RARE, prefixes=(normal_affix,), suffixes=(filler_affix,))

    assert action.applicable(rare_item)
    result = action.outcome(rare_item, random.Random(1))
    assert len(result.affixes) == 2  # removed one, added one -- net unchanged
    assert any(a.mod_id == ModId("exclusive1") for a in result.affixes)
    assert len(result.occupied_group_keys()) == len(result.affixes)  # no exclusion violation


def test_perfect_essence_not_applicable_with_no_removable_mods(essence_gamedata):
    essence = essence_gamedata.essences[1]
    action = EssenceAction(essence_gamedata, essence, BASE_ID)
    empty_rare = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.RARE)
    assert not action.applicable(empty_rare)  # nothing to remove
