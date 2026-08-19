"""Read-only catalog endpoints: bases and their eligible mods, for the
frontend's base picker and the shared current-mods/target-mods picker
component. No session involved."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseId
from poe2craft.solver.item_text import ItemTextParseError, parse_item_text
from poe2craft.web.deps import get_gamedata
from poe2craft.web.schemas import (
    BaseOption,
    ModOption,
    ModTierOption,
    ParsedModOption,
    ParseItemRequest,
    ParseItemResponse,
)

router = APIRouter(prefix="/api", tags=["catalog"])


def _base_option(gamedata: GameData, base_id: BaseId) -> BaseOption:
    base = gamedata.bases[base_id]
    bg = gamedata.base_group_of(base_id)
    return BaseOption(
        base_id=base.id,
        name=base.name,
        bgroup_name=bg.name,
        is_jewellery=base.is_jewellery,
        max_prefix=bg.max_prefix,
        max_suffix=bg.max_suffix,
    )


@router.get("/bases", response_model=list[BaseOption])
def list_bases(gamedata: GameData = Depends(get_gamedata)) -> list[BaseOption]:
    options = [_base_option(gamedata, base_id) for base_id in gamedata.bases]
    options.sort(key=lambda b: b.name)
    return options


@router.get("/bases/{base_id}", response_model=BaseOption)
def get_base(base_id: str, gamedata: GameData = Depends(get_gamedata)) -> BaseOption:
    bid = BaseId(base_id)
    if bid not in gamedata.bases:
        raise HTTPException(404, f"unknown base id {base_id!r}")
    return _base_option(gamedata, bid)


@router.get("/bases/{base_id}/mods", response_model=list[ModOption])
def list_mods(
    base_id: str,
    ilvl: int | None = Query(None, description="Only include tiers reachable at this item level"),
    affix: str | None = Query(None, description='"prefix" or "suffix"'),
    q: str | None = Query(None, description="Case-insensitive substring match on mod name"),
    limit: int = Query(50, le=500),
    gamedata: GameData = Depends(get_gamedata),
) -> list[ModOption]:
    """Serves both the current-mods and target-mods pickers. Sourced from
    `all_tiers_by_base` (rollable + essence-only + Desecrated combined) since
    a real item can currently carry any of those, even though only the
    rollable ones are ever drawn at random by an action."""
    bid = BaseId(base_id)
    if bid not in gamedata.bases:
        raise HTTPException(404, f"unknown base id {base_id!r}")

    rollable_ids = set(gamedata.eligible_mods_for_base(bid))
    essence_grantable_ids = {g.mod_id for e in gamedata.essences for g in e.per_base.get(bid, ())}
    q_lower = q.lower() if q else None

    results: list[ModOption] = []
    for mod_id, tiers in gamedata.all_tiers_by_base.get(bid, {}).items():
        mod = gamedata.mods[mod_id]
        if mod.affix.value not in ("prefix", "suffix"):
            continue
        if affix is not None and mod.affix.value != affix:
            continue
        if q_lower is not None and q_lower not in mod.name.lower():
            continue
        filtered = [t for t in tiers if ilvl is None or t.ilvl <= ilvl]
        if not filtered:
            continue
        rank_by_ilvl = {t.ilvl: i + 1 for i, t in enumerate(gamedata.tier_ranks(bid, mod_id))}
        results.append(
            ModOption(
                mod_id=mod_id,
                name=mod.name,
                affix=mod.affix.value,
                tags=sorted(mod.tags),
                rollable=mod_id in rollable_ids,
                essence_grantable=mod_id in essence_grantable_ids,
                tiers=[
                    ModTierOption(ilvl=t.ilvl, weight=t.weight, rank=rank_by_ilvl[t.ilvl], value_ranges=list(t.value_ranges))
                    for t in sorted(filtered, key=lambda t: t.ilvl)
                ],
            )
        )
    results.sort(key=lambda m: m.name)
    return results[:limit]


@router.post("/parse-item", response_model=ParseItemResponse)
def parse_item(req: ParseItemRequest, gamedata: GameData = Depends(get_gamedata)) -> ParseItemResponse:
    """Stateless: parses pasted PoE2 item text into pre-fillable form fields.
    See `solver/item_text.py`'s module docstring for why this is inherently
    best-effort (archetype ambiguity, unmatched lines) rather than exact."""
    base_id = BaseId(req.base_id) if req.base_id else None
    try:
        parsed = parse_item_text(gamedata, req.text, base_id=base_id)
    except ItemTextParseError as e:
        raise HTTPException(422, str(e)) from e

    mods: list[ParsedModOption] = []
    if parsed.base_id is not None:
        for mod_id, tier_ilvl in parsed.mod_reports:
            mod = gamedata.mods[mod_id]
            ranks = gamedata.tier_ranks(parsed.base_id, mod_id)
            rank = next((i + 1 for i, t in enumerate(ranks) if t.ilvl == tier_ilvl), 0)
            mods.append(ParsedModOption(mod_id=mod_id, name=mod.name, affix=mod.affix.value, tier_ilvl=tier_ilvl, rank=rank))

    return ParseItemResponse(
        base_id=parsed.base_id,
        base_name=parsed.base_name,
        ilvl=parsed.ilvl,
        rarity=parsed.rarity.value if parsed.rarity is not None else None,
        mods=mods,
        ambiguous_bases=[_base_option(gamedata, b.id) for b in parsed.ambiguous_bases],
        unmatched_lines=parsed.unmatched_lines,
    )
