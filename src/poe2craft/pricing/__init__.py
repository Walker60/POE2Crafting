"""Live pathofexile.com/trade2 pricing: what a modifier is actually worth on
the market, and buy-vs-craft-vs-sell comparisons for an in-progress craft.

A separate axis from `poe2craft.data`/`GameData.prices` (currency/omen/
essence costs from a periodic poe2db.tw snapshot) -- this package queries
trade listings live, on demand, never automatically. See
docs/data_provenance.md for the ToS situation, the credential-handling
stance, and the "opt-in only" trigger model this package must never violate.
"""
