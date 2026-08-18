"""
handlers/ — custom per-endpoint logic that overrides fixture replay.

Most of the game's backend can be answered by static replay (fixtures.py),
but some paths need dynamic behaviour (issuing tokens, echoing back part of
the request, tracking state across calls). Add a module here and register
a handler with @route — registered handlers are checked before
fixtures.find(), so they always win.

Example: see handlers/login.py.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from aiohttp import web

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_HANDLERS: dict[tuple[str, str], Handler] = {}


def route(method: str, path: str):
    """Decorator: @route("POST", "/ares/login/") registers a handler.
    app.py normalizes trailing slashes before lookup, so `path` doesn't
    need to worry about matching exactly one way or another."""
    key = (method.upper(), path.rstrip("/") or "/")

    def deco(fn: Handler) -> Handler:
        _HANDLERS[key] = fn
        return fn

    return deco


def find(method: str, path: str) -> Handler | None:
    return _HANDLERS.get((method.upper(), path.rstrip("/") or "/"))


# import submodules so their @route decorators register themselves
from . import login  # noqa: E402,F401
from . import customgame  # noqa: E402,F401
from . import contestmatchmaking  # noqa: E402,F401
