"""
app.py — the emulator's HTTP(S)/WebSocket server.

One aiohttp app answers every request the game sends to config.REWRITE_HOST,
in this order:
  1. handlers/  — explicit custom logic (login, anything you add)
  2. fixtures/  — static replay of a real captured response
  3. a generic fallback (200, empty JSON object) so the client gets
     *something* parseable instead of a hard connection/protocol error

The discovery endpoint and the two websocket "bridge" endpoints are wired
up directly since they're not plain request/response replay.
"""
from __future__ import annotations

import base64
import logging
import re

from aiohttp import web

import bridge_state
import config
import discovery
import fixtures
import handlers
import rta_proxy
import session_proxy

log = logging.getLogger("emulator")

# The client embeds its OWN version number in this path (e.g.
# /configurationproxy/app/config/versions/2.95.1936.0) - it will basically
# never match the exact version fixtures.py happened to capture in
# flows.jsonl. An empty-200 fallback here isn't harmless like it is for
# most other unmatched endpoints - this old client treats a missing config
# as a hard "services unavailable" error ("coralbeard") instead of just
# proceeding with defaults. See fixtures.find_any_under().
_CONFIG_VERSION_PATH = "/configurationproxy/app/config/versions/"
_CONFIG_VERSION_RE = re.compile(re.escape(_CONFIG_VERSION_PATH) + r"[^/?]+$")


async def discovery_endpoint(request: web.Request) -> web.Response:
    return web.json_response(discovery.get(), headers={"X-Rare-StampId": "local"})


async def bridge_ws(request: web.Request) -> web.WebSocketResponse:
    # 2026-08-15: was missing the requested subprotocol echo (client sends
    # Sec-WebSocket-Protocol: Protocol1, server never answered with it) -
    # this exact bug + fix was already documented in project memory
    # (sot-lighthouse-vs-mpsd-diagnosis.md, 2026-08-12 "four more real bugs
    # found in noxboxemulator/") but only ever got applied to that separate
    # copy, never ported back into THIS file - confirmed still live via
    # "Client protocols ['Protocol1'] don't overlap server-known ones ()"
    # warnings + a bridge reconnect every ~12-17s in run_session.log,
    # coinciding with the user's reported "coarsebeard" (failed to setup
    # crew session) loop. Mirrors rta_proxy.py's already-correct pattern.
    requested_protocols = [
        p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()
    ]
    ws = web.WebSocketResponse(protocols=requested_protocols or None, heartbeat=20)
    await ws.prepare(request)
    log.info("bridge connected: %s", request.path)
    bridge_state.register(ws)
    try:
        async for msg in ws:
            log.info("bridge frame on %s: type=%s data=%r", request.path, msg.type, msg.data)
            # Real frames come in as BINARY (type=2), not TEXT, with a
            # short 2-byte non-JSON header before the payload - see
            # bridge_state._decode_frame(). Handle both in case that ever
            # changes/varies.
            if msg.type in (web.WSMsgType.TEXT, web.WSMsgType.BINARY):
                await bridge_state.handle_incoming(ws, request.path, msg.data)
    finally:
        bridge_state.unregister(ws)
    log.info("bridge loop ended (close_code=%s exception=%r)", ws.close_code, ws.exception())
    log.info("bridge disconnected: %s", request.path)
    return ws


def _split_content_type(headers: list) -> tuple[str, str | None, list]:
    content_type = "application/json"
    charset = None
    rest = []
    for k, v in headers:
        if k.lower() == "content-type":
            content_type = v.split(";")[0].strip()
            if "charset=" in v:
                charset = v.split("charset=", 1)[1].strip()
        else:
            rest.append((k, v))
    return content_type, charset, rest


def _fixture_response(fixture: dict) -> web.Response:
    content_type, charset, headers = _split_content_type(fixture["headers"])
    encoding = fixture.get("body_encoding", "utf8")
    if encoding == "base64":
        # Genuinely binary body (e.g. "X-Encoding: sot") — send the exact
        # bytes back, not text, so it isn't re-mangled on the way out.
        body = base64.b64decode(fixture["body"]) if fixture["body"] else b""
        return web.Response(status=fixture["status"], headers=headers, body=body, content_type=content_type)
    if encoding == "empty":
        return web.Response(status=fixture["status"], headers=headers, content_type=content_type)
    return web.Response(
        status=fixture["status"],
        headers=headers,
        text=fixture["body"],
        content_type=content_type,
        charset=charset,
    )


async def catch_all(request: web.Request) -> web.StreamResponse:
    method, path = request.method, request.path

    host = request.host.split(":")[0]
    # Read the body once, up front, so the fallback branch at the bottom can
    # log a preview of it (see comment there) - safe to read even when a
    # handler/fixture below ends up handling the request instead, since
    # nothing downstream in THIS function reads request.read() again.
    body = await request.read()
    if host == "rta.xboxlive.com" and request.headers.get("Upgrade", "").lower() == "websocket":
        return await rta_proxy.handle(request)
    if host in config.PROXIED_HOSTS:
        return await session_proxy.handle(request)

    handler = handlers.find(method, path)
    if handler:
        return await handler(request)

    fixture = fixtures.find(method, path)
    if not fixture and method == "GET" and _CONFIG_VERSION_RE.search(path):
        fixture = fixtures.find_any_under(method, _CONFIG_VERSION_PATH)
        if fixture:
            log.info("configurationproxy: serving fixture for a different version (%s) for requested %s", fixture["path"], path)
    if fixture:
        return _fixture_response(fixture)

    # 2026-08-15: body preview added specifically to catch a genuinely new
    # lead — a real, separate REST API (discovery://contestmatchmaking/api/
    # {client,client/locations,server}, backed by real C++ model classes:
    # ContestMatchmakingClientRequestModel/ResponseModel, ...ServerRequestModel,
    # ...LocationsResponseModel, ...CrewModel — see tools/contestmatchmaking_models_ctx.txt
    # and tools/servermatchmaking_ctx.txt) that resolves through OUR OWN
    # REWRITE_HOST (config.py's discovery-rewrite mechanism), meaning it's
    # already fully in our control, yet has NEVER been observed hitting this
    # fallback even once across this whole project's run_session.log history.
    # This body preview (was previously method+path only, no body) is the
    # cheapest possible way to find out, next time this endpoint (or any
    # other silently-swallowed one, e.g. real telemetry event POSTs whose
    # class names — JoinSessionSuccessEvent/FailedEvent,
    # ClientStartServerMatchmakingTelemetryEvent — were found the same way)
    # is ever actually hit, and with what body — no new Frida hook, no new
    # crash risk, since our own server already sees 100% of traffic that
    # reaches it.
    body_preview = ""
    if body:
        try:
            body_preview = " body=" + body[:600].decode("utf-8", errors="replace")
        except Exception:
            body_preview = " body=" + repr(body[:600])
    log.warning("no fixture/handler for %s %s (%d bytes)%s — returning empty 200", method, path, len(body), body_preview)
    return web.json_response({})


def build_app() -> web.Application:
    fixtures.load()
    app = web.Application()
    app.router.add_get("/discovery/app/endpoint", discovery_endpoint)
    app.router.add_get("/ws/bridge", bridge_ws)
    app.router.add_get("/ws/bridge2", bridge_ws)
    app.router.add_route("*", "/{tail:.*}", catch_all)
    return app
