"""FastAPI dependencies -- both just pull off `app.state`, set once at startup
in `web.app.create_app` (GameData is loaded once, not per request)."""
from __future__ import annotations

from fastapi import Request

from poe2craft.data.loader import GameData
from poe2craft.web.session import SessionStore


def get_gamedata(request: Request) -> GameData:
    return request.app.state.gamedata


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions
