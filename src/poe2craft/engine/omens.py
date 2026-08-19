"""Omens as action wrappers: consumed to steer the *next* currency use rather
than acting as standalone actions. Implemented by constructing a new instance
of the same action class with a modifier (affix restriction, extra count,
deterministic-pick flag, or same-type tag requirement) baked in, since for
every omen modeled here that modifier is exactly what the omen changes.
Confirmed against poe2db.tw's omen catalog (2026-08-18) -- see
domain.actions.OmenKind for which omens aren't modeled and why (Catalyst
quality and Desecrated support this project doesn't have).

Essence omens (Sinistral/Dextral Crystallisation) are base-specific like
essences themselves, so they're constructed in engine.apply.essence_actions_for
instead of here.
"""
from __future__ import annotations

from poe2craft.data.loader import GameData
from poe2craft.domain.actions import OmenKind
from poe2craft.domain.ids import BaseId
from poe2craft.domain.mods import Affix, ModCategory
from poe2craft.engine.apply import (
    AlchemyAction,
    AnnulmentAction,
    ChaosAction,
    ExaltedAction,
    RegalAction,
    build_action_registry,
    desecration_actions_for,
    essence_actions_for,
)

_RESTRICTION: dict[OmenKind, Affix] = {
    OmenKind.DEXTRAL_ANNULMENT: Affix.SUFFIX,
    OmenKind.SINISTRAL_ANNULMENT: Affix.PREFIX,
    OmenKind.DEXTRAL_EXALTATION: Affix.SUFFIX,
    OmenKind.SINISTRAL_EXALTATION: Affix.PREFIX,
    OmenKind.SINISTRAL_ALCHEMY: Affix.PREFIX,
    OmenKind.DEXTRAL_ALCHEMY: Affix.SUFFIX,
    OmenKind.SINISTRAL_CORONATION: Affix.PREFIX,
    OmenKind.DEXTRAL_CORONATION: Affix.SUFFIX,
    OmenKind.SINISTRAL_ERASURE: Affix.PREFIX,
    OmenKind.DEXTRAL_ERASURE: Affix.SUFFIX,
}


def omen_wrapped_actions(gamedata: GameData) -> dict[str, object]:
    """Every omen-wrapped action this project models, keyed by a stable string
    id (mirrors engine.apply.build_action_registry's keying convention)."""
    return {
        "annulment_omen_dextral": AnnulmentAction(gamedata, restrict=_RESTRICTION[OmenKind.DEXTRAL_ANNULMENT]),
        "annulment_omen_sinistral": AnnulmentAction(gamedata, restrict=_RESTRICTION[OmenKind.SINISTRAL_ANNULMENT]),
        "annulment_omen_greater": AnnulmentAction(gamedata, count=2),
        "annulment_omen_light": AnnulmentAction(gamedata, restrict_category=ModCategory.DESECRATED),
        "exalted_omen_dextral": ExaltedAction(gamedata, restrict=_RESTRICTION[OmenKind.DEXTRAL_EXALTATION]),
        "exalted_omen_sinistral": ExaltedAction(gamedata, restrict=_RESTRICTION[OmenKind.SINISTRAL_EXALTATION]),
        "exalted_omen_greater": ExaltedAction(gamedata, count=2),
        "alchemy_omen_sinistral": AlchemyAction(gamedata, priority=_RESTRICTION[OmenKind.SINISTRAL_ALCHEMY]),
        "alchemy_omen_dextral": AlchemyAction(gamedata, priority=_RESTRICTION[OmenKind.DEXTRAL_ALCHEMY]),
        "regal_omen_sinistral": RegalAction(gamedata, restrict=_RESTRICTION[OmenKind.SINISTRAL_CORONATION]),
        "regal_omen_dextral": RegalAction(gamedata, restrict=_RESTRICTION[OmenKind.DEXTRAL_CORONATION]),
        "regal_omen_homogenising": RegalAction(gamedata, homogenising=True),
        "chaos_omen_sinistral": ChaosAction(gamedata, restrict=_RESTRICTION[OmenKind.SINISTRAL_ERASURE]),
        "chaos_omen_dextral": ChaosAction(gamedata, restrict=_RESTRICTION[OmenKind.DEXTRAL_ERASURE]),
        "chaos_omen_whittling": ChaosAction(gamedata, pick_lowest=True),
        "exalted_omen_homogenising": ExaltedAction(gamedata, homogenising=True),
    }


def all_actions(gamedata: GameData, base_id: BaseId | None = None) -> dict[str, object]:
    """The full action set the solver/CLI choose from: base currencies, their
    omen-wrapped variants, and -- when `base_id` is given -- every essence
    with data for that base (essence guarantees are base-specific, so building
    them requires knowing which base is being solved for; omitting base_id
    just skips essences, e.g. for tests/tools that don't need them)."""
    actions = {**build_action_registry(gamedata), **omen_wrapped_actions(gamedata)}
    if base_id is not None:
        actions.update(essence_actions_for(gamedata, base_id))
        actions.update(desecration_actions_for(gamedata, base_id))
    return actions
