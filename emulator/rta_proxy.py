"""
rta_proxy.py — FULLY LOCAL Real-Time Activity (rta.xboxlive.com) mock. No
real Microsoft backend involved - just accepts the websocket upgrade and
acknowledges whatever the client subscribes to, so it never times out
waiting for a real connection.

2026-08-15: replaced the old real-MITM version (backed up to
rta_proxy_real_mitm.py.bak) - that version dialed the REAL rta.xboxlive.com
via session_proxy._resolve_real_ip(), a helper that only ever existed on
the OLD real-MITM session_proxy.py. When session_proxy.py was rewritten to
the fully-local MPSD mock (2026-08-12, see project memory
sot-lighthouse-vs-mpsd-diagnosis.md), this module was never updated to
match and kept calling that now-missing function - a real, live-confirmed
bug: every request routed here (including PlayFabPartyXbl/1.0's own
"GET /connect" websocket-upgrade calls to rta.xboxlive.com, not just the
game's own RTA subscribe traffic) 500'd with
"AttributeError: module 'session_proxy' has no attribute '_resolve_real_ip'"
- a real, concrete cause of user-visible Xbox Live/matchmaking errors this
whole session, unrelated to networking/VPN/account state.

Ported from noxboxemulator/rta_proxy.py (an isolated same-day fully-local
sibling of this file that never had this bug, since it was written fresh
against the fully-local design from the start). Confirmed via a full day
of live capture on the OLD real-MITM version (see project memory): this
build's client ONLY ever subscribes to two topics, both privacy-list
related (`https://privacy.xboxlive.com/users/xuid(...)/neverlist` and
`.../mutelist`) - never anything session/matchmaking-related - so a
generic "ack every subscribe, never push anything real" implementation is
known to be sufficient for the game's own RTA traffic. Whether
PlayFabPartyXbl's own separate `/connect` usage of this same host needs
anything more than a bare ack is untested as of this note - if Party
still misbehaves after this fix, that's the next thing to check.

Real RTA wire protocol (Xbox Live's own, not something we invented):
  Subscribe:        [1, seq, "<uri>"]
  Subscribe ack:     [1, seq, statusCode, subscriptionId, null]
  Unsubscribe:       [2, seq, subscriptionId]
  Unsubscribe ack:   [2, seq, statusCode]
Frames are sent as TEXT with a trailing NUL byte, matching every real
capture seen in this project.
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

log = logging.getLogger("emulator.rta_proxy")


async def handle(request: web.Request) -> web.WebSocketResponse:
    requested_protocols = [
        p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()
    ]
    ws = web.WebSocketResponse(protocols=requested_protocols or None, heartbeat=20)
    await ws.prepare(request)
    log.info("[rta-local] client connected: %s (requested protocols=%s)", request.path_qs, requested_protocols)

    next_subscription_id = 1
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            raw = msg.data.rstrip("\x00")
            log.info("[rta-local] client->local: %r", raw)
            try:
                frame = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(frame, list) or not frame:
                continue
            opcode = frame[0]
            if opcode == 1 and len(frame) >= 3:
                seq = frame[1]
                sub_id = next_subscription_id
                next_subscription_id += 1
                ack = [1, seq, 0, sub_id, None]
                await ws.send_str(json.dumps(ack) + "\x00")
                log.info("[rta-local] local->client: %r", ack)
            elif opcode == 2 and len(frame) >= 3:
                seq = frame[1]
                ack = [2, seq, 0]
                await ws.send_str(json.dumps(ack) + "\x00")
                log.info("[rta-local] local->client: %r", ack)
    except Exception as e:
        log.warning("[rta-local] session error: %r", e)
    finally:
        log.info("[rta-local] client disconnected: %s", request.path_qs)
    return ws
