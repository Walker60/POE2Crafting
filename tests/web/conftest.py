"""Small hand-built GameData + FastAPI TestClient fixtures for the web API
tests -- independent of the real vendored dataset, so these stay fast."""
import pytest
from fastapi.testclient import TestClient

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseGroupId, BaseId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry
from poe2craft.web.app import create_app

BASE_ID = BaseId("base1")
BGROUP_ID = BaseGroupId("bg1")


def _mod(mid: str, affix: Affix, group: str) -> ModDef:
    return ModDef(id=ModId(mid), name=f"Mod {mid}", affix=affix, category=ModCategory.NORMAL, group_keys=frozenset({group}))


def _tier(mid: str, ilvl: int = 1, weight: int = 100) -> ModTierEntry:
    return ModTierEntry(mod_id=ModId(mid), base_id=BASE_ID, ilvl=ilvl, weight=weight, value_ranges=((1.0, 2.0),))


@pytest.fixture
def gamedata() -> GameData:
    mods = {
        ModId("p1"): _mod("p1", Affix.PREFIX, "groupX"),
        ModId("p2"): _mod("p2", Affix.PREFIX, "groupY"),
        ModId("s1"): _mod("s1", Affix.SUFFIX, "groupZ"),
        ModId("s2"): _mod("s2", Affix.SUFFIX, "groupW"),
    }
    tiers_by_base = {
        BASE_ID: {
            ModId("p1"): [_tier("p1")],
            ModId("p2"): [_tier("p2")],
            ModId("s1"): [_tier("s1")],
            ModId("s2"): [_tier("s2", ilvl=50)],  # only eligible on a high-ilvl item
        }
    }
    return GameData(
        base_groups={BGROUP_ID: BaseGroup(id=BGROUP_ID, name="Test Group", max_affix=6, max_sockets=0)},
        bases={BASE_ID: BaseItemDef(id=BASE_ID, name="Test Base", bgroup_id=BGROUP_ID, is_jewellery=False)},
        mods=mods,
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=tiers_by_base,
    )


@pytest.fixture
def app(gamedata):
    return create_app(gamedata=gamedata)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
