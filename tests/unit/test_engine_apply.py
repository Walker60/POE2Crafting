import dataclasses
import random

from poe2craft.domain.items import Item, Rarity
from poe2craft.domain.mods import Affix
from poe2craft.engine.apply import AlchemyAction, AnnulmentAction, DivineAction, FractureAction, TransmutationAction
from poe2craft.engine.pool import build_pool, has_room

from poe2craft.domain.ids import ModId


def _item(gamedata, **kw):
    defaults = dict(base_id=next(iter(gamedata.bases)), ilvl=1, rarity=Rarity.NORMAL)
    defaults.update(kw)
    return Item(**defaults)


def test_group_exclusion_blocks_sibling_mod(gamedata):
    item = _item(gamedata, rarity=Rarity.RARE)
    # simulate p1 already present
    from poe2craft.domain.items import RolledAffix

    p1_affix = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=())
    item = dataclasses.replace(item, prefixes=(p1_affix,))
    pool = build_pool(gamedata, item, Affix.PREFIX)
    ids = {m.id for m, _ in pool}
    assert ModId("p2") not in ids  # shares "groupX" with p1
    assert ModId("p3") in ids


def test_ilvl_gating(gamedata):
    low_item = _item(gamedata, ilvl=1, rarity=Rarity.RARE)
    high_item = _item(gamedata, ilvl=100, rarity=Rarity.RARE)
    low_ids = {m.id for m, _ in build_pool(gamedata, low_item, Affix.PREFIX)}
    high_ids = {m.id for m, _ in build_pool(gamedata, high_item, Affix.PREFIX)}
    assert ModId("hi_ilvl") not in low_ids
    assert ModId("hi_ilvl") in high_ids


def test_magic_caps_at_one_per_affix_regardless_of_base_group(gamedata):
    from poe2craft.domain.items import RolledAffix

    item = _item(gamedata, rarity=Rarity.MAGIC)
    assert has_room(gamedata, item, Affix.PREFIX)
    filled = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=())
    item = dataclasses.replace(item, prefixes=(filled,))
    assert not has_room(gamedata, item, Affix.PREFIX)  # magic caps at 1 prefix even though base group allows 3


def test_transmutation_moves_normal_to_magic_with_one_affix(gamedata):
    rng = random.Random(0)
    action = TransmutationAction(gamedata)
    item = _item(gamedata, rarity=Rarity.NORMAL)
    assert action.applicable(item)
    result = action.outcome(item, rng)
    assert result.rarity is Rarity.MAGIC
    assert len(result.affixes) == 1


def test_alchemy_never_violates_group_exclusion_or_caps(gamedata):
    action = AlchemyAction(gamedata)
    for seed in range(30):
        rng = random.Random(seed)
        item = _item(gamedata, rarity=Rarity.NORMAL)
        result = action.outcome(item, rng)
        assert result.rarity is Rarity.RARE
        assert len(result.affixes) <= 4
        assert result.prefix_count <= 3 and result.suffix_count <= 3
        # no two affixes may share a group -- occupied_group_keys collapses
        # duplicates, so this catches any exclusion violation.
        assert len(result.occupied_group_keys()) == len(result.affixes)


def test_annulment_removes_exactly_one_affix(gamedata):
    from poe2craft.domain.items import RolledAffix

    p1 = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=())
    s1 = RolledAffix(mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=())
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(p1,), suffixes=(s1,))
    action = AnnulmentAction(gamedata)
    rng = random.Random(3)
    result = action.outcome(item, rng)
    assert len(result.affixes) == 1


def test_annulment_omen_restricts_to_suffix(gamedata):
    from poe2craft.domain.items import RolledAffix

    p1 = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=())
    s1 = RolledAffix(mod_id=ModId("s1"), affix=Affix.SUFFIX, group_keys=frozenset({"groupZ"}), value_ranges=(), values=())
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(p1,), suffixes=(s1,))
    action = AnnulmentAction(gamedata, restrict=Affix.SUFFIX)
    for seed in range(20):
        result = action.outcome(item, random.Random(seed))
        assert result.prefix_count == 1  # prefix untouched
        assert result.suffix_count == 0  # suffix always removed


def test_fracture_marks_one_mod_and_then_blocks_further_fracturing(gamedata):
    from poe2craft.domain.items import RolledAffix

    p1 = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=(), values=())
    p3 = RolledAffix(mod_id=ModId("p3"), affix=Affix.PREFIX, group_keys=frozenset({"groupY"}), value_ranges=(), values=())
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(p1, p3))
    action = FractureAction(gamedata)
    assert action.applicable(item)
    result = action.outcome(item, random.Random(5))
    assert sum(1 for a in result.affixes if a.fractured) == 1
    assert not action.applicable(result)  # already has a fracture


def test_divine_rerolls_values_but_not_mod_identity(gamedata):
    from poe2craft.domain.items import RolledAffix

    p1 = RolledAffix(mod_id=ModId("p1"), affix=Affix.PREFIX, group_keys=frozenset({"groupX"}), value_ranges=((10.0, 20.0),), values=(15.0,))
    item = _item(gamedata, rarity=Rarity.RARE, prefixes=(p1,))
    action = DivineAction(gamedata)
    result = action.outcome(item, random.Random(9))
    assert result.prefixes[0].mod_id == ModId("p1")
    assert 10.0 <= result.prefixes[0].values[0] <= 20.0
