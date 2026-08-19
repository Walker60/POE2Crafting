"""`item_from_report`: builds a real Item from a user's freeform description of
their actual item's current mods+tiers -- the first place in the codebase that
builds an Item from arbitrary external input rather than the engine's own
controlled sampling, so every invariant the rest of the engine assumes has to
be validated explicitly here rather than inherited for free."""
import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Rarity
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.solver.featurize import ItemReportError, item_from_report

BASE_ID = BaseId("base1")


def test_valid_report_builds_a_correct_item(gamedata):
    item = item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.RARE, mod_reports=[(ModId("p3"), 1), (ModId("s1"), 1)])
    assert item.rarity is Rarity.RARE
    assert item.prefix_count == 1 and item.suffix_count == 1
    assert {a.mod_id for a in item.affixes} == {ModId("p3"), ModId("s1")}
    assert all(a.ilvl == 1 for a in item.affixes)


def test_normal_rarity_rejects_any_mods(gamedata):
    with pytest.raises(ItemReportError, match="Normal"):
        item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.NORMAL, mod_reports=[(ModId("p3"), 1)])


def test_normal_rarity_with_no_mods_is_fine(gamedata):
    item = item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.NORMAL, mod_reports=[])
    assert item.rarity is Rarity.NORMAL
    assert not item.affixes


def test_rejects_group_exclusion_conflict(gamedata):
    # p1 and p2 share "groupX" in the shared fixture
    with pytest.raises(ItemReportError, match="exclusion group"):
        item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.RARE, mod_reports=[(ModId("p1"), 1), (ModId("p2"), 1)])


def test_rejects_magic_with_two_prefixes(gamedata):
    with pytest.raises(ItemReportError, match="allows at most"):
        item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.MAGIC, mod_reports=[(ModId("p1"), 1), (ModId("p3"), 1)])


def test_magic_with_one_prefix_one_suffix_is_fine(gamedata):
    item = item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.MAGIC, mod_reports=[(ModId("p1"), 1), (ModId("s1"), 1)])
    assert item.prefix_count == 1 and item.suffix_count == 1


def test_rejects_unknown_mod_id(gamedata):
    with pytest.raises(ItemReportError, match="unknown mod id"):
        item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.RARE, mod_reports=[(ModId("nope"), 1)])


def test_rejects_duplicate_mod_id(gamedata):
    with pytest.raises(ItemReportError, match="duplicate"):
        item_from_report(gamedata, BASE_ID, ilvl=1, rarity=Rarity.RARE, mod_reports=[(ModId("p3"), 1), (ModId("p3"), 1)])


def test_rejects_mod_with_no_matching_tier(gamedata):
    # "hi_ilvl" fixture mod's real tier is at ilvl=100, not ilvl=1
    with pytest.raises(ItemReportError, match="no tier"):
        item_from_report(gamedata, BASE_ID, ilvl=100, rarity=Rarity.RARE, mod_reports=[(ModId("hi_ilvl"), 1)])


def test_rejects_a_tier_requiring_higher_ilvl_than_the_item_itself(gamedata):
    # "hi_ilvl"'s real tier is at ilvl=100 -- physically impossible on an ilvl-10 item
    with pytest.raises(ItemReportError, match="only ilvl"):
        item_from_report(gamedata, BASE_ID, ilvl=10, rarity=Rarity.RARE, mod_reports=[(ModId("hi_ilvl"), 100)])


def test_round_trips_through_abstractify_as_satisfied_when_tier_meets_min_ilvl():
    from poe2craft.solver.featurize import ResolvedTarget, TargetModRequirement, abstractify

    # Build a tiny bespoke gamedata for this, isolated from the shared fixture.
    tiered_mod = ModDef(id=ModId("t1"), name="Tiered", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"g1"}))
    weak = ModTierEntry(mod_id=ModId("t1"), base_id=BASE_ID, ilvl=10, weight=100, value_ranges=((1.0, 2.0),))
    strong = ModTierEntry(mod_id=ModId("t1"), base_id=BASE_ID, ilvl=60, weight=100, value_ranges=((3.0, 4.0),))
    tiers_by_base = {BASE_ID: {ModId("t1"): [weak, strong]}}
    gd = GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("t1"): tiered_mod},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=ModId("t1"), min_ilvl=50),), objective="steps", max_steps=30)

    weak_item = item_from_report(gd, BASE_ID, ilvl=80, rarity=Rarity.RARE, mod_reports=[(ModId("t1"), 10)])
    strong_item = item_from_report(gd, BASE_ID, ilvl=80, rarity=Rarity.RARE, mod_reports=[(ModId("t1"), 60)])
    assert not abstractify(target, weak_item).is_goal()
    assert abstractify(target, strong_item).is_goal()


def test_rejects_a_non_prefix_suffix_affix_and_exceeding_rare_caps():
    # Small bespoke gamedata with a corrupted-only mod and 4 non-conflicting suffixes.
    corrupted_mod = ModDef(id=ModId("c1"), name="Corrupted", affix=Affix.CORRUPTED, category=ModCategory.NORMAL, group_keys=frozenset({"gc"}))
    suffix_mods = {
        ModId(f"s{i}"): ModDef(id=ModId(f"s{i}"), name=f"S{i}", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({f"gs{i}"}))
        for i in range(1, 5)
    }
    tiers_by_base = {
        BASE_ID: {
            ModId("c1"): [ModTierEntry(mod_id=ModId("c1"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())],
            **{mid: [ModTierEntry(mod_id=mid, base_id=BASE_ID, ilvl=1, weight=100, value_ranges=())] for mid in suffix_mods},
        }
    }
    gd = GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("c1"): corrupted_mod, **suffix_mods},
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )

    with pytest.raises(ItemReportError, match="not a prefix or suffix"):
        item_from_report(gd, BASE_ID, ilvl=1, rarity=Rarity.RARE, mod_reports=[(ModId("c1"), 1)])

    with pytest.raises(ItemReportError, match="allows at most"):
        item_from_report(
            gd, BASE_ID, ilvl=1, rarity=Rarity.RARE,
            mod_reports=[(ModId("s1"), 1), (ModId("s2"), 1), (ModId("s3"), 1), (ModId("s4"), 1)],
        )
