"""Desecration (bone) actions -- the first action type in this codebase where
the outcome is a *choice* among several revealed candidates rather than a
single random draw. Bespoke fixture (not the shared conftest.py one) since
this needs realistic bgroup names for the slot-family matching logic and a
real DESECRATED-category mod pool."""
import random

import pytest

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.actions import BoneFamily, BoneTier
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.apply import DesecrationAction, _bone_family_matches
from poe2craft.engine.sampler import weighted_sample_without_replacement
from poe2craft.solver.featurize import resolve_target

WEAPON_BASE = BaseId("w1")
QUIVER_BASE = BaseId("q1")
SHIELD_BASE = BaseId("s1")
WEAPON_BG = BaseGroupId("bg_weapon")
OFFHAND_BG = BaseGroupId("bg_offhand")


def _desecrated_mod(mid: str, affix: Affix, group: str) -> ModDef:
    return ModDef(id=ModId(mid), name=f"Desecrated {mid}", affix=affix, category=ModCategory.DESECRATED, group_keys=frozenset({group}))


def _normal_mod(mid: str, affix: Affix, group: str) -> ModDef:
    return ModDef(id=ModId(mid), name=f"Normal {mid}", affix=affix, category=ModCategory.NORMAL, group_keys=frozenset({group}))


def _tier(mid: str, base_id: BaseId, ilvl: int, weight: int = 100) -> ModTierEntry:
    return ModTierEntry(mod_id=ModId(mid), base_id=base_id, ilvl=ilvl, weight=weight, value_ranges=((1.0, 2.0),))


@pytest.fixture
def gamedata() -> GameData:
    mods = {
        ModId("d1"): _desecrated_mod("d1", Affix.PREFIX, "gd1"),
        ModId("d2"): _desecrated_mod("d2", Affix.PREFIX, "gd2"),
        ModId("d3"): _desecrated_mod("d3", Affix.SUFFIX, "gd3"),
        ModId("d_hi"): _desecrated_mod("d_hi", Affix.PREFIX, "gd_hi"),  # tier requires ilvl 70 -- blocked by Gnawed's <=64 item cap
        ModId("d_lo"): _desecrated_mod("d_lo", Affix.PREFIX, "gd_lo"),  # tier at ilvl 10 -- below Ancient's min_ilvl=40 floor
        ModId("n1"): _normal_mod("n1", Affix.PREFIX, "gn1"),
    }
    weapon_tiers = {
        ModId("d1"): [_tier("d1", WEAPON_BASE, 10)],
        ModId("d2"): [_tier("d2", WEAPON_BASE, 10)],
        ModId("d3"): [_tier("d3", WEAPON_BASE, 10)],
        ModId("d_hi"): [_tier("d_hi", WEAPON_BASE, 70)],
        ModId("d_lo"): [_tier("d_lo", WEAPON_BASE, 10)],
        ModId("n1"): [_tier("n1", WEAPON_BASE, 1)],
    }
    all_tiers = {
        WEAPON_BASE: weapon_tiers,
        QUIVER_BASE: {ModId("d1"): [_tier("d1", QUIVER_BASE, 10)]},
        SHIELD_BASE: {ModId("d1"): [_tier("d1", SHIELD_BASE, 10)]},
    }
    rollable = {WEAPON_BASE: {ModId("n1"): weapon_tiers[ModId("n1")]}}
    return GameData(
        base_groups={
            WEAPON_BG: BaseGroup(id=WEAPON_BG, name="One-Handed Weapons", max_affix=6, max_sockets=0),
            OFFHAND_BG: BaseGroup(id=OFFHAND_BG, name="Offhands", max_affix=6, max_sockets=0),
        },
        bases={
            WEAPON_BASE: BaseItemDef(id=WEAPON_BASE, name="One Hand Sword", bgroup_id=WEAPON_BG, is_jewellery=False),
            QUIVER_BASE: BaseItemDef(id=QUIVER_BASE, name="Quiver", bgroup_id=OFFHAND_BG, is_jewellery=False),
            SHIELD_BASE: BaseItemDef(id=SHIELD_BASE, name="Shield (STR)", bgroup_id=OFFHAND_BG, is_jewellery=False),
        },
        mods=mods,
        tiers_by_base=rollable,
        all_tiers_by_base=all_tiers,
    )


def test_bone_family_matches_weapon_bgroup(gamedata):
    assert _bone_family_matches(gamedata, WEAPON_BASE, BoneFamily.JAWBONE)
    assert not _bone_family_matches(gamedata, WEAPON_BASE, BoneFamily.RIB)


def test_bone_family_matches_quiver_via_jawbone_special_case(gamedata):
    assert _bone_family_matches(gamedata, QUIVER_BASE, BoneFamily.JAWBONE)


def test_bone_family_matches_shield_via_rib_special_case(gamedata):
    assert _bone_family_matches(gamedata, SHIELD_BASE, BoneFamily.RIB)
    assert not _bone_family_matches(gamedata, SHIELD_BASE, BoneFamily.JAWBONE)


def test_applicable_requires_rare_and_matching_family(gamedata):
    action = DesecrationAction(gamedata, BoneFamily.JAWBONE, BoneTier.PRESERVED)
    normal_item = Item(base_id=WEAPON_BASE, ilvl=50, rarity=Rarity.NORMAL)
    rare_item = Item(base_id=WEAPON_BASE, ilvl=50, rarity=Rarity.RARE)
    wrong_family_item = Item(base_id=SHIELD_BASE, ilvl=50, rarity=Rarity.RARE)
    assert not action.applicable(normal_item)
    assert action.applicable(rare_item)
    assert not action.applicable(wrong_family_item)


def test_gnawed_tier_caps_item_ilvl(gamedata):
    action = DesecrationAction(gamedata, BoneFamily.JAWBONE, BoneTier.GNAWED)
    low_item = Item(base_id=WEAPON_BASE, ilvl=64, rarity=Rarity.RARE)
    high_item = Item(base_id=WEAPON_BASE, ilvl=65, rarity=Rarity.RARE)
    assert action.applicable(low_item)
    assert not action.applicable(high_item)


def test_ancient_tier_only_reveals_mods_meeting_the_min_ilvl_floor(gamedata):
    action = DesecrationAction(gamedata, BoneFamily.JAWBONE, BoneTier.ANCIENT)
    item = Item(base_id=WEAPON_BASE, ilvl=80, rarity=Rarity.RARE)
    rng = random.Random(0)
    seen_mod_ids: set[str] = set()
    for _ in range(20):  # weighted sampling -- run enough trials to be confident d_lo never appears
        candidates = action.reveal_candidates(item, rng)
        for c in candidates:
            seen_mod_ids.update(a.mod_id for a in c.affixes)
    assert "d_lo" not in seen_mod_ids  # tier ilvl 10 < Ancient's min_ilvl=40
    assert "d_hi" in seen_mod_ids  # tier ilvl 70 >= 40, eligible


def test_reveal_candidates_returns_distinct_options(gamedata):
    action = DesecrationAction(gamedata, BoneFamily.JAWBONE, BoneTier.PRESERVED)
    item = Item(base_id=WEAPON_BASE, ilvl=80, rarity=Rarity.RARE)
    rng = random.Random(1)
    candidates = action.reveal_candidates(item, rng)
    assert len(candidates) == 3
    revealed_mod_ids = [next(iter(c.mod_ids - item.mod_ids)) for c in candidates]
    assert len(set(revealed_mod_ids)) == len(revealed_mod_ids)  # no duplicate reveal


def test_reveal_candidates_makes_room_when_item_is_full(gamedata):
    def _filler(mid: str, affix: Affix, group: str) -> RolledAffix:
        return RolledAffix(mod_id=ModId(mid), affix=affix, group_keys=frozenset({group}), value_ranges=(), values=())

    item = Item(
        base_id=WEAPON_BASE,
        ilvl=80,
        rarity=Rarity.RARE,
        prefixes=tuple(_filler(f"fp{i}", Affix.PREFIX, f"gfp{i}") for i in range(3)),
        suffixes=tuple(_filler(f"fs{i}", Affix.SUFFIX, f"gfs{i}") for i in range(3)),
    )
    action = DesecrationAction(gamedata, BoneFamily.JAWBONE, BoneTier.PRESERVED)
    assert action.applicable(item)
    rng = random.Random(2)
    candidates = action.reveal_candidates(item, rng)
    assert candidates  # actually revealed something, not the empty-pool no-op path
    for c in candidates:
        assert c.prefix_count + c.suffix_count == 6  # one removed, one added -- still at the cap, not 7


def test_reveal_candidates_degrades_to_a_no_op_when_pool_is_empty_after_removal():
    # A base with NO desecrated mods at all -- applicable() only requires
    # "something removable exists" when full, so reveal_candidates must
    # handle finding an empty pool gracefully rather than crashing.
    bg = BaseGroupId("bg")
    base_id = BaseId("empty")
    gd = GameData(
        base_groups={bg: BaseGroup(id=bg, name="One-Handed Weapons", max_affix=6, max_sockets=0)},
        bases={base_id: BaseItemDef(id=base_id, name="Empty Sword", bgroup_id=bg, is_jewellery=False)},
        mods={},
        tiers_by_base={},
        all_tiers_by_base={},
    )

    def _filler(mid: str, affix: Affix, group: str) -> RolledAffix:
        return RolledAffix(mod_id=ModId(mid), affix=affix, group_keys=frozenset({group}), value_ranges=(), values=())

    item = Item(
        base_id=base_id,
        ilvl=80,
        rarity=Rarity.RARE,
        prefixes=tuple(_filler(f"fp{i}", Affix.PREFIX, f"gfp{i}") for i in range(3)),
        suffixes=tuple(_filler(f"fs{i}", Affix.SUFFIX, f"gfs{i}") for i in range(3)),
    )
    action = DesecrationAction(gd, BoneFamily.JAWBONE, BoneTier.PRESERVED)
    assert action.applicable(item)  # full, but something is still removable
    result = action.reveal_candidates(item, random.Random(0))
    # Room-making still happens (a real, if wasted, use of the bone) -- the
    # "no-op" part is specifically that nothing new gets added afterward,
    # since there's nothing eligible to reveal for this base at all.
    assert len(result) == 1
    resulting_item = result[0]
    assert resulting_item.prefix_count + resulting_item.suffix_count == 5
    assert resulting_item.mod_ids <= item.mod_ids


def test_resolve_target_accepts_a_desecrated_mod_as_reachable(gamedata):
    spec = TargetSpec(base="One Hand Sword", ilvl=80, target_mods=[TargetModSpec(mod_id="d1")])
    target = resolve_target(gamedata, spec)
    assert target.target_mods[0].mod_id == "d1"


def test_weighted_sample_without_replacement_never_duplicates_and_caps_at_pool_size():
    mod_a = ModDef(id=ModId("a"), name="A", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset())
    pool = [(mod_a, _tier("a", WEAPON_BASE, ilvl=i, weight=10)) for i in range(5)]
    rng = random.Random(0)
    picks = weighted_sample_without_replacement(pool, 10, rng)  # more than the pool has
    assert len(picks) == 5  # capped, not raising
    assert len(set(picks)) == 5  # every entry distinct
