"""Loads `data/compiled/poe2_gamedata.json` (validated via `schemas.GameDataFile`)
into an in-memory `GameData` registry of domain dataclasses, indexed for the
lookups the engine and solver actually need."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from poe2craft.data.schemas import GameDataFile
from poe2craft.domain.essences import EssenceDef, EssenceGrant, EssenceTierKind
from poe2craft.domain.ids import BaseGroupId, BaseId, EssenceId, ModId
from poe2craft.domain.items import BaseGroup, BaseItemDef
from poe2craft.domain.mods import Affix, ModCategory, ModDef, ModTierEntry

DEFAULT_GAMEDATA_PATH = Path(__file__).resolve().parents[3] / "data" / "compiled" / "poe2_gamedata.json"

_CATEGORY_BY_VALUE = {c.value: c for c in ModCategory}


@dataclass
class GameData:
    base_groups: dict[BaseGroupId, BaseGroup]
    bases: dict[BaseId, BaseItemDef]
    mods: dict[ModId, ModDef]
    # base_id -> mod_id -> tiers for that (mod, base) pair, sorted by ilvl.
    # Rollable (NORMAL category prefix/suffix) mods only -- this is what the
    # general weighted pool draws from.
    tiers_by_base: dict[BaseId, dict[ModId, list[ModTierEntry]]] = field(default_factory=dict)
    # Every mod's tiers, all categories included -- essences guarantee specific
    # mods that are sometimes NORMAL (regular essences) and sometimes the
    # dedicated essence-only pool (Perfect essences), neither of which the
    # general pool should ever draw from randomly. See domain.essences.
    all_tiers_by_base: dict[BaseId, dict[ModId, list[ModTierEntry]]] = field(default_factory=dict)
    omens: list[dict] = field(default_factory=list)
    currency_mechanics: list[dict] = field(default_factory=list)
    essences: list[EssenceDef] = field(default_factory=list)
    prices: dict[str, float] = field(default_factory=dict)
    """Action display name -> Divine Orb cost, from poe2db.tw's live economy
    page. Missing from this dict for any name not currently traded there --
    callers should fall back to a placeholder, not assume every name is
    covered."""
    # Memoizes rollable_entries() below, keyed by its own arguments (excluding
    # self) -- see that method's docstring for why. `compare=False`/`repr=False`
    # so this purely-internal cache never affects equality or dataclass repr.
    # Populated lazily; a harmless, GIL-safe race across threads at worst
    # recomputes the same value twice, never reads a partial one (see
    # `web/session.py`'s docstring for this project's general stance on
    # locking only where real correctness is at stake, not just concurrency).
    _pool_cache: dict[tuple, list[tuple[ModDef, ModTierEntry]]] = field(
        default_factory=dict, compare=False, repr=False
    )
    # Same purpose as `_pool_cache`, kept separate rather than adding a
    # category parameter to `rollable_entries` -- that method iterates
    # `eligible_mods_for_base` (NORMAL-only), while this one iterates
    # `all_tiers_by_base` filtered to DESECRATED, a genuinely different source
    # dict, not just a different filter on the same one.
    _desecrated_pool_cache: dict[tuple, list[tuple[ModDef, ModTierEntry]]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def rollable_entries(
        self,
        base_id: BaseId,
        affix: Affix,
        max_ilvl: int,
        min_ilvl: int = 0,
        required_tags: frozenset[str] | None = None,
    ) -> list[tuple[ModDef, ModTierEntry]]:
        """The group-exclusion-agnostic part of `engine.pool.build_pool`'s
        eligibility filter (affix/ilvl/tags), cached by its own arguments.

        This exists because `build_pool` is called millions of times over a
        single solve (once per filler-mod placement, per Monte Carlo trial,
        per (state, action) pair explored) with the *same* (base_id, affix,
        item.ilvl, min_ilvl, required_tags) tuple every time within one solve
        -- only the item's currently-occupied groups differ call to call.
        Recomputing this dict-iteration-plus-per-tier-ilvl-check from scratch
        on every call was the dominant cost of a real solve (profiled: ~90s of
        a ~195s solve). `build_pool` still applies the group-exclusion filter
        itself, per call, against this cached (mod, tier) list."""
        key = (base_id, affix, max_ilvl, min_ilvl, required_tags)
        cached = self._pool_cache.get(key)
        if cached is not None:
            return cached
        entries: list[tuple[ModDef, ModTierEntry]] = []
        for mod_id, tiers in self.eligible_mods_for_base(base_id).items():
            mod = self.mods[mod_id]
            if mod.affix is not affix:
                continue
            if required_tags is not None and not (mod.tags & required_tags):
                continue
            for tier in tiers:
                if min_ilvl <= tier.ilvl <= max_ilvl and tier.weight > 0:
                    entries.append((mod, tier))
        self._pool_cache[key] = entries
        return entries

    def desecrated_entries(
        self, base_id: BaseId, affix: Affix, max_ilvl: int, min_ilvl: int = 0
    ) -> list[tuple[ModDef, ModTierEntry]]:
        """Like `rollable_entries`, but for `ModCategory.DESECRATED` mods --
        the "reveal 3, pick 1" pool a Desecration bone action draws from
        (see `engine.pool.build_desecrated_pool`). Desecrated tiers are only
        present in `all_tiers_by_base` (the NORMAL-only rollable pool never
        includes them), so this can't reuse `rollable_entries`."""
        key = (base_id, affix, max_ilvl, min_ilvl)
        cached = self._desecrated_pool_cache.get(key)
        if cached is not None:
            return cached
        entries: list[tuple[ModDef, ModTierEntry]] = []
        for mod_id, tiers in self.all_tiers_by_base.get(base_id, {}).items():
            mod = self.mods[mod_id]
            if mod.category is not ModCategory.DESECRATED or mod.affix is not affix:
                continue
            for tier in tiers:
                if min_ilvl <= tier.ilvl <= max_ilvl and tier.weight > 0:
                    entries.append((mod, tier))
        self._desecrated_pool_cache[key] = entries
        return entries

    def base_group_of(self, base_id: BaseId) -> BaseGroup:
        return self.base_groups[self.bases[base_id].bgroup_id]

    def eligible_mods_for_base(self, base_id: BaseId) -> dict[ModId, list[ModTierEntry]]:
        """All (mod -> tiers) rollable on this base, ilvl-gating applied by the caller."""
        return self.tiers_by_base.get(base_id, {})

    def find_tier(self, base_id: BaseId, mod_id: ModId, ilvl: int) -> ModTierEntry:
        """Exact-ilvl tier lookup across ALL categories, for essence-guaranteed
        mods (which may not be in the general rollable pool)."""
        for tier in self.all_tiers_by_base.get(base_id, {}).get(mod_id, []):
            if tier.ilvl == ilvl:
                return tier
        raise KeyError(f"no tier found for mod={mod_id} base={base_id} ilvl={ilvl}")

    def tier_ranks(self, base_id: BaseId, mod_id: ModId) -> list[ModTierEntry]:
        """This mod's tiers on this base ordered best-first (T1 = highest ilvl
        requirement = strongest/rarest tier, matching in-game "Tier: N" display
        convention) -- rank is simply 1-based position in this list. `tiers_by_base`
        /`all_tiers_by_base` are stored ascending by ilvl for the general pool's
        own purposes, so this is a separate, display-oriented ordering rather
        than a field stored on `ModTierEntry` itself."""
        tiers = self.all_tiers_by_base.get(base_id, {}).get(mod_id, [])
        return sorted(tiers, key=lambda t: t.ilvl, reverse=True)


def _build_mod(rec: dict) -> ModDef:
    return ModDef(
        id=ModId(rec["id"]),
        name=rec["name"],
        affix=Affix(rec["affix"]),
        category=_CATEGORY_BY_VALUE[rec["category"]],
        group_keys=frozenset(rec["group_keys"]),
        hybrid=rec.get("hybrid", False),
        tags=frozenset(rec.get("tags", ())),
    )


def load_gamedata(path: Path | None = None) -> GameData:
    path = path or DEFAULT_GAMEDATA_PATH
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    validated = GameDataFile.model_validate(raw)

    base_groups = {
        BaseGroupId(bg.id): BaseGroup(id=BaseGroupId(bg.id), name=bg.name, max_affix=bg.max_affix, max_sockets=bg.max_sockets)
        for bg in validated.base_groups
    }
    bases = {
        BaseId(b.id): BaseItemDef(id=BaseId(b.id), name=b.name, bgroup_id=BaseGroupId(b.bgroup_id), is_jewellery=b.is_jewellery)
        for b in validated.bases
    }
    mods = {ModId(m.id): _build_mod(m.model_dump()) for m in validated.mods}
    only_rollable = {mid: m for mid, m in mods.items() if m.is_rollable()}

    all_tiers_by_base: dict[BaseId, dict[ModId, list[ModTierEntry]]] = defaultdict(lambda: defaultdict(list))
    for t in validated.tiers:
        mod_id = ModId(t.mod_id)
        base_id = BaseId(t.base_id)
        all_tiers_by_base[base_id][mod_id].append(
            ModTierEntry(
                mod_id=mod_id,
                base_id=base_id,
                ilvl=t.ilvl,
                weight=t.weight,
                value_ranges=tuple(t.value_ranges),
                tord=t.tord,
                alias=t.alias,
            )
        )
    for per_mod in all_tiers_by_base.values():
        for entries in per_mod.values():
            entries.sort(key=lambda e: e.ilvl)
    all_tiers_by_base = {k: dict(v) for k, v in all_tiers_by_base.items()}

    tiers_by_base = {
        base_id: {mid: tiers for mid, tiers in per_mod.items() if mid in only_rollable}
        for base_id, per_mod in all_tiers_by_base.items()
    }
    tiers_by_base = {base_id: per_mod for base_id, per_mod in tiers_by_base.items() if per_mod}

    essences = [_build_essence(e.model_dump()) for e in validated.essences]

    return GameData(
        base_groups=base_groups,
        bases=bases,
        mods=mods,
        tiers_by_base=tiers_by_base,
        all_tiers_by_base=all_tiers_by_base,
        omens=[o.model_dump() for o in validated.omens],
        currency_mechanics=[c.model_dump() for c in validated.currency_mechanics],
        essences=essences,
        prices=dict(validated.prices),
    )


def _build_essence(rec: dict) -> EssenceDef:
    per_base = {
        BaseId(base_id): tuple(EssenceGrant(mod_id=ModId(g["mod_id"]), ilvl=g["ilvl"]) for g in grants)
        for base_id, grants in rec["per_base"].items()
    }
    return EssenceDef(
        id=EssenceId(rec["id"]),
        name=rec["name"],
        family=rec["family"],
        tier_kind=EssenceTierKind(rec["tier_kind"]),
        per_base=per_base,
    )
