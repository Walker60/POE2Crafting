# Data provenance

This project vendors static snapshots of two community-maintained datasets rather
than scraping them live at runtime. Neither is an official GGG API; both are
treated as a legal/ToS gray area (see "Stance" below).

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

## Stance on scraping / redistribution

Both sources are community-maintained hobby projects, not official APIs, and
their exact terms of use are unclear. This project:

- fetches each source **manually/occasionally** (via `scripts/fetch_*.py`),
  never automatically or at package runtime;
- **caches vendored snapshots locally** under `data/vendor/` and works entirely
  offline from `data/compiled/poe2_gamedata.json` afterwards;
- is a **personal, non-commercial tool** and does not redistribute the raw
  vendored datasets as a product;
- attributes both sources here and in the compiled gamedata's `meta.sources`.

If either site's terms change or an issue is raised, the vendored snapshot
should be removed and re-sourced.

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
