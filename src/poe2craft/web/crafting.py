"""Session endpoints: submit a setup (base/ilvl/rarity/current mods/target
mods) to get a session id plus the first recommendation, then repeatedly
report the item's new state to get the next one -- mirroring the CLI's
`solve` sequence for setup, and a fast policy lookup (falling back to a fresh
solve if the reported state wasn't reachable from the original one) for each
subsequent report."""
from __future__ import annotations

import random
from concurrent.futures import ProcessPoolExecutor

from fastapi import APIRouter, Depends, HTTPException

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.engine.omens import all_actions
from poe2craft.pricing.errors import TradeAPIError, TradeConfigError
from poe2craft.pricing.trade_client import TradeClient
from poe2craft.pricing.valuation import estimate_buy_price, estimate_sell_value, recommend
from poe2craft.solver.cost_stats import estimate_cost_spread
from poe2craft.solver.featurize import (
    ItemReportError,
    ModStatus,
    TargetResolutionError,
    abstractify,
    item_from_report,
    resolve_target,
    start_state,
)
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.value_iteration import q_values_at, value_iteration
from poe2craft.web.deps import (
    get_executor,
    get_gamedata,
    get_session_store,
    get_solve_status_tracker,
    get_trade_client,
    get_trade_stat_mapping,
)
from poe2craft.web.schemas import (
    AdvanceRequest,
    AlternativeAction,
    AlternativeActionsResponse,
    CostSpreadResponse,
    PoolPreviewEntry,
    PoolPreviewResponse,
    RecommendedAction,
    SetupRequest,
    SolveResponse,
    TargetProgressItem,
    TradeComparisonResponse,
)
from poe2craft.web.session import Session, SessionStore
from poe2craft.web.solve_status import SolveStatusTracker

router = APIRouter(prefix="/api/sessions", tags=["crafting"])

_STATUS_NAME = {ModStatus.ABSENT: "absent", ModStatus.BELOW_TIER: "below_tier", ModStatus.SATISFIED: "satisfied"}


def _parse_rarity(raw: str) -> Rarity:
    try:
        return Rarity(raw)
    except ValueError:
        raise HTTPException(422, f"unknown rarity {raw!r} -- expected normal/magic/rare") from None


def _build_response(
    session: Session, gamedata: GameData, resolved_via: str | None = None, note: str | None = None
) -> SolveResponse:
    target = session.target
    state = session.current_state
    result = session.result

    target_progress = [
        TargetProgressItem(
            mod_id=req.mod_id,
            name=gamedata.mods[req.mod_id].name,
            min_ilvl=req.min_ilvl,
            status=_STATUS_NAME[ModStatus(s)],
        )
        for req, s in zip(target.target_mods, state.status)
    ]

    action_id = result.policy.get(state)
    recommended = None
    if action_id is not None:
        action = session.actions[action_id]
        recommended = RecommendedAction(action_id=action_id, name=action.name, cost=action.cost())

    bg = gamedata.base_group_of(target.base_id)
    unit = "steps" if target.objective == "steps" else "currency (Divine Orb)"

    return SolveResponse(
        session_id=session.session_id,
        base_id=str(target.base_id),
        ilvl=target.ilvl,
        target_progress=target_progress,
        prefix_count=state.prefix_count,
        suffix_count=state.suffix_count,
        max_prefix=bg.max_prefix,
        max_suffix=bg.max_suffix,
        rarity=state.rarity.value,
        is_goal=state.is_goal(),
        dead_end=state in result.dead_ends,
        recommended_action=recommended,
        estimated_remaining=-result.expected_value(state),
        objective=target.objective,
        unit=unit,
        converged=result.converged,
        iterations=result.iterations,
        states_explored=len(result.value),
        can_undo=bool(session.history),
        resolved_via=resolved_via,
        note=note,
    )


@router.post("", response_model=SolveResponse, status_code=201)
def create_session(
    req: SetupRequest,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
    executor: ProcessPoolExecutor | None = Depends(get_executor),
    solve_status: SolveStatusTracker = Depends(get_solve_status_tracker),
) -> SolveResponse:
    base_id = BaseId(req.base_id)
    base = gamedata.bases.get(base_id)
    if base is None:
        raise HTTPException(404, f"unknown base id {req.base_id!r}")

    # resolve_target matches by base *name*, not id -- see docs/design_notes.md.
    spec = TargetSpec(
        base=base.name,
        ilvl=req.ilvl,
        target_mods=[TargetModSpec(mod_id=tm.mod_id, min_ilvl=tm.min_ilvl) for tm in req.target_mods],
        objective=req.objective,
        max_steps=req.max_steps,
    )
    try:
        target = resolve_target(gamedata, spec)
    except TargetResolutionError as e:
        raise HTTPException(422, str(e)) from e

    rarity = _parse_rarity(req.rarity)
    mod_reports = [(ModId(m.mod_id), m.tier_ilvl) for m in req.current_mods]
    try:
        item = item_from_report(gamedata, target.base_id, target.ilvl, rarity, mod_reports)
    except ItemReportError as e:
        raise HTTPException(422, str(e)) from e

    state0 = abstractify(target, item)
    actions = all_actions(gamedata, base_id=target.base_id)
    rng = random.Random(req.seed) if req.seed is not None else random.Random()
    token = solve_status.start("create_session", base.name, target.objective, req.n_trials)
    try:
        mdp = build_mdp(gamedata, target, state0, actions, rng, n_trials=req.n_trials, executor=executor, base_id=target.base_id)
        result = value_iteration(mdp, actions, objective=target.objective)
    finally:
        solve_status.finish(token)

    session = store.create(
        target=target,
        actions=actions,
        result=result,
        mdp=mdp,
        current_state=state0,
        current_item=item,
        rng=rng,
        n_trials=req.n_trials,
    )
    return _build_response(session, gamedata)


@router.post("/{session_id}/advance", response_model=SolveResponse)
def advance_session(
    session_id: str,
    req: AdvanceRequest,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
    executor: ProcessPoolExecutor | None = Depends(get_executor),
    solve_status: SolveStatusTracker = Depends(get_solve_status_tracker),
) -> SolveResponse:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")

    rarity = _parse_rarity(req.rarity)
    mod_reports = [(ModId(m.mod_id), m.tier_ilvl) for m in req.current_mods]
    try:
        item = item_from_report(gamedata, session.target.base_id, session.target.ilvl, rarity, mod_reports)
    except ItemReportError as e:
        raise HTTPException(422, str(e)) from e

    new_state = abstractify(session.target, item)

    if new_state in session.result.value:
        session.push_history()
        session.current_state = new_state
        session.current_item = item
        return _build_response(session, gamedata, resolved_via="cached_policy")

    # Unseen state: the reported item isn't reachable from the original start
    # via the modeled action set (a data-entry slip, or a real mechanic this
    # project doesn't model). Re-solve fresh from here rather than erroring --
    # and mutate the session in place so the enlarged reachable set benefits
    # every later advance in this session too, not just this one call.
    token = solve_status.start("advance_session", gamedata.bases[session.target.base_id].name, session.target.objective, session.n_trials)
    try:
        mdp = build_mdp(
            gamedata,
            session.target,
            new_state,
            session.actions,
            session.rng,
            n_trials=session.n_trials,
            executor=executor,
            base_id=session.target.base_id,
        )
        session.result = value_iteration(mdp, session.actions, objective=session.target.objective)
    finally:
        solve_status.finish(token)
    session.mdp = mdp  # alternatives/preview must reflect the newly-enlarged reachable set, not the stale original one
    session.push_history()
    session.current_state = new_state
    session.current_item = item
    return _build_response(
        session,
        gamedata,
        resolved_via="resolved_fresh",
        note="The reported state wasn't reachable from the original plan, so this was re-solved fresh from here.",
    )


@router.get("/{session_id}", response_model=SolveResponse)
def get_session(
    session_id: str, gamedata: GameData = Depends(get_gamedata), store: SessionStore = Depends(get_session_store)
) -> SolveResponse:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")
    return _build_response(session, gamedata)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, store: SessionStore = Depends(get_session_store)) -> None:
    store.delete(session_id)


@router.get("/{session_id}/cost-spread", response_model=CostSpreadResponse)
def cost_spread(
    session_id: str,
    n_rollouts: int = 300,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
) -> CostSpreadResponse:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")
    n_rollouts = max(1, min(n_rollouts, 2000))

    spread = estimate_cost_spread(
        gamedata,
        session.target,
        session.actions,
        session.result.policy,
        session.current_item,
        session.rng,
        n_rollouts=n_rollouts,
    )
    return CostSpreadResponse(
        n_rollouts=spread.n_rollouts,
        n_samples=spread.n_samples,
        success_rate=spread.success_rate,
        mean_cost=spread.mean,
        median_cost=spread.median,
        p90_cost=spread.p90,
        worst_cost=spread.worst,
    )


@router.post("/{session_id}/trade-compare", response_model=TradeComparisonResponse)
def trade_compare(
    session_id: str,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
    trade_client: TradeClient = Depends(get_trade_client),
    mod_mapping: dict = Depends(get_trade_stat_mapping),
    solve_status: SolveStatusTracker = Depends(get_solve_status_tracker),
) -> TradeComparisonResponse:
    """Live pathofexile.com/trade2 lookup comparing three options in real
    Divine-Orb terms: keep crafting, buy the target outright, or sell the
    current item and start over. Only ever called when the user explicitly
    asks for it -- never from create_session/advance_session, never polled.
    See docs/data_provenance.md."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")
    if session.target.objective != "cost":
        raise HTTPException(422, "trade-compare needs a cost-objective session, so every number is in Divine Orb terms")

    try:
        league = trade_client.league
        buy = estimate_buy_price(trade_client, gamedata, mod_mapping, session.target)
        sell = estimate_sell_value(trade_client, gamedata, mod_mapping, session.current_item)
    except (TradeAPIError, TradeConfigError) as e:
        raise HTTPException(502, f"pathofexile.com/trade2 lookup failed: {e}") from e

    craft_cost = -session.result.expected_value(session.current_state)

    # "Sell and restart"'s other leg: cost to craft the same target again
    # from an empty item -- reuses advance_session's own "cached policy vs.
    # resolve fresh" fallback shape, since the empty state is very likely
    # already in this session's reachable set from the original BFS.
    fresh_state = start_state(gamedata, session.target, Rarity.NORMAL, frozenset())
    if fresh_state in session.result.value:
        fresh_craft_cost = -session.result.expected_value(fresh_state)
    else:
        token = solve_status.start(
            "trade_compare_restart", gamedata.bases[session.target.base_id].name, session.target.objective, session.n_trials
        )
        try:
            fresh_mdp = build_mdp(gamedata, session.target, fresh_state, session.actions, session.rng, n_trials=session.n_trials)
            fresh_result = value_iteration(fresh_mdp, session.actions, objective=session.target.objective)
        finally:
            solve_status.finish(token)
        fresh_craft_cost = -fresh_result.expected_value(fresh_state)

    restart_net_cost = fresh_craft_cost - sell.divine_price if sell.divine_price is not None else None
    recommendation = recommend(craft_cost, buy.divine_price, restart_net_cost)

    return TradeComparisonResponse(
        league=league,
        craft_cost=craft_cost,
        buy_price=buy.divine_price,
        buy_price_n_listings=buy.n_listings,
        sell_value=sell.divine_price,
        sell_value_n_listings=sell.n_listings,
        sell_and_restart_net_cost=restart_net_cost,
        recommendation=recommendation,
        caveats=list(buy.caveats) + list(sell.caveats),
    )


@router.get("/{session_id}/alternatives", response_model=AlternativeActionsResponse)
def alternatives(
    session_id: str,
    top_n: int = 3,
    store: SessionStore = Depends(get_session_store),
) -> AlternativeActionsResponse:
    """The top `top_n` actions by expected value at the current state, not
    just the single greedy recommendation -- lets the user compare options
    before spending currency in-game, the way competing crafting tools do."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")
    top_n = max(1, min(top_n, len(session.actions)))

    qs = q_values_at(session.mdp, session.actions, session.result, session.current_state)
    recommended_id = session.result.policy.get(session.current_state)
    ranked = sorted(qs.items(), key=lambda kv: kv[1], reverse=True)[:top_n]

    unit = "steps" if session.target.objective == "steps" else "currency (Divine Orb)"
    return AlternativeActionsResponse(
        alternatives=[
            AlternativeAction(
                action_id=action_id,
                name=session.actions[action_id].name,
                cost=session.actions[action_id].cost(),
                expected_total=-q,
                is_recommended=action_id == recommended_id,
            )
            for action_id, q in ranked
        ],
        unit=unit,
    )


@router.post("/{session_id}/undo", response_model=SolveResponse)
def undo(
    session_id: str,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
) -> SolveResponse:
    """Restores the item/state to what it was one report ago. A 409 (not a
    500) when there's nothing to undo -- an expected, user-facing condition
    at the start of a session, not a server error."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")

    entry = session.pop_history()
    if entry is None:
        raise HTTPException(409, "nothing to undo -- this session has no prior reported state")

    session.current_state = entry.state
    session.current_item = entry.item
    return _build_response(session, gamedata, resolved_via="undo")


@router.get("/{session_id}/preview/{action_id}", response_model=PoolPreviewResponse)
def preview(
    session_id: str,
    action_id: str,
    store: SessionStore = Depends(get_session_store),
) -> PoolPreviewResponse:
    """The exact resulting mod-pool odds for one specific action against the
    current item, before spending it in-game -- only available for actions
    that are a single weighted draw (or an essence's guaranteed grant); see
    docs/design_notes.md for exactly which action kinds this covers and why
    the rest (Alchemy, Greater Exaltation, Annulment/Chaos, Desecration)
    report `available: false` instead of a misleading number."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"unknown or expired session {session_id!r}")
    action = session.actions.get(action_id)
    if action is None:
        raise HTTPException(404, f"unknown action id {action_id!r}")

    preview_result = action.preview(session.current_item) if hasattr(action, "preview") else None
    if preview_result is None:
        return PoolPreviewResponse(
            available=False,
            entries=[],
            guaranteed=[],
            unavailable_reason="odds preview isn't available for this action -- see docs/design_notes.md",
        )

    if preview_result.guaranteed:
        return PoolPreviewResponse(
            available=True,
            entries=[],
            guaranteed=[
                PoolPreviewEntry(mod_id=str(e.mod_id), name=e.name, tier_ilvl=e.tier_ilvl, probability=1.0)
                for e in preview_result.guaranteed
            ],
            unavailable_reason=None,
        )

    total_weight = sum(e.weight for e in preview_result.entries)
    return PoolPreviewResponse(
        available=True,
        entries=sorted(
            (
                PoolPreviewEntry(mod_id=str(e.mod_id), name=e.name, tier_ilvl=e.tier_ilvl, probability=e.weight / total_weight)
                for e in preview_result.entries
            ),
            key=lambda e: e.probability,
            reverse=True,
        ),
        guaranteed=[],
        unavailable_reason=None,
    )
