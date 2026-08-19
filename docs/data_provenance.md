# Data provenance

This project vendors static snapshots of two community-maintained datasets rather
than scraping them live at runtime. Neither is an official GGG API; both are
treated as a legal/ToS gray area (see "Stance" below).

A third source, pathofexile.com/trade2, is different in kind: it's queried
live, per-request, on explicit user action only -- never cached as a static
snapshot, and not a gray area in the same sense as the two above (see its own
"Sources" entry and "Stance" note below for exactly how it differs).

## Sources

### Craft of Exile (primary)

- URL: `https://www.craftofexile.com/json/poe2/main/poec_data.json`
- Format: a `poecd={...}` JS-variable-wrapped JSON blob (~3 MB), stripped by
  `poe2craft.data.coe_parse`.
- Provides: base items, base groups (slot metadata: max affixes, max sockets),
  modifiers (name, affix, source-category, mutual-exclusion groups), per-base
  per-modifier tiers (ilvl gate, spawn weight, value ranges), essences,
  socketables (runes/soul cores), catalysts.
- Does **not** provide: currency mechanics or the omen catalog at all -- CoE
  hardcodes those in its site's JS rather than data-driving them.
- No `robots.txt` or explicit terms of use were found for this JSON endpoint at
  the time of vendoring (2026-08-18).

### poe2db.tw (secondary)

- Plain server-rendered HTML. `robots.txt` allows all (`Allow: /`).
- Provides the omen catalog and currency mechanic descriptions -- the only
  source for either. Fetched as a small number of targeted pages, not a crawl.
- Value ranges embedded in modifier description text and non-numeric weight
  strings need regex extraction; see `poe2craft.data.poe2db_parse`.
- Also provides **live currency/omen/essence prices in Divine Orb terms**, via
  its `Economy_divine` page (`data/vendor/poe2db/economy_divine.html`,
  parsed by `poe2db_parse.parse_economy_divine`) -- a single table of every
  traded item paired against 1 Divine Orb. This page has two similarly-placed
  numeric columns ("24h Value" = the actual exchange rate, "24h volume
  traded" = an unrelated trade-count) that are easy to transpose by accident;
  caught during this project by cross-checking a known real-world ratio
  (Chaos Orb) before trusting the parse -- see the parser's docstring.
  **These are live market prices, not fixed constants** -- expect them to
  drift meaningfully between refreshes; that's real, not a bug.

### pathofexile.com/trade2 (live pricing -- unofficial, opt-in)

- **This one is a knowingly-accepted ToS conflict, not an unclear gray
  area.** GGG's officially documented API (`pathofexile.com/developer/docs`)
  lists Account Profile/Leagues/Characters/Currency Exchange -- no trade
  search endpoint. The `POST /api/trade2/search/poe2/{league}` and
  `GET /api/trade2/fetch/{ids}` endpoints this project's `poe2craft.pricing`
  package uses are the trade *website's own internal endpoints*, hit
  directly the way every community trade tool does. The docs page states
  plainly: "Requests for access to any other internal website APIs... will
  be denied. It is against our Terms of Use [section 7i] to reverse-engineer
  endpoints outside of this documentation." This was reviewed and accepted
  deliberately (not re-litigated here) for this personal, non-commercial
  tool -- if that changes, or GGG raises an issue, this integration should be
  removed immediately, not just reconsidered.
- **Credential**: using it authenticated means passing your own PoE account's
  POESESSID session cookie. Read once, from the `POE2CRAFT_POESESSID`
  environment variable (`poe2craft.pricing.config.TradeConfig`), never
  logged, never a field on any request/response model the web API exposes --
  it never leaves the server process. Optional: it works logged out too,
  just rate-limited harder.
- **`GET /api/trade2/data/stats`** (the stat-filter catalog used to map this
  project's mod ids to trade's `stat_XXXXXXXX` ids, see
  `poe2craft.pricing.stat_matching`) sits under the same unofficial
  `/api/trade2/` path, but needs no cookie/account -- lower risk than
  search/fetch, though not on genuinely different legal footing.
- **Leagues** (`api.pathofexile.com/leagues`, used only to validate a
  configured league name) *is* part of GGG's documented API -- a materially
  different footing from everything else in this section, called out
  explicitly so it's never conflated with the unofficial endpoints.
- Exact request/response JSON shapes came from community-tool consensus
  (the convention PoE1's long-documented-by-the-community trade API uses,
  which trade2 closely mirrors), not official docs, and could silently
  change if GGG alters trade2's internals. `poe2craft.pricing`'s client
  fails loudly (`TradeAPIError`) on any unexpected shape rather than
  guessing -- a wrong price is worse than a refusal to answer.

## Stance on scraping / redistribution

Craft of Exile and poe2db.tw are community-maintained hobby projects, not
official APIs, and their exact terms of use are unclear. This project:

- fetches each source **manually/occasionally** (via `scripts/fetch_*.py`),
  never automatically or at package runtime;
- **caches vendored snapshots locally** under `data/vendor/` and works entirely
  offline from `data/compiled/poe2_gamedata.json` afterwards;
- is a **personal, non-commercial tool** and does not redistribute the raw
  vendored datasets as a product;
- attributes both sources here and in the compiled gamedata's `meta.sources`.

If either site's terms change or an issue is raised, the vendored snapshot
should be removed and re-sourced.

**pathofexile.com/trade2 is a genuinely different shape**, not just another
entry in the list above: comparable-listings data is stale within minutes,
so it's never cached as a snapshot the way the other two are -- every
`poe2craft.pricing` lookup is a real, live, per-query request. To keep that
contained to what was actually reviewed and accepted:

- it fires **only** on an explicit trigger -- the `mod-price`/`trade-compare`
  CLI commands, or the web UI's "Compare vs. market" button click -- **never**
  from session creation, `advance`, polling, a timer, or any other automatic
  path. If you ever find it firing outside one of those two triggers, that's
  a bug, not a feature;
- the `stats.json` catalog snapshot (`data/vendor/pathofexile_trade2/`,
  `scripts/fetch_trade_stats.py`) *is* refreshed the same manual/occasional
  way as the other two sources -- only the search/fetch calls themselves are
  live per-query;
- see the credential/failure-mode notes in its "Sources" entry above for the
  rest of this source's specific handling.

## Refresh procedure

Run `uv run python scripts/refresh_all_data.py` to do all of the below in one
go (still a manual, user-invoked action -- this doesn't run automatically or
at package runtime, it just saves running four commands by hand). It
continues past a single source failing (e.g. a network hiccup) rather than
aborting, rebuilds gamedata from whatever's vendored either way, and exits
non-zero if anything failed to refresh so that doesn't go unnoticed.

To refresh just one source instead:

1. `uv run python scripts/fetch_coe_data.py` -- re-downloads
   `data/vendor/coe_poe2_data.json`.
2. `uv run python scripts/fetch_poe2db_pages.py` -- re-downloads the omen and
   currency pages under `data/vendor/poe2db/`.
3. `uv run python scripts/fetch_coe_prices.py` -- re-downloads
   `data/vendor/poe2db/economy_divine.html` (live prices; refresh this one
   more often than the other two if solve costs need to track the current
   market, not a snapshot).
4. `uv run python scripts/build_gamedata.py` -- re-parses all three into
   `data/compiled/poe2_gamedata.json`, printing any new parse warnings or
   referential-integrity issues. Re-run the test suite afterwards -- a patch
   that changes mod weights or adds/removes bases can silently change solver
   output.

Separately (not part of `refresh_all_data.py`, and not needed for normal
crafting solves -- only for the `mod-price`/`trade-compare`/"Compare vs.
market" trade-pricing feature):

5. `uv run python scripts/fetch_trade_stats.py` -- re-downloads
   `data/vendor/pathofexile_trade2/stats.json`.
6. `uv run python scripts/build_trade_stat_mapping.py` -- rebuilds
   `data/compiled/trade_stat_mapping.json` (mod id -> trade stat id),
   printing any mods it couldn't match by text so they can be reviewed and,
   if genuinely a wording mismatch rather than a real gap, added to
   `poe2craft.pricing.stat_matching._STAT_ID_OVERRIDE`.

## Known upstream data gaps (as of the 2026-08-18 snapshot)

- **6 base items** (ids 51, 68, 200, 230-232) are referenced by `basemods`/
  `tiers` but missing from CoE's own `bases` table -- CoE hadn't synced a few
  patch-0.5 hybrid-attribute armour bases yet. Four are identifiable from their
  `bitems` (STR/DEX/INT Body Armour/Helmet/Gloves/Boots) and patched in by
  `coe_parse._ORPHAN_BASE_PATCH`; two (68, 200) have no matching `bitems` at all
  and are parked under a synthetic "Unknown" base group rather than dropped, so
  their ~200 mods' worth of tier data isn't silently lost.
- **`nvalues` value-range ambiguity**: see the docstring on
  `coe_parse._parse_value_ranges` and `docs/design_notes.md` -- affects only the
  numeric display/reroll value, never which mods are eligible or their weights.
- **Incomplete modifier weights (this one does affect the solver)**: ~40% of
  rollable mods have at least one tier stuck at `weighting=1` (27% of them
  entirely), confirmed by scraping Craft of Exile's own live JS (`js/poe2.js`,
  `packages/package.js` via direct `curl`, not the main data JSON) -- their
  site reads weight the identical way this project does, from the identical
  file, so this is genuinely their current data, not a stale vendor snapshot
  or a parsing bug here. Root cause per CoE's own published methodology:
  weights are inferred from trade-listing parsing and community recombinator
  research, both incomplete for less-observed mod/base combinations. See
  `docs/design_notes.md` for the full writeup and what it means for solve
  accuracy on an affected target.
- **Trade stat mapping coverage (as of the first real build, 2026-08-19)**:
  `scripts/build_trade_stat_mapping.py` matched 1121 of 1364 mods (82%)
  against the real `/api/trade2/data/stats` catalog; the 243 unmatched split
  roughly in half between two different root causes, neither fixed by
  adding more `_STAT_ID_OVERRIDE` entries:
  - **~118 are hybrid mods** ("#% increased Armour, +# to Stun Threshold"):
    trade represents a hybrid stat as *multiple separate* stat filters, not
    one combined one, so a single mod_id -> single stat_id mapping is the
    wrong shape for these entirely -- `build_mod_stat_mapping` correctly
    reports them as unmatched rather than guessing which half to keep, but
    pricing/buying/selling an item carrying one of these hybrid mods isn't
    supported by v1's trade-pricing feature. A real fix would change the
    mapping's value type to a list of stat ids per hybrid mod and adjust
    every query-building call site accordingly -- not done yet.
  - **~125 are non-hybrid mods with no catalog match at all**, heavily
    skewed toward map/Waystone-affecting modifiers ("#% increased Quantity
    of Items found in your Maps", "#% increased Pack size", etc.) -- these
    may genuinely not be explicit-stat-filterable on trade (some can't
    plausibly be an *item* modifier trade would search by mod at all), not
    just a wording mismatch this project's text-normalization missed.
    Reviewed at a sample level, not mod-by-mod -- treat any specific one of
    these as unconfirmed until checked against a real trade search.
