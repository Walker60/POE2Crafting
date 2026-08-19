"""FastAPI app factory. `poe2craft serve` (cli/main.py) runs this via uvicorn;
tests construct it directly with `create_app(gamedata_path=...)` for a small
test fixture instead of the full real dataset."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from poe2craft.data.loader import GameData, load_gamedata
from poe2craft.web import catalog, crafting
from poe2craft.web.session import SessionStore

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(gamedata_path: Path | None = None, gamedata: GameData | None = None) -> FastAPI:
    """`gamedata`, if given, is used directly (e.g. a small hand-built
    fixture in tests) -- otherwise loads from `gamedata_path` (or its default,
    or the `POE2CRAFT_GAMEDATA_PATH` env var `poe2craft serve` relays an
    override through, see cli.main.serve)."""
    app = FastAPI(title="poe2craft")

    if gamedata is None:
        if gamedata_path is None:
            env_path = os.environ.get("POE2CRAFT_GAMEDATA_PATH")
            gamedata_path = Path(env_path) if env_path else None
        gamedata = load_gamedata(gamedata_path)
    app.state.gamedata = gamedata
    app.state.sessions = SessionStore()

    app.include_router(catalog.router)
    app.include_router(crafting.router)

    # Built frontend (`npm run build` under frontend/) is optional -- absent
    # during backend-only development, present for normal local use so
    # `poe2craft serve` alone (no Node at runtime) serves everything.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
