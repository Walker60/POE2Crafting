"""Real Divine-Orb-equivalent pricing: parsing poe2db.tw's Economy_divine
table, and Action.cost() looking prices up (with omen costs stacking
additively on the base currency's, since using an omen consumes both items)."""
from poe2craft.data.loader import GameData
from poe2craft.data.poe2db_parse import parse_economy_divine
from poe2craft.domain.actions import CurrencyTier
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity
from poe2craft.domain.mods import Affix, ModCategory, ModDef
from poe2craft.engine.apply import (
    DEFAULT_COSTS,
    FALLBACK_OMEN_COST,
    AnnulmentAction,
    ChaosAction,
    ExaltedAction,
    TransmutationAction,
)

# A tiny fragment matching the real page's row shape: "<24h Value> <name> <->
# 1 Divine Orb <24h volume traded>", tags stripped to '|' the same way the
# real table's cells are (icons/links interspersed, hence needing tag-strip
# rather than a strict per-cell parse).
_SAMPLE_HTML = """
<table><tbody>
<tr><td>10.2</td><td><a>Chaos Orb</a></td><td>1</td><td><a>Divine Orb</a></td><td>685,278</td></tr>
<tr><td>342.0</td><td><a>Exalted Orb</a></td><td>1</td><td><a>Divine Orb</a></td><td>107,290</td></tr>
<tr><td>26.4</td><td><a>Omen of Sinistral Exaltation</a></td><td>1</td><td><a>Divine Orb</a></td><td>500</td></tr>
<tr><th>24h Value</th><th>24h volume traded</th></tr>
</tbody></table>
"""


def test_parse_economy_divine_inverts_units_per_divine_to_divine_cost():
    prices = parse_economy_divine(_SAMPLE_HTML)
    assert abs(prices["Chaos Orb"] - 1 / 10.2) < 1e-9
    assert abs(prices["Exalted Orb"] - 1 / 342.0) < 1e-9
    assert prices["Divine Orb"] == 1.0


def test_parse_economy_divine_ignores_the_header_row():
    prices = parse_economy_divine(_SAMPLE_HTML)
    assert "24h Value" not in prices


# Items pricier than 1 Divine Orb are shown the other way around on the real
# page: "1 <name> <-> <qty_divine> Divine Orb" -- an earlier version of the
# parser required the divine-side quantity to be exactly "1" and silently
# dropped rows like this one (caught while pricing Desecration's bones).
_EXPENSIVE_ROW_HTML = """
<table><tbody>
<tr><td>1</td><td><a>Ancient Collarbone</a></td><td>4.76</td><td><a>Divine Orb</a></td><td>120</td></tr>
</tbody></table>
"""


def test_parse_economy_divine_handles_items_pricier_than_one_divine():
    prices = parse_economy_divine(_EXPENSIVE_ROW_HTML)
    assert abs(prices["Ancient Collarbone"] - 4.76) < 1e-9


BASE_ID = BaseId("b1")


def _gamedata(prices: dict[str, float]) -> GameData:
    mod = ModDef(id=ModId("p1"), name="P1", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"g1"}))
    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods={ModId("p1"): mod},
        tiers_by_base={},
        all_tiers_by_base={},
        prices=prices,
    )


def test_cost_uses_real_price_when_available():
    gd = _gamedata({"Orb of Transmutation": 0.0005})
    action = TransmutationAction(gd, tier=CurrencyTier.BASE)
    assert action.cost() == 0.0005


def test_cost_falls_back_to_placeholder_when_unpriced():
    gd = _gamedata({})
    action = TransmutationAction(gd, tier=CurrencyTier.BASE)
    assert action.cost() == DEFAULT_COSTS[action.kind]


def test_omen_cost_stacks_additively_on_base_currency_price():
    gd = _gamedata({"Exalted Orb": 0.003, "Omen of Dextral Exaltation": 0.027})
    base_action = ExaltedAction(gd)
    omen_action = ExaltedAction(gd, restrict=Affix.SUFFIX)
    assert base_action.cost() == 0.003
    assert abs(omen_action.cost() - (0.003 + 0.027)) < 1e-9
    assert omen_action.cost() > base_action.cost()  # using the omen is never cheaper than not


def test_unpriced_omen_falls_back_to_fallback_omen_cost_not_zero():
    gd = _gamedata({"Orb of Annulment": 0.45})
    action = AnnulmentAction(gd, restrict=Affix.SUFFIX)  # "Omen of Dextral Annulment" not in this fixture's prices
    assert abs(action.cost() - (0.45 + FALLBACK_OMEN_COST)) < 1e-9


def test_perfect_tier_falls_back_to_known_greater_price_not_a_guess():
    gd = _gamedata({"Chaos Orb": 0.1, "Greater Chaos Orb": 0.3})  # no "Perfect Chaos Orb" entry
    action = ChaosAction(gd, tier=CurrencyTier.PERFECT)
    assert action.cost() == 0.3  # falls back to the real Greater price, not base*multiplier
