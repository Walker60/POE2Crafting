"""FastAPI app factory. `poe2craft serve` (cli/main.py) runs this via uvicorn;
tests construct it directly with `create_app(gamedata_path=...)` for a small
test fixture instead of the full real dataset."""
from __future__ import annotations

import os
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from poe2craft.data.loader import GameData, load_gamedata
from poe2craft.pricing.settings_store import TradeSettingsStore
from poe2craft.solver.parallel import health_check, make_executor
from poe2craft.web import catalog, crafting, solve_status, trade_settings
from poe2craft.web.session import SessionStore
from poe2craft.web.solve_status import SolveStatusTracker

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup work happens synchronously in create_app() itself, not here --
    # tests/web/conftest.py's TestClient(app) fixture isn't used as a context
    # manager, so Starlette never runs lifespan *startup* for it; anything
    # startup-critical gated behind this would silently never happen in
    # tests. Shutdown has no such issue (the process pool just needs to be
    # reaped eventually, and this is the only clean hook a factory function
    # offers for that).
    yield
    executor = getattr(app.state, "executor", None)
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)


def create_app(
    gamedata_path: Path | None = None,
    gamedata: GameData | None = None,
    n_pool_workers: int | None = None,
    trade_settings_path: Path | None = None,
) -> FastAPI:
    """`gamedata`, if given, is used directly (e.g. a small hand-built
    fixture in tests) -- otherwise loads from `gamedata_path` (or its default,
    or the `POE2CRAFT_GAMEDATA_PATH` env var `poe2craft serve` relays an
    override through, see cli.main.serve).

    `n_pool_workers`, if not given, reads `POE2CRAFT_POOL_WORKERS` and
    defaults to **0 (disabled)** if that isn't set either -- deliberately not
    `os.cpu_count()`. This module has `app = create_app()` at the bottom
    (needed for `uvicorn "poe2craft.web.app:app"`'s string import), which
    means *any* import of this module -- including `from poe2craft.web.app
    import create_app` in test fixtures -- runs that line, so a CPU-count
    default here would silently spin up a real, unmanaged process pool (with
    a full real-gamedata load) just from importing the module in a test
    session. `cli.main.serve()` is the one place that actually wants the pool
    on by default for real usage -- it sets `POE2CRAFT_POOL_WORKERS` itself
    (the same env-var-relay pattern already used for `gamedata_path`, needed
    because an override can't cross uvicorn's string-import boundary as a
    live value) before uvicorn imports this module."""
    app = FastAPI(title="poe2craft", lifespan=_lifespan)

    if gamedata is None:
        if gamedata_path is None:
            env_path = os.environ.get("POE2CRAFT_GAMEDATA_PATH")
            gamedata_path = Path(env_path) if env_path else None
        gamedata = load_gamedata(gamedata_path)
    app.state.gamedata = gamedata
    app.state.sessions = SessionStore()
    # `trade_settings_path`, if not given, defaults to the real
    # data/local/trade_settings.json (see pricing.config.DEFAULT_SETTINGS_PATH)
    # -- tests pass an isolated tmp_path so they never read/write the real
    # local settings file.
    app.state.trade_settings = TradeSettingsStore(trade_settings_path)
    app.state.solve_status = SolveStatusTracker()

    if n_pool_workers is None:
        n_pool_workers = int(os.environ.get("POE2CRAFT_POOL_WORKERS", "0"))
    app.state.executor = None
    if n_pool_workers > 0:
        executor = make_executor(gamedata, max_workers=n_pool_workers)
        if health_check(executor):
            app.state.executor = executor
        else:
            executor.shutdown(wait=False)
            warnings.warn("poe2craft: process pool self-test failed; falling back to sequential solving", stacklevel=2)

    app.include_router(catalog.router)
    app.include_router(crafting.router)
    app.include_router(trade_settings.router)
    app.include_router(solve_status.router)

    # Built frontend (`npm run build` under frontend/) is optional -- absent
    # during backend-only development, present for normal local use so
    # `poe2craft serve` alone (no Node at runtime) serves everything.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
