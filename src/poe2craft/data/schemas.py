"""Pydantic v2 schemas -- used only at I/O boundaries: validating our own compiled
`data/compiled/poe2_gamedata.json` (guards against schema drift between the build
script and the loader) and validating user-authored CLI target-spec YAML files.
Everything past these boundaries uses the plain dataclasses in `poe2craft.domain`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SourceMeta(BaseModel):
    name: str
    url: str
    fetched_at: str
    sha256: str | None = None


class GameDataMeta(BaseModel):
    built_at: str
    sources: list[SourceMeta]


class BaseGroupRecord(BaseModel):
    id: str
    name: str
    max_affix: int
    max_sockets: int


class BaseItemRecord(BaseModel):
    id: str
    name: str
    bgroup_id: str
    is_jewellery: bool


class ModRecord(BaseModel):
    id: str
    name: str
    affix: str
    category: str
    group_keys: list[str]
    hybrid: bool = False
    tags: list[str] = []


class TierRecord(BaseModel):
    mod_id: str
    base_id: str
    ilvl: int
    weight: int
    value_ranges: list[tuple[float, float]]
    tord: int = 0
    alias: str | None = None


class OmenRecord(BaseModel):
    id: str
    name: str
    modifies: str  # ActionKind value this omen wraps
    effect: str  # human-readable effect text, from poe2db


class CurrencyMechanicRecord(BaseModel):
    action_kind: str
    display_name: str
    description: str
    deterministic: bool


class EssenceGrantRecord(BaseModel):
    mod_id: str
    ilvl: int


class EssenceRecord(BaseModel):
    id: str
    name: str
    family: str
    tier_kind: str  # EssenceTierKind value: lesser/normal/greater/perfect
    per_base: dict[str, list[EssenceGrantRecord]]


class GameDataFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    meta: GameDataMeta
    base_groups: list[BaseGroupRecord]
    bases: list[BaseItemRecord]
    mods: list[ModRecord]
    tiers: list[TierRecord]
    omens: list[OmenRecord] = []
    currency_mechanics: list[CurrencyMechanicRecord] = []
    essences: list[EssenceRecord] = []
    socketables_raw: list[dict] = []
    catalysts_raw: list[dict] = []
    prices: dict[str, float] = {}
    """name -> Divine Orb cost, from poe2db.tw's live economy page (see
    poe2db_parse.parse_economy_divine). Live market data, not a fixed constant
    -- expect drift between refreshes."""


class TargetModSpec(BaseModel):
    mod_id: str
    name: str | None = None
    min_ilvl: int = 0
    """Minimum tier requirement: the mod must be rolled at a tier whose own
    ilvl requirement is at least this. 0 (default) means any tier satisfies
    -- the mod just needs to be present at all."""


class TargetSpec(BaseModel):
    """A user-authored crafting-goal spec (CLI YAML input)."""

    base: str  # base item name, e.g. "Amulet"
    ilvl: int
    target_mods: list[TargetModSpec]
    start_rarity: str = "normal"
    start_mod_ids: list[str] = []
    objective: str = "steps"  # "steps" or "cost"
    max_steps: int = 30
