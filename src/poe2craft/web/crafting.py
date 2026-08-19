"""Session endpoints: submit a setup (base/ilvl/rarity/current mods/target
mods) to get a session id plus the first recommendation, then repeatedly
report the item's new state to get the next one -- mirroring the CLI's
`solve` sequence for setup, and a fast policy lookup (falling back to a fresh
solve if the reported state wasn't reachable from the original one) for each
subsequent report."""
from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException

from poe2craft.data.loader import GameData
from poe2craft.data.schemas import TargetModSpec, TargetSpec
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.engine.omens import all_actions
from poe2craft.solver.cost_stats import estimate_cost_spread
from poe2craft.solver.featurize import (
    ItemReportError,
    ModStatus,
    TargetResolutionError,
    abstractify,
    item_from_report,
    resolve_target,
)
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.value_iteration import value_iteration
from poe2craft.web.deps import get_gamedata, get_session_store
from poe2craft.web.schemas import (
    AdvanceRequest,
    CostSpreadResponse,
    RecommendedAction,
    SetupRequest,
    SolveResponse,
    TargetProgressItem,
)
from poe2craft.web.session import Session, SessionStore

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
        resolved_via=resolved_via,
        note=note,
    )


@router.post("", response_model=SolveResponse, status_code=201)
def create_session(
    req: SetupRequest,
    gamedata: GameData = Depends(get_gamedata),
    store: SessionStore = Depends(get_session_store),
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
    mdp = build_mdp(gamedata, target, state0, actions, rng, n_trials=req.n_trials)
    result = value_iteration(mdp, actions, objective=target.objective)

    session = store.create(
        target=target,
        actions=actions,
        result=result,
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
        session.current_state = new_state
        session.current_item = item
        return _build_response(session, gamedata, resolved_via="cached_policy")

    # Unseen state: the reported item isn't reachable from the original start
    # via the modeled action set (a data-entry slip, or a real mechanic this
    # project doesn't model). Re-solve fresh from here rather than erroring --
    # and mutate the session in place so the enlarged reachable set benefits
    # every later advance in this session too, not just this one call.
    mdp = build_mdp(gamedata, session.target, new_state, session.actions, session.rng, n_trials=session.n_trials)
    session.result = value_iteration(mdp, session.actions, objective=session.target.objective)
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
