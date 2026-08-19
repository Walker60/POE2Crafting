"""`item_text.parse_item_text` -- turning pasted PoE2 item-clipboard text into
pre-fillable (base, ilvl, rarity, mod_reports) fields. Bespoke small GameData
here (not the shared `conftest.py` fixture) since these tests need realistic
`#`-templated mod names, multiple tiers per mod, and base names that actually
look like real archetypes (e.g. "Body Armour (STR)") to exercise the
Item-Class/Requirements resolution heuristics."""
import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Rarity
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.solver.item_text import ItemTextParseError, parse_item_text

AMULET = BaseId("amulet")
BA_STR = BaseId("ba_str")
BA_DEX = BaseId("ba_dex")


def _mod(mid: str, name: str, affix: Affix) -> ModDef:
    return ModDef(id=ModId(mid), name=name, affix=affix, category=ModCategory.NORMAL, group_keys=frozenset({f"g_{mid}"}))


def _tier(base_id: BaseId, mid: str, ilvl: int, *ranges: tuple[float, float]) -> ModTierEntry:
    return ModTierEntry(mod_id=ModId(mid), base_id=base_id, ilvl=ilvl, weight=100, value_ranges=ranges)


@pytest.fixture
def gamedata() -> GameData:
    mods = {
        ModId("inc_armour"): _mod("inc_armour", "#% increased Armour", Affix.PREFIX),
        ModId("max_mana"): _mod("max_mana", "+# to maximum Mana", Affix.SUFFIX),
        ModId("added_phys"): _mod("added_phys", "Adds # to # Physical Damage to Attacks", Affix.PREFIX),
    }
    tiers_by_base = {
        AMULET: {
            ModId("inc_armour"): [_tier(AMULET, "inc_armour", 2, (10.0, 19.0)), _tier(AMULET, "inc_armour", 46, (30.0, 39.0))],
            ModId("max_mana"): [_tier(AMULET, "max_mana", 1, (20.0, 29.0))],
            ModId("added_phys"): [_tier(AMULET, "added_phys", 1, (5.0, 15.0), (15.0, 25.0))],
        }
    }
    return GameData(
        base_groups={
            BaseGroupId("jewellery"): BaseGroup(id=BaseGroupId("jewellery"), name="Jewellery", max_affix=6, max_sockets=0),
            BaseGroupId("body"): BaseGroup(id=BaseGroupId("body"), name="Body Armours", max_affix=6, max_sockets=0),
        },
        bases={
            AMULET: BaseItemDef(id=AMULET, name="Amulet", bgroup_id=BaseGroupId("jewellery"), is_jewellery=True),
            BA_STR: BaseItemDef(id=BA_STR, name="Body Armour (STR)", bgroup_id=BaseGroupId("body"), is_jewellery=False),
            BA_DEX: BaseItemDef(id=BA_DEX, name="Body Armour (DEX)", bgroup_id=BaseGroupId("body"), is_jewellery=False),
        },
        mods=mods,
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )


def test_direct_item_class_stem_match(gamedata):
    text = "Item Class: Amulets\nRarity: Normal\nSome Amulet\n--------\nItem Level: 20\n"
    parsed = parse_item_text(gamedata, text)
    assert parsed.base_id == AMULET
    assert parsed.ilvl == 20
    assert parsed.rarity is Rarity.NORMAL


def test_ambiguous_archetype_without_requirements(gamedata):
    text = "Item Class: Body Armours\nRarity: Rare\nSome Armour\n--------\nItem Level: 40\n"
    parsed = parse_item_text(gamedata, text)
    assert parsed.base_id is None
    assert {b.id for b in parsed.ambiguous_bases} == {BA_STR, BA_DEX}


def test_requirements_heuristic_resolves_ambiguity(gamedata):
    text = (
        "Item Class: Body Armours\nRarity: Rare\nSome Armour\n--------\n"
        "Requirements:\nLevel: 60\nStr: 100\n--------\nItem Level: 40\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.base_id == BA_STR


def test_unique_rarity_rejected(gamedata):
    text = "Item Class: Amulets\nRarity: Unique\nSome Amulet\n--------\nItem Level: 20\n"
    with pytest.raises(ItemTextParseError, match="Unique"):
        parse_item_text(gamedata, text)


def test_full_parse_of_a_rare_amulet(gamedata):
    text = (
        "Item Class: Amulets\nRarity: Rare\nDoom Pendant\nAmulet\n--------\n"
        "Item Level: 50\n--------\n15% increased Armour\n+24 to maximum Mana\n--------\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.base_id == AMULET
    assert parsed.ilvl == 50
    assert parsed.rarity is Rarity.RARE
    assert set(parsed.mod_reports) == {(ModId("inc_armour"), 2), (ModId("max_mana"), 1)}
    assert parsed.unmatched_lines == []


def test_tier_annotation_takes_priority_over_value_matching(gamedata):
    # 100% doesn't fall in either tier's value_ranges (10-19 / 30-39) -- but a
    # "(Tier: 1)" annotation should resolve directly via tier_ranks (T1 = the
    # highest-ilvl tier, ilvl=46) without needing the value to fit.
    text = (
        "Item Class: Amulets\nRarity: Rare\nAmulet\n--------\n"
        "Item Level: 50\n--------\n100% increased Armour (Tier: 1)\n--------\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.mod_reports == [(ModId("inc_armour"), 46)]


def test_unmatched_line_is_reported_not_dropped(gamedata):
    text = (
        "Item Class: Amulets\nRarity: Rare\nAmulet\n--------\n"
        "Item Level: 50\n--------\n15% increased Armour\nSome Unrecognized Modifier Text\n--------\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.mod_reports == [(ModId("inc_armour"), 2)]
    assert parsed.unmatched_lines == ["Some Unrecognized Modifier Text"]


def test_implicit_line_is_silently_skipped(gamedata):
    text = (
        "Item Class: Amulets\nRarity: Rare\nAmulet\n--------\n"
        "Item Level: 50\n--------\n+16 to maximum Life (implicit)\n15% increased Armour\n--------\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.mod_reports == [(ModId("inc_armour"), 2)]
    assert parsed.unmatched_lines == []  # the implicit is known-and-ignored, not a parse failure


def test_two_value_mod_is_parsed(gamedata):
    text = (
        "Item Class: Amulets\nRarity: Rare\nAmulet\n--------\n"
        "Item Level: 50\n--------\nAdds 10 to 20 Physical Damage to Attacks\n--------\n"
    )
    parsed = parse_item_text(gamedata, text)
    assert parsed.mod_reports == [(ModId("added_phys"), 1)]


def test_forced_base_id_skips_autodetection(gamedata):
    text = "Item Class: Nonsense\nRarity: Rare\nWhatever\n--------\nItem Level: 50\n--------\n15% increased Armour\n--------\n"
    parsed = parse_item_text(gamedata, text, base_id=AMULET)
    assert parsed.base_id == AMULET
    assert parsed.mod_reports == [(ModId("inc_armour"), 2)]


def test_normal_rarity_never_attempts_mod_parsing(gamedata):
    text = "Item Class: Amulets\nRarity: Normal\nAmulet\n--------\nItem Level: 50\n--------\n15% increased Armour\n--------\n"
    parsed = parse_item_text(gamedata, text)
    assert parsed.mod_reports == []
    assert parsed.unmatched_lines == []


def test_missing_item_level_leaves_ilvl_none_but_still_parses_mods(gamedata):
    text = "Item Class: Amulets\nRarity: Rare\nAmulet\n--------\n15% increased Armour\n--------\n"
    parsed = parse_item_text(gamedata, text)
    assert parsed.ilvl is None
    assert parsed.mod_reports == [(ModId("inc_armour"), 2)]


def test_empty_text_raises():
    with pytest.raises(ItemTextParseError):
        parse_item_text(GameData(base_groups={}, bases={}, mods={}), "   ")
