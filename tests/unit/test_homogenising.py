"""Omen of Homogenising Coronation/Exaltation: restricts the next Regal/Exalted
add to a mod sharing a broad category tag (e.g. "fire") with an existing
modifier. Uses a dedicated fixture with actual tags set, since the shared
conftest.py fixture's mods are untagged (matching most real mods, per
docs/design_notes.md -- only 57% of rollable mods have any tag at all)."""
import random

import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.apply import ExaltedAction, RegalAction

BASE_ID = BaseId("b1")


@pytest.fixture
def tagged_gamedata() -> GameData:
    def mod(mid: str, affix: Affix, group: str, tags: frozenset[str] = frozenset()) -> ModDef:
        return ModDef(id=ModId(mid), name=mid, affix=affix, category=ModCategory.NORMAL, group_keys=frozenset({group}), tags=tags)

    def tier(mid: str) -> ModTierEntry:
        return ModTierEntry(mod_id=ModId(mid), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())

    mods = {
        "existing_fire": mod("existing_fire", Affix.PREFIX, "gExistingFire", frozenset({"fire"})),
        "candidate_fire": mod("candidate_fire", Affix.SUFFIX, "gCandFire", frozenset({"fire", "elemental"})),
        "candidate_cold": mod("candidate_cold", Affix.SUFFIX, "gCandCold", frozenset({"cold"})),
        "candidate_untagged": mod("candidate_untagged", Affix.SUFFIX, "gCandUntagged"),
        "existing_untagged": mod("existing_untagged", Affix.PREFIX, "gExistingUntagged"),
    }
    tiers_by_base = {BASE_ID: {mid: [tier(mid)] for mid in mods}}
    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId(k): v for k, v in mods.items()},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )


def _affix(mid: str, affix: Affix, group: str) -> RolledAffix:
    return RolledAffix(mod_id=ModId(mid), affix=affix, group_keys=frozenset({group}), value_ranges=(), values=())


def test_regal_homogenising_only_adds_a_same_tag_mod(tagged_gamedata):
    existing = _affix("existing_fire", Affix.PREFIX, "gExistingFire")
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC, prefixes=(existing,))
    action = RegalAction(tagged_gamedata, homogenising=True)
    assert action.applicable(item)
    for seed in range(20):
        result = action.outcome(item, random.Random(seed))
        assert result.rarity is Rarity.RARE
        new_mod_ids = {a.mod_id for a in result.affixes} - {ModId("existing_fire")}
        assert new_mod_ids == {ModId("candidate_fire")}  # the only other fire/elemental-tagged mod


def test_regal_homogenising_inapplicable_with_no_tagged_existing_mods(tagged_gamedata):
    existing = _affix("existing_untagged", Affix.PREFIX, "gExistingUntagged")
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC, prefixes=(existing,))
    action = RegalAction(tagged_gamedata, homogenising=True)
    assert not action.applicable(item)  # no tag on the item's one existing mod -- nothing to homogenise against


def test_regal_homogenising_inapplicable_on_empty_item(tagged_gamedata):
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC)
    action = RegalAction(tagged_gamedata, homogenising=True)
    assert not action.applicable(item)  # no existing mods at all


def test_regal_without_homogenising_ignores_tags_entirely(tagged_gamedata):
    existing = _affix("existing_fire", Affix.PREFIX, "gExistingFire")
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC, prefixes=(existing,))
    action = RegalAction(tagged_gamedata)  # no homogenising
    seen = set()
    for seed in range(30):
        result = action.outcome(item, random.Random(seed))
        new_mod_ids = {a.mod_id for a in result.affixes} - {ModId("existing_fire")}
        seen |= new_mod_ids
    # cold and untagged candidates should both be reachable when not restricted
    assert ModId("candidate_cold") in seen
    assert ModId("candidate_untagged") in seen


def test_exalted_homogenising_only_adds_a_same_tag_mod(tagged_gamedata):
    existing = _affix("existing_fire", Affix.PREFIX, "gExistingFire")
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.RARE, prefixes=(existing,))
    action = ExaltedAction(tagged_gamedata, homogenising=True)
    assert action.applicable(item)
    result = action.outcome(item, random.Random(0))
    new_mod_ids = {a.mod_id for a in result.affixes} - {ModId("existing_fire")}
    assert new_mod_ids == {ModId("candidate_fire")}
    assert "same type as existing" in action.name
