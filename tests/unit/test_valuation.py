"""estimate_buy_price / estimate_sell_value / mod_premium's aggregation and
currency-normalization logic, against a fake TradeClient transport -- never
the real network. Query construction itself (`_build_query`) is exercised
indirectly via the URLs/bodies the fake transport records."""
from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef, Item, Rarity, RolledAffix
from poe2craft.domain.mods import Affix, ModCategory, ModDef
from poe2craft.pricing.config import TradeConfig
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.pricing.transport import RateLimiter
from poe2craft.pricing.valuation import estimate_buy_price, estimate_sell_value, mod_premium
from poe2craft.solver.featurize import ResolvedTarget, TargetModRequirement
from pricing_fakes import FakeResponse, FakeTransport

BASE_ID = BaseId("b1")
MOD_A = ModId("a1")
MOD_B = ModId("a2")

MOD_MAPPING = {MOD_A: "explicit.stat_a", MOD_B: "explicit.stat_b"}


def _gamedata(prices: dict[str, float] | None = None) -> GameData:
    mods = {
        MOD_A: ModDef(id=MOD_A, name="Mod A", affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({"ga"})),
        MOD_B: ModDef(id=MOD_B, name="Mod B", affix=Affix.SUFFIX, category=ModCategory.NORMAL, group_keys=frozenset({"gb"})),
    }
    return GameData(
        base_groups={BaseGroupId("bg1"): BaseGroup(id=BaseGroupId("bg1"), name="Test", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BaseGroupId("bg1"), is_jewellery=False)},
        mods=mods,
        tiers_by_base={},
        all_tiers_by_base={},
        prices=prices or {},
    )


def _client(responses: list[FakeResponse]) -> tuple[TradeClient, FakeTransport]:
    transport = FakeTransport(responses)
    client = TradeClient(TradeConfig(poesessid=None, league="Standard"), transport, rate_limiter=RateLimiter(sleep=lambda _: None))
    return client, transport


def _search_and_fetch(ids: list[str], listing_bodies: list[dict]) -> list[FakeResponse]:
    return [FakeResponse(200, {"id": "s1", "result": ids}), FakeResponse(200, {"result": listing_bodies})]


def _listing(entry_id: str, amount: float, currency: str = "divine") -> dict:
    return {"id": entry_id, "listing": {"price": {"amount": amount, "currency": currency}, "account": {"name": "acc"}}}


def test_estimate_buy_price_returns_the_single_cheapest_listing():
    gd = _gamedata()
    client, _ = _client(_search_and_fetch(["a", "b"], [_listing("a", 3.0), _listing("b", 5.0)]))
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert estimate.divine_price == 3.0
    assert estimate.n_listings == 2


def test_estimate_buy_price_reports_no_listings_found():
    gd = _gamedata()
    client, _ = _client(_search_and_fetch([], []))
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert estimate.divine_price is None
    assert any("no matching listings" in c for c in estimate.caveats)


def test_estimate_buy_price_flags_an_unmapped_base_category():
    gd = _gamedata()  # "Test Base" has no known trade category
    client, _ = _client(_search_and_fetch(["a"], [_listing("a", 3.0)]))
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert any("no known trade category" in c for c in estimate.caveats)


def test_estimate_buy_price_sends_the_mapped_category_not_an_exact_type():
    # "Amulet" (unlike the fixture's "Test Base") has a live-confirmed
    # category mapping -- see poe2craft.pricing.categories.
    amulet_base_id = BaseId("amulet_base")
    gd = _gamedata()
    gd.bases[amulet_base_id] = BaseItemDef(id=amulet_base_id, name="Amulet", bgroup_id=BaseGroupId("bg1"), is_jewellery=True)
    client, transport = _client(_search_and_fetch(["a"], [_listing("a", 3.0)]))
    target = ResolvedTarget(base_id=amulet_base_id, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)

    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert not any("no known trade category" in c for c in estimate.caveats)
    _method, _url, body, _headers = transport.calls[0]
    assert body["query"]["filters"]["type_filters"]["filters"]["category"] == {"option": "accessory.amulet"}
    assert "type" not in body["query"]  # the exact-base-type field this project can't use -- see valuation.py


def test_estimate_buy_price_flags_unmapped_target_mods():
    gd = _gamedata()
    client, _ = _client(_search_and_fetch(["a"], [_listing("a", 3.0)]))
    unmapped_mod = ModId("unmapped")
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=unmapped_mod),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert any("no known trade stat id" in c for c in estimate.caveats)


def test_estimate_buy_price_converts_non_divine_currency():
    gd = _gamedata(prices={"Exalted Orb": 0.01})  # 1 exalted = 0.01 divine
    client, _ = _client(_search_and_fetch(["a"], [_listing("a", 200.0, "exalted")]))
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert abs(estimate.divine_price - 2.0) < 1e-9  # 200 * 0.01


def test_estimate_buy_price_drops_listings_in_an_unrecognized_currency():
    gd = _gamedata()  # no price for "mystery"
    client, _ = _client(_search_and_fetch(["a", "b"], [_listing("a", 3.0), _listing("b", 999.0, "mystery")]))
    target = ResolvedTarget(base_id=BASE_ID, ilvl=80, target_mods=(TargetModRequirement(mod_id=MOD_A),), objective="cost", max_steps=30)
    estimate = estimate_buy_price(client, gd, MOD_MAPPING, target)
    assert estimate.n_listings == 1
    assert estimate.divine_price == 3.0


def _item_with_affixes() -> Item:
    prefix = RolledAffix(mod_id=MOD_A, affix=Affix.PREFIX, group_keys=frozenset({"ga"}), value_ranges=(), values=())
    return Item(base_id=BASE_ID, ilvl=80, rarity=Rarity.RARE, prefixes=(prefix,))


def test_estimate_sell_value_needs_at_least_three_comparable_listings():
    gd = _gamedata()
    client, _ = _client(_search_and_fetch(["a", "b"], [_listing("a", 3.0), _listing("b", 4.0)]))
    estimate = estimate_sell_value(client, gd, MOD_MAPPING, _item_with_affixes())
    assert estimate.divine_price is None
    assert any("fewer than 3" in c for c in estimate.caveats)


def test_estimate_sell_value_is_the_median_of_the_cheapest_three():
    gd = _gamedata()
    ids = ["a", "b", "c", "d"]
    bodies = [_listing("a", 1.0), _listing("b", 2.0), _listing("c", 3.0), _listing("d", 100.0)]
    client, _ = _client(_search_and_fetch(ids, bodies))
    estimate = estimate_sell_value(client, gd, MOD_MAPPING, _item_with_affixes())
    assert estimate.divine_price == 2.0  # median of the 3 cheapest (1, 2, 3), the 100 outlier excluded
    assert estimate.n_listings == 4


def test_mod_premium_is_the_difference_of_the_two_medians():
    gd = _gamedata()
    with_ids = ["w1", "w2", "w3"]
    without_ids = ["n1", "n2", "n3"]
    responses = [
        FakeResponse(200, {"id": "s1", "result": with_ids}),
        FakeResponse(200, {"result": [_listing(i, p) for i, p in zip(with_ids, [10.0, 11.0, 12.0])]}),
        FakeResponse(200, {"id": "s2", "result": without_ids}),
        FakeResponse(200, {"result": [_listing(i, p) for i, p in zip(without_ids, [4.0, 5.0, 6.0])]}),
    ]
    client, _ = _client(responses)
    estimate = mod_premium(client, gd, MOD_MAPPING, BASE_ID, MOD_A)
    assert abs(estimate.divine_price - (11.0 - 5.0)) < 1e-9


def test_mod_premium_reports_no_stat_id_without_querying():
    gd = _gamedata()
    client, transport = _client([])
    estimate = mod_premium(client, gd, {}, BASE_ID, MOD_A)
    assert estimate.divine_price is None
    assert transport.calls == []
