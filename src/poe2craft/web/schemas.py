"""Pydantic request/response models for the web API -- a separate I/O boundary
from `data.schemas` (which is scoped to the compiled gamedata file and CLI
YAML target specs, per its own docstring)."""
from __future__ import annotations

from pydantic import BaseModel


class BaseOption(BaseModel):
    base_id: str
    name: str
    bgroup_name: str
    is_jewellery: bool
    max_prefix: int
    max_suffix: int


class ModTierOption(BaseModel):
    ilvl: int
    weight: int
    rank: int  # 1 = best/highest-ilvl tier ("T1"), matching in-game Tier display convention
    value_ranges: list[tuple[float, float]]


class ModOption(BaseModel):
    mod_id: str
    name: str
    affix: str  # "prefix" | "suffix"
    tags: list[str]
    rollable: bool
    essence_grantable: bool
    tiers: list[ModTierOption]


class ModReport(BaseModel):
    """One entry in a user's description of their item's actual current mods:
    the mod, and the exact ilvl of the tier they say is currently rolled."""

    mod_id: str
    tier_ilvl: int


class TargetModRequest(BaseModel):
    mod_id: str
    min_ilvl: int = 0


class SetupRequest(BaseModel):
    base_id: str
    ilvl: int
    rarity: str  # "normal" | "magic" | "rare"
    current_mods: list[ModReport] = []
    target_mods: list[TargetModRequest]
    objective: str = "steps"  # "steps" | "cost"
    max_steps: int = 30
    n_trials: int = 500
    seed: int | None = None


class AdvanceRequest(BaseModel):
    rarity: str
    current_mods: list[ModReport] = []


class TargetProgressItem(BaseModel):
    mod_id: str
    name: str
    min_ilvl: int
    status: str  # "absent" | "below_tier" | "satisfied"


class RecommendedAction(BaseModel):
    action_id: str
    name: str
    cost: float


class SolveResponse(BaseModel):
    session_id: str
    target_progress: list[TargetProgressItem]
    prefix_count: int
    suffix_count: int
    max_prefix: int
    max_suffix: int
    rarity: str
    is_goal: bool
    dead_end: bool
    recommended_action: RecommendedAction | None
    estimated_remaining: float
    objective: str
    unit: str
    converged: bool
    iterations: int
    states_explored: int
    # Only meaningful on /advance responses -- None on the initial setup response.
    resolved_via: str | None = None  # "cached_policy" | "resolved_fresh"
    note: str | None = None


class ParseItemRequest(BaseModel):
    text: str
    base_id: str | None = None  # force a base rather than auto-detecting -- see ParseItemResponse.ambiguous_bases


class ParsedModOption(BaseModel):
    mod_id: str
    name: str
    affix: str
    tier_ilvl: int
    rank: int


class ParseItemResponse(BaseModel):
    base_id: str | None
    base_name: str | None
    ilvl: int | None
    rarity: str | None
    mods: list[ParsedModOption]
    ambiguous_bases: list[BaseOption]
    unmatched_lines: list[str]


class CostSpreadResponse(BaseModel):
    n_rollouts: int
    n_samples: int
    success_rate: float
    mean_cost: float
    median_cost: float
    p90_cost: float
    worst_cost: float
    unit: str = "currency (Divine Orb)"


class TradeComparisonResponse(BaseModel):
    """Buy-vs-craft-vs-sell, in real Divine-Orb terms -- only ever returned
    from an explicit POST the user triggers (see web/crafting.py's
    trade_compare route and docs/data_provenance.md). Deliberately has no
    credential field anywhere on this or any other request/response model --
    POE2CRAFT_POESESSID is a server-side-only secret, never round-tripped
    through the API."""

    league: str
    craft_cost: float
    buy_price: float | None
    buy_price_n_listings: int
    sell_value: float | None
    sell_value_n_listings: int
    sell_and_restart_net_cost: float | None
    """fresh_craft_cost - sell_value -- negative means selling now and
    starting over would be a net *profit*, not just cheaper."""
    recommendation: str  # "keep_crafting" | "buy" | "sell_and_restart" | "insufficient_data"
    caveats: list[str]
    unit: str = "currency (Divine Orb)"
