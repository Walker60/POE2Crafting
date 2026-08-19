"""The 11 omens added after the initial 4 (Dextral/Sinistral Annulment/
Exaltation): confirmed against poe2db.tw's omen catalog, see
domain.actions.OmenKind and docs/design_notes.md for what's still deferred.
Uses the shared `gamedata` fixture from conftest.py (BASE_ID, p1/p2/p3 prefix
mods, s1/s2/s3 suffix mods, hi_ilvl a high-ilvl-gated prefix)."""
import dataclasses
import random

from poe2craft.domain.ids import ModId
from poe2craft.domain.items import Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix
from poe2craft.engine.apply import AlchemyAction, AnnulmentAction, ChaosAction, ExaltedAction, RegalAction


def _item(gamedata, **kw):
    defaults = dict(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.NORMAL)
    defaults.update(kw)
    return Item(**defaults)


def test_sinistral_alchemy_maxes_out_prefixes_first(gamedata):
    action = AlchemyAction(gamedata, priority=Affix.PREFIX)
    for seed in range(20):
        item = action.outcome(_item(gamedata, rarity=Rarity.NORMAL), random.Random(seed))
        # Fixture has exactly 2 non-conflicting prefixes (p1/p2 share a group,
        # p3 is separate) so "max prefixes" tops out at 2, then fills the rest
        # (up to 4 total) with suffixes.
        assert item.prefix_count == 2
        assert item.prefix_count + item.suffix_count <= 4


def test_dextral_alchemy_maxes_out_suffixes_first(gamedata):
    action = AlchemyAction(gamedata, priority=Affix.SUFFIX)
    for seed in range(20):
        item = action.outcome(_item(gamedata, rarity=Rarity.NORMAL), random.Random(seed))
        assert item.suffix_count == 3  # s1/s2/s3 don't conflict, so all 3 fit
        assert item.prefix_count == 1  # remaining 1 of the 4 total


def test_regal_coronation_omen_restricts_added_affix(gamedata):
    action = RegalAction(gamedata, restrict=Affix.SUFFIX)
    item = _item(gamedata, rarity=Rarity.MAGIC)
    result = action.outcome(item, random.Random(0))
    assert result.rarity is Rarity.RARE
    assert result.suffix_count == 1 and result.prefix_count == 0
    assert "Regal Orb (Omen of Dextral Coronation)" == action.name


def test_greater_exaltation_adds_two_modifiers(gamedata):
    action = ExaltedAction(gamedata, count=2)
    item = _item(gamedata, rarity=Rarity.RARE)
    result = action.outcome(item, random.Random(1))
    assert len(result.affixes) == 2
    assert len(result.occupied_group_keys()) == 2  # both distinct, no exclusion violation


def test_greater_exaltation_stops_early_if_room_runs_out(gamedata):
    # p1/p3 are the only two non-conflicting prefixes the fixture has (p2
    # shares p1's group), so prefix room is already maxed out in practice even
    # though the 3-prefix cap isn't literally full. s1/s2 leave exactly one
    # suffix slot (s3) open -- so only ONE more affix can ever be added here,
    # and Greater Exaltation (count=2) must stop after adding it.
    prefixes = (
        RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=()),
        RolledAffix(mod_id=ModId("p3"), affix=Affix.PREFIX, group_keys=frozenset({"groupY"}), value_ranges=(), values=()),
    )
    suffixes = (
        RolledAffix(mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=()),
        RolledAffix(mod_id=ModId("s2"), affix=Affix.SUFFIX, group_keys=frozenset({"groupW"}), value_ranges=(), values=()),
    )
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=prefixes, suffixes=suffixes)
    action = ExaltedAction(gamedata, count=2)
    result = action.outcome(item, random.Random(2))
    assert result.prefix_count == 2  # untouched -- no eligible prefix mod was ever available
    assert result.suffix_count == 3  # exactly one added (s3), then the pool truly ran dry


def test_greater_annulment_removes_two_modifiers(gamedata):
    prefixes = (RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=()),)
    suffixes = (RolledAffix(mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=()),)
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=prefixes, suffixes=suffixes)
    action = AnnulmentAction(gamedata, count=2)
    result = action.outcome(item, random.Random(3))
    assert len(result.affixes) == 0


def test_greater_annulment_falls_back_to_however_many_exist(gamedata):
    prefixes = (RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=()),)
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=prefixes)
    action = AnnulmentAction(gamedata, count=2)
    result = action.outcome(item, random.Random(4))
    assert len(result.affixes) == 0  # only 1 existed; removes just that 1, doesn't crash


def test_chaos_erasure_omen_restricts_removal(gamedata):
    prefixes = (RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=()),)
    suffixes = (RolledAffix(mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=()),)
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=prefixes, suffixes=suffixes)
    action = ChaosAction(gamedata, restrict=Affix.SUFFIX)
    for seed in range(20):
        result = action.outcome(item, random.Random(seed))
        assert any(a.mod_id == ModId("p1") for a in result.prefixes)  # prefix untouched


def test_whittling_removes_the_lowest_level_modifier_deterministically(gamedata):
    low = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=(), ilvl=10)
    high = RolledAffix(mod_id=ModId("p3"), affix=Affix.PREFIX, group_keys=frozenset({"groupY"}), value_ranges=(), values=(), ilvl=80)
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(low, high))
    action = ChaosAction(gamedata, pick_lowest=True)
    for seed in range(20):
        result = action.outcome(item, random.Random(seed))
        # Checked by value, not mod_id: the add-back step could coincidentally
        # re-roll a *new* "p1" affix (different ilvl/values) once removing
        # `low` frees its group, which would make a mod_id-based check flaky.
        assert low not in result.prefixes  # the exact ilvl=10 affix is gone
        assert high in result.prefixes  # the exact ilvl=80 affix is untouched


def test_whittling_breaks_ties_randomly_not_by_insertion_order(gamedata):
    tied_a = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=(), ilvl=10)
    tied_b = RolledAffix(mod_id=ModId("p3"), affix=Affix.PREFIX, group_keys=frozenset({"groupY"}), value_ranges=(), values=(), ilvl=10)
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(tied_a, tied_b))
    action = ChaosAction(gamedata, pick_lowest=True)
    removed = set()
    for seed in range(30):
        result = action.outcome(item, random.Random(seed))
        if tied_a not in result.prefixes:
            removed.add("a")
        if tied_b not in result.prefixes:
            removed.add("b")
    assert removed == {"a", "b"}  # both sides of the tie get removed across enough trials


def test_omen_of_light_only_removes_desecrated_modifiers():
    # Bespoke gamedata (not the shared fixture, which has no DESECRATED-
    # category mod) with one Desecrated prefix and one Normal prefix present
    # on the same item.
    from poe2craft.data.loader import GameData
    from poe2craft.domain.ids import BaseGroupId, BaseId
    from poe2craft.domain.items import BaseGroup, BaseItemDef
    from poe2craft.domain.mods import ModCategory, ModDef

    base_id = BaseId("b1")
    bgroup_id = BaseGroupId("bg1")
    normal_mod = ModDef(id=ModId("n1"), name="Normal", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gn"}))
    desecrated_mod = ModDef(id=ModId("d1"), name="Desecrated", affix=Affix.PREFIX, category=ModCategory.DESECRATED, group_keys=frozenset({"gd"}))
    gamedata = GameData(
        base_groups={bgroup_id: BaseGroup(id=bgroup_id, name="Test", max_affix=6, max_sockets=0)},
        bases={base_id: BaseItemDef(id=base_id, name="Test Base", bgroup_id=bgroup_id, is_jewellery=False)},
        mods={ModId("n1"): normal_mod, ModId("d1"): desecrated_mod},
        tiers_by_base={},
        all_tiers_by_base={},
    )

    normal_affix = RolledAffix(mod_id=ModId("n1"), affix=Affix.PREFIX, group_keys=frozenset({"gn"}), value_ranges=(), values=())
    desecrated_affix = RolledAffix(mod_id=ModId("d1"), affix=Affix.PREFIX, group_keys=frozenset({"gd"}), value_ranges=(), values=())
    item = Item(base_id=base_id, ilvl=1, rarity=Rarity.RARE, prefixes=(normal_affix, desecrated_affix))

    action = AnnulmentAction(gamedata, restrict_category=ModCategory.DESECRATED)
    assert action.name == "Orb of Annulment (Omen of Light)"
    for seed in range(20):
        result = action.outcome(item, random.Random(seed))
        assert normal_affix in result.prefixes  # untouched -- not Desecrated
        assert desecrated_affix not in result.prefixes  # the only removable candidate
