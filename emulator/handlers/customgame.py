"""
handlers/customgame.py — GET /ares/customgame/api/checkcreatepermission.

No real capture of this endpoint exists in flows.jsonl (it only shows up as
a discovery service entry, never actually called during the captured
session), so this is a guess: grant permission via every plausible field
name a permission-check response might use, since extra unknown JSON keys
are harmless and we don't know which one the client actually reads.

Why this matters: with the current build's real Xbox Live infrastructure
still alive (confirmed via Frida - sessiondirectory.xboxlive.com session
creation succeeds), matchmaking into a *dedicated* server ends in
Bronzebeard because no real Rare backend is left to register an actual
game server for that Xbox Live session. A Custom Game (private session)
might use a listen-server model (one client hosts) instead of needing a
Rare-provisioned dedicated server - if so, granting permission here is the
one guess-able gate keeping that path shut.
"""
from __future__ import annotations

from aiohttp import web

from . import route


@route("GET", "/ares/customgame/api/checkcreatepermission")
async def check_create_permission(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "hasPermission": True,
            "canCreate": True,
            "isAllowed": True,
            "allowed": True,
            "permitted": True,
            "canCreateCustomGame": True,
            "reason": None,
            "reasonCode": None,
            "denyReason": None,
        }
    )
