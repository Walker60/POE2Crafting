# poe2craft

Solves Path of Exile 2 item crafting as a Markov decision process: learns an
empirical transition model for the currencies/essences/omens in scope, then
runs tabular value iteration to compute the optimal crafting policy toward a
target item spec -- "given this base and these target mods, what should I do
next, and how many steps/how much currency should it take?"

Modeled after [dennybritz.com/posts/poe-crafting](https://dennybritz.com/posts/poe-crafting/)
(a PoE1 tool written in Rust); this is a from-scratch Python implementation
for PoE2's real crafting mechanics and mod data. See `docs/design_notes.md`
for the full design rationale, scope decisions, and known limitations, and
`docs/data_provenance.md` for where the game data comes from.

## Setup

```
uv sync
```

## Usage

```
uv run poe2craft solve examples/amulet_life_regen.yaml --out out/policy.json
uv run poe2craft simulate examples/amulet_life_regen.yaml out/policy.json --n 300
uv run poe2craft explain "Orb of Alchemy"
```

`solve` learns the transition model (Monte Carlo sampling each reachable
(state, action) pair) and runs value iteration, printing the recommended next
action and expected steps/cost from the start state. `simulate` replays a
saved policy against the real sampler for concrete worked examples and as a
sanity check against the solver's predicted expected value. `explain` prints
poe2db-sourced mechanic text for a currency or omen (currently empty --
poe2db scraping is a documented follow-up, see `docs/data_provenance.md`).

A target spec is a small YAML file -- see `examples/*.yaml`:

```yaml
base: Amulet
ilvl: 80
target_mods:
  - mod_id: "5049"        # ids come from data/compiled/poe2_gamedata.json
    name: "# Life Regeneration per second"
    min_ilvl: 0            # optional: require at least this tier (0 = any tier). See examples/sword_tiered_target.yaml
start_rarity: normal
start_mod_ids: []
objective: steps          # "steps" or "cost"
max_steps: 30
```

## What's implemented

- **Data layer**: Craft of Exile's full PoE2 mod/tier/base dataset, parsed and
  validated into `data/compiled/poe2_gamedata.json` (`poe2craft.data`).
- **Engine**: the core currency loop -- Transmutation, Augmentation, Alchemy,
  Regal, Divine, Annulment, Chaos, Exalted, Fracturing -- plus **Desecration**
  (bones: reveal 3 random Desecrated modifiers, pick 1 -- the first action
  where the outcome is a *choice* among candidates rather than a single
  random draw, see `docs/design_notes.md`) -- as action wrappers
  (`poe2craft.engine`). Weighted mod sampling respects group exclusion, ilvl
  gating, and rarity-based prefix/suffix caps.
- **21 omens**, confirmed against poe2db.tw's omen catalog except the
  Desecration-related ones (poe2db doesn't document Desecration at all --
  confirmed against several current PoE2 guides instead, see
  `docs/design_notes.md`): Sinistral/Dextral Annulment, Exaltation, Alchemy,
  Coronation (Regal), Erasure (Chaos), and Necromancy (Desecration reveal);
  Greater Annulment/Exaltation (removes/adds 2 instead of 1); Whittling
  (Chaos removes the *lowest-level* modifier, deterministically);
  Sinistral/Dextral Crystallisation (restricts a Perfect Essence's removal
  step); Homogenising Coronation/Exaltation (restricts the add to a mod
  sharing a broad category tag -- fire/caster/life/etc. -- with an existing
  modifier); Abyssal Echoes (rerolls a Desecration reveal once); and Light
  (Annulment removes only a Desecrated modifier). The solver genuinely uses
  these -- e.g. solving for a single suffix mod on an Amulet drops from
  ~12.6 to ~7.9 expected steps once Dextral Alchemy (max suffixes) is in the
  action set. 8 more omens are deferred (Catalyst quality, 4 Waystone-
  specific ones, and 3 restricted to "Lich" modifiers with no confirmed tag
  data -- see `docs/design_notes.md`).
- **Greater/Perfect tiers** of Transmutation, Augmentation, Regal, Chaos, and
  Exalted: each restricts its roll to mods whose tier requires at least a
  minimum modifier level, confirmed directly from poe2db.tw's item pages
  (Transmutation/Augmentation: 44/70; Regal/Chaos/Exalted: 35/50 -- see
  `engine.apply.MIN_ILVL_BY_TIER`). This concentrates odds toward
  stronger/rarer mods rather than changing how many affixes get added, and the
  solver can and does pick a tiered orb when the odds improvement is worth it
  under the "steps" objective. Omens currently only wrap base-tier
  Annulment/Exalted/Alchemy/Regal/Chaos, not Greater/Perfect ones -- see
  `docs/design_notes.md`.
- **Real currency costs, in Divine Orb terms**: every currency, tier variant,
  omen, and essence this project models is priced from poe2db.tw's live
  economy page (`GameData.prices`, see `docs/data_provenance.md`) -- not a
  guess. Using an omen adds its own real price on top of the base currency's
  (you consume both), so e.g. `Exalted Orb (Omen: suffixes only)` genuinely
  costs more than plain `Exalted Orb`. The `cost` objective's "expected cost"
  output is therefore a real Divine-Orb-equivalent estimate, not an arbitrary
  unit -- e.g. a real solve for 2 Body Armour mods came back at "0.47" (Divine
  Orbs). A handful of names not currently traded on that page (Fracturing
  Orb, Gnawed/Ancient Cranium, 7 of the 21 omens, ~53 of 95 essences) fall
  back to a documented placeholder (`engine.apply.DEFAULT_COSTS`/
  `FALLBACK_OMEN_COST`/`FALLBACK_ESSENCE_COST`), calibrated from the real
  prices actually observed rather than an arbitrary guess. All 12 Desecration
  bones and every Desecration-related omen are real, live-priced quotes, not
  guesses -- fixing a real parser bug along the way (it silently dropped any
  item priced *above* 1 Divine Orb, e.g. "1 Ancient Collarbone <-> 4.76
  Divine Orb", since it only recognized the inverse "cheap item <-> 1 Divine
  Orb" row shape).
- **Essences**, all 95 of them: non-Perfect tiers (Lesser/Normal/Greater, plus
  ~11 uniquely-named essences) guarantee a normal-pool mod on a Magic->Rare
  transition, like a targeted Regal Orb; Perfect essences remove one existing
  mod and guarantee an essence-exclusive mod (never obtainable by normal
  rolling -- confirmed by weight=0 entries in the general pool), like a
  targeted, guaranteed-hit Chaos Orb. A target mod may itself be
  essence-exclusive -- the solver correctly discovers that reaching it
  requires essence use, not just efficient use (see the
  `examples/body_armour_essence_life.yaml` example, which solves in exactly 2
  deterministic steps: any Rare item, then the essence).
- **Solver**: target-relative state featurization, Monte Carlo transition
  learning via lazy BFS, and infinite-horizon discounted value iteration
  (`poe2craft.solver`). A target mod can optionally request a minimum tier
  (`min_ilvl`) -- the abstract state then distinguishes "absent" from
  "present but below the requested tier" from "satisfied", so the solver can
  reason about (and recommend actions toward) re-rolling a mod that showed up
  too weak, not just whether it showed up at all (see
  `examples/sword_tiered_target.yaml`).
- **Live trade pricing** (`poe2craft.pricing`, optional -- see "Live trade
  pricing" below and `docs/data_provenance.md`): queries
  pathofexile.com/trade2 on demand to answer two things the solver's own
  currency-based cost estimate can't: what real market premium a modifier
  carries (`poe2craft mod-price`), and -- mid-craft -- whether it's cheaper
  to keep crafting, buy the target outright, or sell the current item and
  start over (`poe2craft trade-compare`, or the web UI's "Compare vs.
  market" button). Deliberately never automatic: fires only on that
  explicit CLI command or button click, never on session creation,
  `advance`, or any polling.
- **CLI**: `solve` / `simulate` / `explain` / `mod-price` / `trade-compare`
  (`poe2craft.cli`).

## What's not implemented yet

- **poe2db scraping** (the omen catalog and currency mechanic text) is stubbed
  in `poe2craft.data.poe2db_parse` -- `scripts/fetch_poe2db_pages.py` and
  `scripts/build_gamedata.py` are wired up to consume it once written.
- Recombinators, Vaal/corruption, Runes/Soul Cores, and quality/Catalysts are
  deliberately out of scope for the solver -- see `docs/design_notes.md`.
  Desecrated mods *are* now in scope (bones); Altered Collarbone (a rare
  Genesis-Tree-only bone variant) and the 3 omens restricted to "Lich"
  modifiers remain deferred within that mechanic specifically.

## Tests

```
uv run pytest
```

Unit tests use small hand-built fixtures (fast, isolated from upstream data
changes); `tests/unit/test_coe_parse.py` checks the real vendored dataset's
invariants; `tests/toy_mdp/` verifies value iteration against hand-computed
closed-form answers; `tests/integration/` runs real solves across several
base groups (weapon/armour/jewellery/jewel) against the full compiled
gamedata.

## Refreshing game data

```
uv run python scripts/refresh_all_data.py
```

Re-scrapes every vendored source (Craft of Exile's mod/base/tier dataset,
poe2db's omen/currency pages, poe2db's live economy prices) and rebuilds
`data/compiled/poe2_gamedata.json` in one command -- run this after a PoE2
patch, or whenever you want current currency prices (see the "Real currency
costs" note above -- these drift). Still a manual, user-invoked action, never
automatic. See `docs/data_provenance.md` for sources, the scraping/
redistribution stance, and how to refresh just one source instead.

## Live trade pricing (optional)

`poe2craft mod-price`/`trade-compare` and the web UI's "Compare vs. market"
button query pathofexile.com/trade2 for real listing prices -- **not** part
of the offline currency-cost pipeline above, and **never fired
automatically** (see `docs/data_provenance.md` for why these particular
endpoints are a knowingly-accepted ToS conflict, not a routine data source,
and what's done to keep that contained).

One-time setup:

```
uv run python scripts/fetch_trade_stats.py
uv run python scripts/build_trade_stat_mapping.py
```

Then set the league to query (never guessed automatically) and optionally
your account's session cookie (works logged out too, just rate-limited
harder -- see `docs/data_provenance.md` for exactly how this credential is
and isn't handled). Two ways to do this, checked in this order (a later one
overrides an earlier one -- see `TradeConfig.load`):

1. **The web UI's "Trade settings" panel** (in the app's header) -- a
   dropdown of the real, currently-active PoE2 leagues (fetched live from
   GGG's official Leagues endpoint) plus a POESESSID field. Saved to
   `data/local/trade_settings.json`, which is gitignored -- see
   `docs/data_provenance.md` for the plaintext-local-file tradeoff this
   makes, in exchange for not having to re-enter the cookie every restart.
2. **Environment variables**, per shell session -- works for the CLI too,
   not just the web UI:

   ```
   export POE2CRAFT_TRADE_LEAGUE="Standard"     # the exact trade-site league name
   export POE2CRAFT_POESESSID="..."             # optional
   uv run poe2craft mod-price 5049 --base Amulet
   uv run poe2craft trade-compare examples/amulet_life_regen.yaml
   ```
# POE2Crafting
