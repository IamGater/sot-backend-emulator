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

import re
from typing import Awaitable, Callable

from aiohttp import web

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_HANDLERS: dict[tuple[str, str], Handler] = {}

# Same reasoning/pattern as fixtures.py's _strip_ids(): a handler path like
# "/ares/loadout/api/user/<xuid>/pirate/<guid>/loadout" is registered once
# with literal placeholder text, but the real request path carries whatever
# XUID/pirate-GUID the currently signed-in account actually has - normalize
# both sides the same way so @route(..., "/ares/.../user/XUID/pirate/GUID/...")
# matches regardless of the real ids.
_XUID_RE = re.compile(r"/user/\d{10,20}")
_GUID_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _strip_ids(path: str) -> str:
    path = _XUID_RE.sub("/user/XUID", path)
    path = _GUID_RE.sub("/GUID", path)
    return path


def route(method: str, path: str):
    """Decorator: @route("POST", "/ares/login/") registers a handler.
    app.py normalizes trailing slashes before lookup, so `path` doesn't
    need to worry about matching exactly one way or another. For paths
    containing a real XUID/pirate-GUID segment, write the literal example
    value (e.g. copy one from a fixture path) — it gets id-stripped the
    same as the incoming request, so the literal value itself doesn't
    matter, only its position/shape."""
    key = (method.upper(), _strip_ids(path.rstrip("/") or "/"))

    def deco(fn: Handler) -> Handler:
        _HANDLERS[key] = fn
        return fn

    return deco


def find(method: str, path: str) -> Handler | None:
    method = method.upper()
    normalized = path.rstrip("/") or "/"
    handler = _HANDLERS.get((method, normalized))
    if handler:
        return handler
    return _HANDLERS.get((method, _strip_ids(normalized)))


# import submodules so their @route decorators register themselves
from . import login  # noqa: E402,F401
from . import customgame  # noqa: E402,F401
from . import contestmatchmaking  # noqa: E402,F401
from . import loadout  # noqa: E402,F401
