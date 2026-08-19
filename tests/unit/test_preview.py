"""Action.preview()'s pre-commit odds preview -- see docs/design_notes.md
for exactly which action kinds this covers (single weighted-draw currencies,
plus essence's guaranteed grant as its own non-probabilistic case) and which
are deliberately excluded (Alchemy, Greater Exaltation, Annulment/Chaos,
Desecration) because they aren't a single clean draw."""
import pytest

from poe2craft.data.loader import GameData
from poe2craft.domain.actions import BoneFamily, BoneTier
from poe2craft.domain.essences import EssenceDef, EssenceGrant, EssenceTierKind
from poe2craft.domain.ids import BaseGroupId, BaseId, EssenceId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.engine.apply import (
    AlchemyAction,
    AnnulmentAction,
    ChaosAction,
    DesecrationAction,
    EssenceAction,
    ExaltedAction,
    RegalAction,
    TransmutationAction,
)


def test_transmutation_preview_sums_to_one_and_matches_pool_weights(gamedata):
    action = TransmutationAction(gamedata)
    item = Item(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.NORMAL)

    result = action.preview(item)

    assert result is not None
    assert result.guaranteed == []
    total_weight = sum(e.weight for e in result.entries)
    assert total_weight > 0
    probabilities = [e.weight / total_weight for e in result.entries]
    assert abs(sum(probabilities) - 1.0) < 1e-9
    assert {e.mod_id for e in result.entries} == {ModId("p1"), ModId("p2"), ModId("p3"), ModId("s1"), ModId("s2"), ModId("s3")}


def test_transmutation_preview_is_none_off_a_non_normal_item(gamedata):
    action = TransmutationAction(gamedata)
    item = Item(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.MAGIC)
    assert action.preview(item) is None


def test_regal_preview_with_restrict_only_returns_that_affix_side(gamedata):
    action = RegalAction(gamedata, restrict=Affix.SUFFIX)
    item = Item(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.MAGIC)

    result = action.preview(item)

    assert result is not None
    assert {e.mod_id for e in result.entries} == {ModId("s1"), ModId("s2"), ModId("s3")}


def test_exalted_preview_available_for_a_single_draw(gamedata):
    action = ExaltedAction(gamedata, count=1)
    item = Item(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.RARE)
    result = action.preview(item)
    assert result is not None
    assert result.entries


def test_exalted_preview_unavailable_for_greater_exaltation(gamedata):
    # count=2 (Omen of Greater Exaltation): the second draw's pool depends
    # on the first draw's outcome -- a single preview can't describe it.
    action = ExaltedAction(gamedata, count=2)
    item = Item(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.RARE)
    assert action.preview(item) is None


def test_alchemy_has_no_preview_method_at_all(gamedata):
    # Always multi-draw (fills up to 4 affixes), regardless of any omen --
    # deliberately not given a preview() method rather than a misleading one.
    action = AlchemyAction(gamedata)
    assert not hasattr(action, "preview")


def test_annulment_and_chaos_have_no_preview_method_at_all(gamedata):
    # Uniform pick among the item's *existing* affixes, not a weighted-pool draw.
    assert not hasattr(AnnulmentAction(gamedata), "preview")
    assert not hasattr(ChaosAction(gamedata), "preview")


def test_desecration_has_no_preview_method_at_all(gamedata):
    # Samples 3-6 candidates *without replacement* -- genuinely different
    # combinatorics than a simple normalize-by-weight draw.
    action = DesecrationAction(gamedata, family=BoneFamily.JAWBONE, tier=BoneTier.PRESERVED)
    assert not hasattr(action, "preview")


BASE_ID = BaseId("eb1")


@pytest.fixture
def essence_gamedata() -> GameData:
    normal_mod = ModDef(id=ModId("normal1"), name="Normal Mod", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gNormal"}))
    normal_tier = ModTierEntry(mod_id=ModId("normal1"), base_id=BASE_ID, ilvl=1, weight=100, value_ranges=((1.0, 2.0),))
    essence = EssenceDef(
        id=EssenceId("e1"),
        name="Essence of Testing",
        family="Essence of Testing",
        tier_kind=EssenceTierKind.NORMAL,
        per_base={BASE_ID: (EssenceGrant(mod_id=ModId("normal1"), ilvl=1),)},
    )
    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("normal1"): normal_mod},
        tiers_by_base={BASE_ID: {ModId("normal1"): [normal_tier]}},
        all_tiers_by_base={BASE_ID: {ModId("normal1"): [normal_tier]}},
        essences=[essence],
    )


def test_essence_preview_reports_the_guaranteed_grant_not_odds(essence_gamedata):
    action = EssenceAction(essence_gamedata, essence_gamedata.essences[0], BASE_ID)
    item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.MAGIC)

    result = action.preview(item)

    assert result is not None
    assert result.entries == []
    assert len(result.guaranteed) == 1
    assert result.guaranteed[0].mod_id == ModId("normal1")
    assert result.guaranteed[0].tier_ilvl == 1


def test_essence_preview_is_none_when_not_applicable(essence_gamedata):
    action = EssenceAction(essence_gamedata, essence_gamedata.essences[0], BASE_ID)
    normal_item = Item(base_id=BASE_ID, ilvl=10, rarity=Rarity.NORMAL)  # essences never act on Normal items
    assert action.preview(normal_item) is None
