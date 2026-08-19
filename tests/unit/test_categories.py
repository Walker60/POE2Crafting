"""trade_category_for's exact-name lookup -- see the module docstring for
why this is exact-match, not prefix/substring (a substring version silently
collapsed One/Two-Handed Mace onto the same wrong category)."""
from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId
from poe2craft.domain.items import BaseGroup, BaseItemDef
from poe2craft.pricing.categories import trade_category_for

BGROUP_ID = BaseGroupId("bg1")


def _gamedata_with_bases(names: dict[str, str]) -> tuple[GameData, dict[str, BaseId]]:
    """`names`: {label: base_name} -> (gamedata, {label: base_id})."""
    ids = {label: BaseId(label) for label in names}
    bases = {ids[label]: BaseItemDef(id=ids[label], name=name, bgroup_id=BGROUP_ID, is_jewellery=False) for label, name in names.items()}
    gd = GameData(
        base_groups={BGROUP_ID: BaseGroup(id=BGROUP_ID, name="Test", max_affix=6, max_sockets=0)},
        bases=bases,
        mods={},
        tiers_by_base={},
        all_tiers_by_base={},
    )
    return gd, ids


def test_amulet_maps_to_the_live_confirmed_category():
    gd, ids = _gamedata_with_bases({"amulet": "Amulet"})
    assert trade_category_for(gd, ids["amulet"]) == "accessory.amulet"


def test_one_and_two_hand_mace_map_to_distinct_categories():
    gd, ids = _gamedata_with_bases({"one": "One Hand Mace", "two": "Two Hand Mace"})
    assert trade_category_for(gd, ids["one"]) == "weapon.onemace"
    assert trade_category_for(gd, ids["two"]) == "weapon.twomace"
    assert trade_category_for(gd, ids["one"]) != trade_category_for(gd, ids["two"])


def test_unmapped_base_returns_none_rather_than_guessing():
    gd, ids = _gamedata_with_bases({"waystone": "Low Tier (1-5)"})
    assert trade_category_for(gd, ids["waystone"]) is None
