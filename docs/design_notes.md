# Design notes

## Out of scope for the v1 solver

The following PoE2 mechanics are parsed/captured where the data is convenient to
keep (for future extension) but are never acted on by the engine or solver:

- **Recombinators** -- merge two separate items into one. This needs a joint
  two-item state, a fundamentally different problem from the single-item MDP
  this project solves.
- **Vaal Orb / corruption** -- a terminal, mostly-bad gambling branch, not a
  "reach this target deterministically" action.
- **Runes, Soul Cores, quality, Catalysts** -- flat deterministic upgrades
  unrelated to the weighted-random mod-roll problem the solver targets.
- **Desecrated mods** (CoE `id_mgroup=10`, ~204 mods) -- a ground/corpse-reveal
  mechanic (patch 0.5), not an on-demand currency action. Parsed and tagged
  (`ModCategory.DESECRATED`) but excluded from the rollable pool.

Only `ModCategory.NORMAL` prefix/suffix mods (513 of the 1364 parsed) are ever
placed in the weighted roll pool by `poe2craft.engine.pool`.

## Known data-fidelity gap: incomplete modifier weights (confirmed, affects the solver)

Unlike the other data gaps in this document, this one **does** affect solver
accuracy -- it feeds directly into the weighted pool `engine.pool` samples
from.

**The finding**: `weighting` is a placeholder value of `1` (next to nothing,
against mods normally weighted in the hundreds/thousands) for a large chunk
of the vendored dataset:

| Scope | Rows/mods at `weighting=1` |
|---|---|
| All 19,332 tier rows | 55.4% |
| Rollable (513) mods -- *every* tier weight=1 | 139 (27%) |
| Rollable mods -- *some* tiers weight=1 | 203 more (40%) |
| Rollable mods with real, varying weights throughout | 154 (30%) |

Found while investigating a specific case (mod 5119, "#% increased Elemental
Damage with Attacks" on One Hand Sword) that a user flagged as looking wrong
-- an ordinary, commonly-seen weapon prefix showing weight=1 across all six
of its tiers is implausible on its face. The other all-weight-1 examples
skew toward Waystone/map mods (Rare Monster counts, Abyss rewards, Gold
found, etc.), but it isn't confined to that category, as mod 5119 shows.

**Confirmed this is a real upstream data gap, not a bug on this project's
side**, by fetching Craft of Exile's own live site directly with `curl`
(bypassing the HTML-to-markdown conversion a normal fetch does, which was
hiding the `<script>` tags) and grepping its actual JS bundles
(`js/poe2.js`, `packages/package.js`). Their own client-side code reads
weight via the exact same path this project does --
`poecd.tiers[modid][base][tier].weighting` -- against the exact same
`poec_data.json`. No special-case handling of `weighting==1` exists in their
code, and no separate/richer weight endpoint exists on either the main or
beta (`beta.craftofexile.com`, patch 4.5.4.1.2) site. Craft of Exile's own
published methodology explains *why*: weights are derived from parsing
trade-site listings and from community recombinator experiments (the
"Prohibited Library" Discord's `#poe2-recombinator-chat`, the same research
Krakenbul's community weight spreadsheet also draws from) -- both
inherently incomplete for less-traded, less-experimented-on mod/base
combinations. This is the live site's actual current data, not a stale
vendor snapshot or a wrong field.

**What this means in practice**: for the ~40% of rollable mods with at least
one weight=1 tier, the weighted sampler will under-estimate that mod's real
in-game frequency -- possibly *severely*, since weight=1 next to
hundreds/thousands makes it nearly unselectable in the simulated pool even
if its true relative frequency is much higher. A `poe2craft solve` targeting
one of these mods will likely overstate the expected steps/cost to reach it,
and a `simulate` run will show a correspondingly pessimistic success rate.
This isn't fixable by better parsing -- the correct data doesn't appear to
be publicly available yet. Options not pursued here: a hand-maintained
override table for specific high-priority mods (once a real weight is known
from some other source), or waiting for community weight research to catch
up. Worth surfacing to the user at solve time (e.g. a CLI warning when a
target mod has any weight=1 tier) as a natural follow-up, not yet
implemented.

## Known data-fidelity gap: `nvalues` ambiguity

See `coe_parse._parse_value_ranges` docstring for the full reasoning. Summary:
CoE's per-tier `nvalues` field is a list of "value slots", each either a `[low,
high]` range or a bare flat number -- except when the *whole* list is exactly
two bare numbers, which is genuinely ambiguous between "one range" (e.g. a
socket-only "1 to 100" damage mod) and "two unrelated flat stats" (confirmed
real for several hybrid Waystone mods). This project always reads it as
independent per-element slots, which is correct for the confirmed hybrid cases
and only slightly wrong (splits one range into two degenerate flat slots) for
a handful of true single-range mods. This has **zero effect on the solver**:
state/eligibility/weight/group-exclusion never depend on value_ranges, only on
mod identity. It only affects a mod's displayed numeric range and Divine Orb's
reroll simulation -- and Divine Orb itself is a near no-op for v1 (see below).

## Solver scaling ceiling

State is `(rarity, prefix_count, suffix_count, status-tuple)`, one status
code per target mod, relative to a single `TargetSpec` -- this is what keeps
the state space small regardless of the game's overall mod pool (1364 mods,
86 bases): a solve only ever reasons about the mods in *that* target, not the
whole game. Each status is normally binary (absent/satisfied, 1 bit); a
target mod with a `min_ilvl` tier requirement (see "Modifier tier targeting"
below) gets a third value (present-but-below-tier), a little over 1.5 bits
instead of 1 -- a real but modest widening, not a different order of growth.
The status-tuple dimension still dominates cost as the target grows:

- comfortable up to ~10-12 target mods
- workable, with care, to ~16-18
- **impractical in pure-Python tabular value iteration beyond ~20-24** target
  mods -- the same ceiling the source article (dennybritz.com/posts/poe-crafting)
  hit for PoE1. Past that point, function approximation (e.g. a small neural
  net in place of the tabular Q-table) would be required; that's explicitly out
  of scope here.

Action-count growth is a secondary cost, separate from the state-space
ceiling above: each omen/tier variant is its own action the Monte Carlo
learner samples per state, so the per-base action set has grown from 9 (core
currencies only) to 32 core+omen actions plus up to a few dozen essence
variants -- a real, measured ~2-3x slowdown per solve (e.g. a 1-target-mod
solve went from ~17s to ~40s at 500 trials/pair). Still practical for the
target sizes this project is scoped for; would be the first thing to prune
(e.g. an omen relevance pre-filter) if solves needed to run much faster.

## Modifier tier targeting

A `TargetModSpec` can set `min_ilvl` (default 0, meaning "any tier
satisfies") to require a mod be rolled at a tier whose own ilvl requirement
is at least that. This turns each such target's status from a boolean into
three values (`solver.featurize.ModStatus`): `ABSENT` (0), `BELOW_TIER` (1,
present but rolled at too weak a tier), `SATISFIED` (2). A target with no
`min_ilvl` can only ever be ABSENT or SATISFIED -- BELOW_TIER needs nothing
more than "present at all" to already qualify, so it's simply never produced
for that mod, which is what keeps ordinary (untiered) targets exactly as
small as before this was added.

`resolve_target` rejects an unreachable request up front (a `min_ilvl` no
tier on that base can reach at the target's own ilvl) rather than letting the
solver silently search for a state that can never exist. `concretize()` must
place a target mod at a tier consistent with the state's own status -- a
tier `>= min_ilvl` for SATISFIED, `< min_ilvl` for BELOW_TIER -- since
concretizing the wrong one would make a later `abstractify()` disagree with
the state it was supposed to represent (the same silent-corruption risk the
group-exclusion and filler-re-randomization logic elsewhere in this module
guards against).

A declared *starting* mod (`start_mod_ids`) is always treated as SATISFIED,
even against a tiered target -- the CLI's start-state input has no field for
"what tier is it currently at," so presence is read as an assertion that it's
already good enough. Documented in `start_state`'s docstring as a real
simplification, not an oversight.

**Divine Orb is still a near no-op**, tier targeting or not: it rerolls a
mod's numeric value within its already-assigned tier, never the tier
(`RolledAffix.ilvl`) itself -- so it produces no visible change to
`BELOW_TIER` vs. `SATISFIED` either. Tracking rolled *values* (not just
tiers) against a target threshold would be a further, larger extension (its
own state dimension per valued target, rather than reusing the existing
ilvl already on every `RolledAffix`) -- not implemented.

## Open mechanic-verification items

Not fully pinned down by either vendored source at time of writing; verify
against poe2db's currency/omen text during Phase 2/4 rather than guessing
further:

- Does Chaos Orb's added mod preserve the removed mod's affix type, or roll
  completely freely (any prefix or suffix)?
- Are fractured mods immune to Annulment/Chaos removal (expected: yes)?
- Perfect Essence: if its guaranteed added mod's exclusion group collides with
  a mod that *wasn't* the one randomly removed, what happens (is that outcome
  simply excluded from the removal-choice distribution, or can it fail)?
  **Resolved by assumption, not confirmed against poe2db text**: implemented
  as "the removal choice is restricted to mods whose removal would actually
  let the guaranteed mod(s) fit" (`EssenceAction._removal_candidates`), i.e.
  essences always successfully apply. If real PoE2 instead lets you burn an
  essence into a dead end, this would need revisiting.

## Tiered currencies (Greater/Perfect)

Confirmed directly from poe2db.tw's item pages for each currency (quoted
"Minimum Modifier Level" field, 2026-08-18 -- user-confirmed against their own
game knowledge before implementation):

| Currency | Base | Greater | Perfect |
|---|---|---|---|
| Orb of Transmutation | 0 | 44 | 70 |
| Orb of Augmentation | 0 | 44 | 70 |
| Regal Orb | 0 | 35 | 50 |
| Chaos Orb | 0 | 35 | 50 |
| Exalted Orb | 0 | 35 | 50 |

The floor restricts `engine.pool.build_pool`'s tier filter to `min_ilvl <=
tier.ilvl <= item.ilvl` -- it changes *which* mod/tier can be drawn (biasing
toward stronger, rarer mods by removing lower-tier competition from the
weighted pool), never *how many* affixes get added. This has a real,
measurable effect on odds: e.g. on one real Body Armour base at ilvl 82, a
Perfect-floor (50) suffix pool drops from 85 to 36 eligible mods (70500 to
28450 total weight), roughly doubling a mid-tier mod's individual draw
probability. The "steps" objective solver can and does prefer a tiered orb
when that odds improvement is worth it (cost is irrelevant to that
objective); the "cost" objective weighs it against the tier's (placeholder)
cost multiplier -- 3x for Greater, 15x for Perfect, illustrative only.

A real bug caught during implementation and worth remembering: checking pool/
room eligibility for Transmutation and Regal (both of which change rarity as
part of their effect) must be evaluated *as if already transitioned*
(Magic/Rare), not against the item's pre-transition rarity -- checking while
still Normal always reports "no room" (`has_room` treats Normal as having
none), and checking under Magic's 1-prefix/1-suffix cap can wrongly report no
room for a slot that Rare's larger cap would actually allow. Covered by
`tests/unit/test_tiered_currencies.py::test_regal_checks_room_as_if_already_rare_not_magic`.

**Known gap**: omens only wrap base-tier currencies in the action registry --
there's no "Perfect Exalted Orb + Dextral Exaltation" combined action, even
though e.g. `ExaltedAction` supports both `restrict` and `tier` simultaneously
and nothing stops constructing that combination. Not wired into
`engine.omens.omen_wrapped_actions` because no target in testing needed it
yet; straightforward to add if a real target spec shows the combination
would matter (both levers combine multiplicatively on the same pool, so it's
plausible some target would prefer it over either alone).

## Omens

17 of poe2db.tw's ~23 listed omens are modeled (`domain.actions.OmenKind`),
implemented as wrapping the same action classes above with a modifier baked
in (an affix restriction, an extra count, a deterministic-pick flag, or a
same-tag requirement) rather than as separate mechanics:

| Omen | Wraps | Effect |
|---|---|---|
| Sinistral/Dextral Annulment | Annulment | restricts removal to prefix/suffix |
| Greater Annulment | Annulment | removes 2 instead of 1 |
| Sinistral/Dextral Exaltation | Exalted | restricts the add to prefix/suffix |
| Greater Exaltation | Exalted | adds 2 instead of 1 |
| Homogenising Exaltation | Exalted | restricts the add to a mod sharing a tag with an existing modifier |
| Sinistral/Dextral Alchemy | Alchemy | maxes out prefixes/suffixes first, then fills the rest (still 4 total) |
| Sinistral/Dextral Coronation | Regal | restricts the add to prefix/suffix |
| Homogenising Coronation | Regal | restricts the add to a mod sharing a tag with an existing modifier |
| Sinistral/Dextral Erasure | Chaos | restricts removal to prefix/suffix |
| Whittling | Chaos | removes the **lowest-level** modifier -- deterministic, not random |
| Sinistral/Dextral Crystallisation | Perfect Essence | restricts removal to prefix/suffix |

**Homogenising required pulling in mod-tag data I'd previously left
unparsed.** CoE's `modifiers.mtypes` field (a pipe-delimited list of ids into
a 53-entry top-level `mtypes` lookup, e.g. `id_mtype=1 -> poedb_id="life"`)
gives real, broad category tags -- "fire", "caster", "life", "elemental",
"attribute", etc. -- matching exactly the kind of grouping PoE's own
Catalysts target. Only 620/1364 mods (294/513 of the rollable ones, ~57%)
have any tag at all; `mtags` (a separately-named field on the same records)
is empty for every mod in the dataset and stayed unused. Added a `tags:
frozenset[str]` field to `ModDef` (default empty, so no existing code needed
updating) and an `item_tags()` helper (`engine.pool`) that unions the tags of
an item's current affixes -- that union is the "existing modifier" side of
the omen; the pool is then filtered to mods whose own tags intersect it at
all (any single shared tag counts, matching how Catalysts work). An item with
no tagged mods at all (a real possibility, not just an edge case, given only
57% coverage) has nothing to homogenise against, so the omen is correctly
inapplicable rather than guessing at a fallback.

These aren't just wired up for completeness -- the solver measurably uses
them: solving for a single suffix mod on an Amulet, the optimal first action
changed from plain Alchemy (~12.6 expected steps) to Dextral Alchemy/"max
suffixes" (~7.9 expected steps) once that omen was available, since
guaranteeing 3 suffix slots beats a random 4-mod mix when the target is a
suffix.

**Whittling required a data model change**: `RolledAffix` didn't previously
record which tier/ilvl it was rolled at (state/eligibility never needed it),
so "remove the lowest-level modifier" had nothing to compare. Added an
`ilvl` field (default 0, so existing hand-built test fixtures didn't need
updating) populated by every real roll path. Tie-breaking among equal-lowest
candidates is random, not insertion-order, since the source text doesn't
specify a tiebreak and insertion order isn't a real game mechanic to fake.

**Not modeled, and why** (`OmenKind`'s docstring has the short version):

- **Catalysing Exaltation** ("consumes all Catalyst Quality...") -- Catalysts
  are explicitly out of scope (a flat deterministic upgrade this project
  doesn't model at all); this omen is meaningless without tracking Catalyst
  quality on the item.
- **Omen of Light** (Annulment removes only Desecrated modifiers) --
  Desecrated mods are also out of scope (no action ever places one), so this
  omen would always be a no-op in the current engine; implementing a
  guaranteed-dead action wouldn't add value.
- **Omen of Chaotic Rarity/Quantity/Monsters/Effectiveness** (4 Chaos omens,
  Waystone-specific) -- need both Waystone-specific mod-tag categorization
  (not parsed) and are a narrower use case (map crafting, not gear crafting).

## Real currency costs (Divine Orb terms)

Every `Action.cost()` is now a real Divine-Orb-equivalent price, not the
arbitrary placeholder scale used before this. Source: poe2db.tw's
`Economy_divine` page (`GameData.prices`, see `docs/data_provenance.md`) --
found and validated while investigating the modifier-weight gap above (this
project's own request to check whether Craft of Exile's data could be
scraped for more/better information led to finding poe2db's live economy
page instead, a different site).

**Omen costs stack additively on top of the base currency's**, since using an
omen means consuming *both* items, not choosing between them --
`ExaltedAction(restrict=Affix.SUFFIX).cost()` is `price("Exalted Orb") +
price("Omen of Dextral Exaltation")`, not just one or the other. This was a
real, if minor, undercounting bug in the placeholder-cost version of this
project (omen-wrapped actions silently reused the base action's cost,
ignoring the omen's own price entirely) -- caught and fixed as part of
switching to real prices, not present before because the placeholder scale
never claimed to represent anything real enough to be "wrong" in this way.

**Coverage, as of the 2026-08-18 snapshot**: all core currencies are priced
except Fracturing Orb and Perfect Chaos/Perfect Exalted Orb (the latter two
fall back to a real cheaper tier's price -- Greater's -- rather than a guess,
see `engine.apply._tiered_price`); 5 of
the 17 modeled omens are priced directly, the other 12 fall back to
`FALLBACK_OMEN_COST` (the median of the 28 omens that *are* priced); 42 of
95 essences are priced directly, the rest fall back to
`FALLBACK_ESSENCE_COST` (median of the 42). These fallbacks are real
aggregate statistics from the live snapshot, not arbitrary numbers, but
they're still approximations for the specific unpriced name -- a target
whose optimal policy leans on one of those names should be read with that
in mind.

**A parsing mistake caught before it shipped**: the `Economy_divine` table
has two numeric columns close together ("24h Value" = the real exchange
rate, "24h volume traded" = an unrelated trade-count). An initial parse grabbed
the wrong one (a nonsensical "1 Divine = ~685,000 Chaos Orb" for the very
first spot-check), caught immediately by comparing against a known
real-world ratio (Divine:Chaos is roughly 10:1) before trusting any of it.
Worth remembering as a general lesson for any future scrape of this
page format: sanity-check one familiar number before trusting the rest.

Real prices are live market data and will drift between refreshes -- a
`poe2craft solve --out policy.json` run today and the same command next
month can legitimately recommend different actions under the `cost`
objective purely because the market moved, not because anything about the
mod data or the solver changed.

## Essences

Confirmed by inspecting the real vendored data (not assumed -- see
`domain.essences` module docstring): an essence's power tier is encoded
entirely in its *name* ("Greater Essence of X", "Perfect Essence of X", ...),
not in any nested tier-progression field. Non-Perfect essences (Lesser/Normal/
Greater, plus ~11 uniquely-named ones like "Adaptive Alloy" with no tier
variants) guarantee a mod from the normal rollable pool; Perfect essences
guarantee a mod from a dedicated 75-mod essence-exclusive pool
(`ModCategory.ESSENCE_ONLY`, CoE `id_mgroup=13`) that's never obtainable by
normal rolling -- confirmed by several of those mods having `weight=0` in the
general pool. A target spec can name an essence-exclusive mod as a target; the
solver correctly treats reaching it as *requiring* essence use (there is no
other action that can ever produce it), not merely an efficiency choice.

A handful of essences grant 2-3 mods simultaneously on certain bases
(hybrid essences) -- `EssenceAction` adds all of a grant's mods in one
application and checks room/group-exclusion for all of them jointly before
considering itself applicable.
