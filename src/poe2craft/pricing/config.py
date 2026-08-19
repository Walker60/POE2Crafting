"""Where the one secret this package needs (a PoE account session cookie)
comes from -- see docs/data_provenance.md for the full credential-handling
stance. Two sources, in precedence order (see `TradeConfig.load`):

1. The POE2CRAFT_POESESSID/POE2CRAFT_TRADE_LEAGUE environment variables
   (`from_env`) -- the original, process-lifetime-only mechanism.
2. A small local settings file the web UI's "Trade settings" panel edits
   (`poe2craft.pricing.settings_store.TradeSettingsStore`) -- a deliberate,
   disclosed tradeoff: plaintext on the user's own disk, gitignored, never
   sent anywhere except to pathofexile.com itself when a query actually
   runs, never round-tripped back through any API response.

Never logged or `repr()`'d, never a field on any web request/response model
other than write-only in `TradeSettingsUpdateRequest`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from poe2craft.pricing.errors import TradeConfigError

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[3] / "data" / "local" / "trade_settings.json"
"""`data/local/` is explicitly gitignored (see .gitignore) -- this file must
never be committed, since it can hold a real session cookie."""


def read_settings_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class TradeConfig:
    poesessid: str | None = field(default=None, repr=False)
    league: str | None = None

    @classmethod
    def from_env(cls) -> "TradeConfig":
        return cls(
            poesessid=os.environ.get("POE2CRAFT_POESESSID") or None,
            league=os.environ.get("POE2CRAFT_TRADE_LEAGUE") or None,
        )

    @classmethod
    def load(cls, settings_path: Path | None = None) -> "TradeConfig":
        """Environment variables as the baseline, overlaid by anything
        saved via the web UI's Trade settings panel -- the more recent,
        explicit action wins. An empty/absent field in the settings file
        falls back to the environment, not to "no value" -- see
        `poe2craft.pricing.settings_store.TradeSettingsStore` for how a
        deliberate "clear" is distinguished from "never set via the UI"."""
        env = cls.from_env()
        saved = read_settings_file(settings_path or DEFAULT_SETTINGS_PATH)
        return cls(poesessid=saved.get("poesessid") or env.poesessid, league=saved.get("league") or env.league)

    def require_league(self) -> str:
        if not self.league:
            raise TradeConfigError(
                "No PoE2 trade league configured -- set it in the web UI's Trade "
                "settings panel, or the POE2CRAFT_TRADE_LEAGUE environment variable, "
                "to the exact trade-site league name (e.g. the current challenge "
                "league). This is never guessed automatically: silently querying the "
                "wrong league's economy would be worse than refusing to run. See "
                "poe2craft.pricing.leagues.list_poe2_leagues for the real current "
                "options."
            )
        return self.league

    def cookie_header(self) -> dict[str, str]:
        """Built fresh at each call site from this immutable config -- never
        stored on a request object or logged."""
        return {"Cookie": f"POESESSID={self.poesessid}"} if self.poesessid else {}
