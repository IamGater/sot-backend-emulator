"""
bridge_state.py — shared registry of live /ws/bridge(2) websocket
connections, so session_proxy.py (which handles the real MITM'd MPSD
session PUT/GET) can push a message down the SAME channel the client is
already holding open, at the moment it injects a populated "servers"
field.

Why this exists (2026-08-12 finding): static analysis of the client exe
(SoTGame.exe, all tested depot builds) shows the "/ws/bridge" websocket
speaks a real, Rare-authored pub/sub protocol called "ServiceMessaging" -
NOT an opaque/binary one. A live capture during a real play session showed
the client subscribing to routes ("a":3 = subscribe) like
"EvictPlayerMessage.EvictionService.<xuid>" with envelope shape
{"a":<int>, "r":<route str>, "p":<payload obj>, "mid":<uuid>, "sq":0,
"sp":0, "sh":0}. The exe's UE4 reflection string table separately reveals
a message class **PlayerServerAssignmentMessage** with exactly 3 fields:
ConnectionToken, ConnectionKey, ServerAddress - i.e. a dedicated
"here is your server" push message, structurally exactly what's needed to
tell the client to connect, and completely independent of Xbox Live's
MPSD `servers`/secureDeviceAddress mechanism (which months of
reverse-engineering already proved the client never acts on in any tested
build - see project memory sot-lighthouse-vs-mpsd-diagnosis.md).

Working theory: the client doesn't dial out because it's waiting for a
PlayerServerAssignmentMessage push over THIS channel, not because it's
parsing (or failing to parse) the MPSD servers field. This module lets
session_proxy.py's _inject_server() trigger that push at the same moment
it patches the MPSD response, so the two arrive close together the way a
real backend's matchmaking-complete sequence presumably would.

This is exploratory / best-guess: the exact envelope shape for a
SERVER->CLIENT push (as opposed to the CLIENT->SERVER subscribe frame we
actually captured) is not confirmed - flows.jsonl has zero real bridge
traffic ever captured, so there's no known-good sample to copy. Expect to
iterate based on what the client actually does in response (see
gameserver/server.py's capture log and Frida socket hooks).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from aiohttp import web

log = logging.getLogger("emulator.bridge")

_sockets: set[web.WebSocketResponse] = set()


def register(ws: web.WebSocketResponse) -> None:
    _sockets.add(ws)


def unregister(ws: web.WebSocketResponse) -> None:
    _sockets.discard(ws)


def _decode_frame(data: bytes | str) -> dict | None:
    """Real captured frames are sent as BINARY websocket messages (type=2,
    not TEXT) with a short non-JSON header before the payload - e.g.
    b'\\x8a\\x00{"a":3,...}' / b'\\x80\\x00{"a":3,...}'. The two observed
    header bytes differ (0x8a vs 0x80) in a way that isn't understood yet
    (tried correlating with route-string length, inconclusive) - so instead
    of parsing the header, just find the first '{' and decode JSON from
    there. Also accepts plain TEXT/str in case that ever shows up too."""
    if isinstance(data, (bytes, bytearray)):
        idx = data.find(b"{")
        if idx < 0:
            return None
        raw = data[idx:]
    else:
        idx = data.find("{")
        if idx < 0:
            return None
        raw = data[idx:]
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return msg if isinstance(msg, dict) else None


def _encode_frame(obj: dict) -> bytes:
    """Mirror the client's own 2-byte-prefix-then-JSON binary framing (see
    _decode_frame) for anything we send back, on the guess the channel is
    symmetric. Prefix bytes are an unverified guess (0x80 0x00, one of the
    two real values observed from the client) - if wrong, worst case the
    client can't parse our frame at all, same as it ignoring us entirely
    today."""
    return b"\x80\x00" + json.dumps(obj).encode("utf-8")


_ACK_ENABLED = False  # see 2026-08-12 note below


async def handle_incoming(ws: web.WebSocketResponse, path: str, data) -> None:
    """Log-only by default (see _ACK_ENABLED). 2026-08-12: briefly sent a
    best-guess ack ({"a":2,...}) for every "a":3 subscribe - this
    correlated with NEW instability that had never shown up in ~5 prior
    clean test runs across 3 builds (menu-level "Xbox Live error" kicks,
    before even reaching Set Sail; previously failures were 100% isolated
    to Set Sail itself). Strong circumstantial evidence the guessed ack
    shape/action-code is actively harmful - possibly the bridge socket's
    health feeds into a broader "connected to services" client-side state,
    and a malformed/unexpected frame on it trips that. Disabled pending a
    less blind approach (e.g. Frida-tracing the client's own bridge
    frame-parsing code to get the real ack schema before trying again,
    rather than guessing). DO NOT re-enable without re-verifying against a
    clean baseline run first."""
    msg = _decode_frame(data)
    if msg is None:
        return
    action = msg.get("a")
    route = msg.get("r")
    mid = msg.get("mid")
    log.info("bridge[%s] incoming a=%r r=%r mid=%r", path, action, route, mid)
    if _ACK_ENABLED and action == 3:  # subscribe (observed)
        ack = {"a": 2, "r": route, "p": {}, "mid": mid, "sq": 0, "sp": 0, "sh": 0}
        try:
            await ws.send_bytes(_encode_frame(ack))
            log.info("bridge[%s] sent ack for subscribe to %r", path, route)
        except Exception as e:
            log.info("bridge[%s] ack send failed: %r", path, e)


async def push_player_server_assignment(server_address: str, connection_token: str | None = None,
                                          connection_key: str | None = None) -> None:
    """Broadcast a best-guess PlayerServerAssignmentMessage to every
    currently-connected bridge websocket. See module docstring for why."""
    if not _sockets:
        log.info("bridge: no live bridge socket to push PlayerServerAssignmentMessage to (none connected)")
        return
    payload = {
        "ConnectionToken": connection_token or str(uuid.uuid4()),
        "ConnectionKey": connection_key or str(uuid.uuid4()),
        "ServerAddress": server_address,
    }
    frame = {
        "a": "PlayerServerAssignmentMessage",
        "r": "PlayerServerAssignmentMessage",
        "p": payload,
        "mid": str(uuid.uuid4()),
        "sq": 0, "sp": 0, "sh": 0,
    }
    log.info("bridge: pushing PlayerServerAssignmentMessage -> %d live socket(s): %s", len(_sockets), json.dumps(frame))
    encoded = _encode_frame(frame)
    results = await asyncio.gather(
        *(ws.send_bytes(encoded) for ws in list(_sockets)), return_exceptions=True
    )
    for ws, r in zip(list(_sockets), results):
        if isinstance(r, Exception):
            log.info("bridge: push failed on one socket: %r", r)
