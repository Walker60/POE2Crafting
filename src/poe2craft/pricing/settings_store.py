"""Read/write side of the locally-persisted trade settings the web UI's
Trade settings panel edits. See `poe2craft.pricing.config.TradeConfig.load`
for how these combine with the POE2CRAFT_* environment variables, and
docs/data_provenance.md for the plaintext-local-file tradeoff this makes.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from poe2craft.pricing.config import DEFAULT_SETTINGS_PATH, TradeConfig, read_settings_file


class TradeSettingsStore:
    """One instance lives on `app.state` for the life of the server process
    (see `web.deps.get_trade_settings_store`). A single lock, not per-field
    -- this is a personal, single-user tool; the lock exists only to keep a
    read-modify-write update from racing a concurrent one, not to support
    real concurrent load (same posture as `web.session.SessionStore`)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_SETTINGS_PATH
        self._lock = Lock()

    def current(self) -> TradeConfig:
        """The effective config right now: this store's saved file,
        overlaid on the environment variables."""
        with self._lock:
            return TradeConfig.load(self._path)

    def update(self, league: str | None, poesessid: str | None, clear_poesessid: bool = False) -> TradeConfig:
        """Persists only fields the caller actually provided, merged with
        whatever is *already on disk* -- deliberately not the environment-
        overlaid `current()` view, so updating just the league can never
        silently copy an env-var-only POESESSID into the plaintext file.
        Returns the new effective (file-overlaid-on-env) config."""
        with self._lock:
            raw = read_settings_file(self._path)
            new_league = league if league is not None else raw.get("league")
            new_poesessid = None if clear_poesessid else (poesessid if poesessid is not None else raw.get("poesessid"))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"league": new_league, "poesessid": new_poesessid}), encoding="utf-8")
            return TradeConfig.load(self._path)
