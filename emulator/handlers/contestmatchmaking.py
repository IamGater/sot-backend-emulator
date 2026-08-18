"""
handlers/contestmatchmaking.py — GET /contestmatchmaking/app/api/client/locations.

2026-08-15: this whole "contestmatchmaking" REST API (separate from Xbox
Live MPSD - see project memory sot-lighthouse-vs-mpsd-diagnosis.md) was a
purely static, never-confirmed-live lead for weeks: found via string-hunt
in SoTGame.exe (real C++ model classes: ContestMatchmakingClientRequestModel/
ResponseModel, ...ServerRequestModel, ...LocationsResponseModel,
...CrewModel), routed through OUR OWN REWRITE_HOST via discovery.py, but
never once observed actually firing in run_session.log across this whole
project's history - until today, right after the rta_proxy.py/bridge
subprotocol fixes let the client get further than before. This endpoint
fired 7 times in ~13s (a real poll loop), previously answered with a blind
"no fixture/handler ... {}" by app.py's generic fallback.

Field names below (Locations, Result) are the highest-confidence guesses
from the string-pool proximity dump (tools/contestmatchmaking_models_ctx.txt)
- NOT confirmed via real UStruct/FProperty offsets like the MPSD schema
was. Deliberately minimal/conservative per this project's own established
lesson (see memory: "observe the real request first, then design the
response from what's actually seen, not more guessing") - one plausible
non-empty entry, not a large invented schema, specifically to see what the
client does NEXT (stop polling? call .../client or .../server?) rather
than assume this is already correct.

2026-08-15 follow-up: the first (minimal) version of this response DID
change client behavior - polled 2x in <1s then stopped (vs. 7x/13s with
the old blind {}), a real signal it's being read - but no .../client or
.../server call followed; the client just went quiet and Bronzebeard
appeared shortly after. Added SelectedPlayMode/SessionType (also found in
the same string-pool proximity dump, near ContestMatchmakingLocations
ResponseModel) on the chance the client needs one of these to actually
select a location and proceed - still a guess, not confirmed. If this
doesn't produce a .../client call either, treat this endpoint as
explored-and-inconclusive rather than continuing to guess more fields.
"""
from __future__ import annotations

import logging

from aiohttp import web

from . import route

log = logging.getLogger("emulator.contestmatchmaking")


@route("GET", "/contestmatchmaking/app/api/client/locations")
async def client_locations(request: web.Request) -> web.Response:
    body = {
        "Locations": [
            {"Name": "Local", "Region": "EastUs", "ServerLocation": "EastUs"},
        ],
        "Result": "Success",
        "SelectedPlayMode": "Adventure",
        "SessionType": "SmallShip",
    }
    log.info("[contestmatchmaking] GET client/locations -> %r", body)
    return web.json_response(body)
