"""
session_proxy.py — FULLY LOCAL MPSD (sessiondirectory.xboxlive.com) mock.
No real Microsoft backend involved at all - sessions are created, updated,
and listed entirely in-memory, instantly, every time. Eliminates the
real-backend-timing "coarsebeard" stall AND the real-account session churn/
throttling risk that the real-MITM version of this file was subject to (see
project memory sot-lighthouse-vs-mpsd-diagnosis.md for that history,
including the "seed session" hammering saga this fully-local approach makes
moot - no session ever needs to be seeded on a real backend when there is
no real backend).

2026-08-12: promoted from noxboxemulator/session_proxy.py (an isolated
same-day revival of this approach) back into emulator/, now that the user
wants to try dropping Xbox Live entirely for matchmaking/session state.
This exact logic already went through several real bug fixes in that
isolated copy (changeNumber must be per-document not a shared global
counter; new-vs-update PUT status (201 vs 204) must be decided from local
dict membership, not another shared global; per-server "servers[addr].
properties.system.matchmaking" - the untested fix noted in the previous
version of THIS file's own docstring - is now included) before being
brought back here.

2026-08-12 KNOWN RISK, carried over from the ORIGINAL same-day experiment
on this exact file (before it was reverted to real-MITM, then promoted
back now): a fully-local MPSD mock reproduced a real, clean NULL-pointer-
dereference crash (SoTGame.exe RVA 0x3cbd9aa, identical on two unrelated
depot builds) roughly 20-60s after boot, in UI/engine code unrelated to
matchmaking - root cause traced to a lookup that always succeeds against
genuine Microsoft responses returning nothing against a locally-fabricated
one, but the exact missing field was never pinned down (two hypotheses
disproven: gamertag spaces, response latency). The isolated noxboxemulator
copy revived this same approach specifically to test whether the crash
reappears with these bug fixes and the wider (login/presence/etc also
local) surface - if it does, the missing-field theory is probably still
right and needs to keep being chased; if it doesn't, something about the
bug fixes or the wider local surface incidentally avoided it.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import uuid

from aiohttp import web

import bridge_state

log = logging.getLogger("emulator.session_proxy")

# Was noxboxemulator's xboxlive_local.LOCAL_GAMERTAG - inlined here rather
# than importing a whole sibling-folder module for one constant.
LOCAL_GAMERTAG = "LocalPirate"

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "host",
}


def _is_session_document(path: str) -> bool:
    return "/sessiontemplates/" in path.lower() and "/sessions/" in path.lower()


def _is_session_list(path: str) -> bool:
    p = path.lower()
    return p.rstrip("/").endswith("/sessions") and "/sessiontemplates/" not in p


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


_SCID = "00000000-0000-0000-0000-000066591171"
LOCAL_GAMESERVER = "127.0.0.1:7777"

_LOCAL_SESSIONS: dict[str, dict] = {}


def _extract_member_xuid(put_body: dict) -> str:
    try:
        return put_body["members"]["me"]["constants"]["system"]["xuid"]
    except Exception:
        return "0"


def _build_new_session_doc(put_body: dict) -> dict:
    # changeNumber/status-code fixes: see module docstring - both must be
    # per-document/per-request, not shared global state across the whole
    # process lifetime (a real fresh MPSD session always starts at
    # changeNumber=1; a genuinely new session must get 201, not 204).
    custom_props = {}
    try:
        custom_props = dict(put_body.get("properties", {}).get("custom", {}))
    except Exception:
        pass
    xuid = _extract_member_xuid(put_body)
    now = _now_iso()
    # Only inject matchmaking/servers for the actual SmallShip matchmaking
    # session, not unconditionally on every new session doc - the real
    # client PUTs a SECOND, paired session under the same template for
    # crew-tracking purposes whose custom properties look like
    # {"SessionTarget":"CrewSession", ...} with NO "SessionType" field at
    # all. Populating matchmaking/servers on that companion session too
    # fabricates "server assigned" state the real client never expects
    # there.
    is_smallship_matchmaking_session = custom_props.get("SessionType") == "SmallShip"
    system_properties = {
        "joinRestriction": "followed", "readRestriction": "followed", "turn": [],
    }
    top_level_servers = {}
    if is_smallship_matchmaking_session:
        system_properties["matchmaking"] = {
            "targetSessionConstants": {},
            "serverConnectionString": LOCAL_GAMESERVER,
            "status": "found",
        }
        system_properties["serverConnectionStringCandidates"] = [LOCAL_GAMESERVER]
        # Per-server matchmaking status (Ghidra finding, FUN_7ff780e6a240
        # in project memory) - separate from the top-level
        # properties.system.matchmaking above.
        top_level_servers = {
            LOCAL_GAMESERVER: {
                "constants": {"system": {"initialize": True}, "custom": {}},
                "properties": {
                    "system": {
                        "matchmaking": {
                            "status": "found",
                            "statusDetails": "",
                            "typicalWait": 0,
                        },
                    },
                    "custom": {},
                },
            },
        }
    doc = {
        "membersInfo": {"first": 0, "next": 1, "count": 1, "accepted": 1, "active": 1},
        "constants": {
            "system": {
                "readyRemovalTimeout": 180000,
                "reservedRemovalTimeout": 30000,
                "sessionEmptyTimeout": 0,
                "inactiveRemovalTimeout": 600000,
                "version": 1,
                "maxMembersCount": 2,
                "visibility": "open",
                "capabilities": {
                    "connectivity": True, "gameplay": True,
                    "userAuthorizationStyle": True, "crossPlay": True,
                },
                "memberInitialization": {"membersNeededToStart": 1},
                "inviteProtocol": "game",
                "initiators": [xuid],
            },
            "custom": {},
        },
        "properties": {
            "system": system_properties,
            "custom": custom_props,
        },
        "servers": top_level_servers,
        "members": {
            "0": {
                "next": 1,
                "joinTime": now,
                "constants": {"system": {"initialize": True, "xuid": xuid, "index": 0}, "custom": {}},
                "properties": {"system": {"active": True}, "custom": {}},
                "gamertag": LOCAL_GAMERTAG,
                "activeTitleId": "1717113201",
            },
        },
        "correlationId": str(uuid.uuid4()),
        "contractVersion": 107,
        "branch": str(uuid.uuid4()),
        "changeNumber": 1,  # always 1 for a genuinely new document - see comment above
        "startTime": now,
    }
    return doc


def _apply_update(doc: dict, put_body: dict) -> None:
    try:
        custom_updates = put_body.get("properties", {}).get("custom", {})
        if custom_updates:
            doc["properties"]["custom"].update(custom_updates)
    except Exception:
        pass
    try:
        members_update = put_body.get("members", {})
        if "me" in members_update:
            me_update = members_update["me"]
            if me_update is None:
                doc["members"].pop("0", None)
            else:
                xuid = (
                    (me_update.get("constants", {}) or {}).get("system", {}).get("xuid")
                    or _extract_member_xuid(put_body)
                )
                existing = doc["members"].get("0", {})
                doc["members"]["0"] = {
                    "next": 1,
                    "joinTime": existing.get("joinTime", _now_iso()),
                    "constants": {"system": {"initialize": True, "xuid": xuid, "index": 0}, "custom": {}},
                    "properties": {"system": {"active": True}, "custom": {}},
                    "gamertag": existing.get("gamertag", LOCAL_GAMERTAG),
                    "activeTitleId": "1717113201",
                }
    except Exception:
        pass
    member_count = len(doc.get("members", {}))
    doc["membersInfo"] = {
        "first": 0, "next": member_count, "count": member_count,
        "accepted": member_count, "active": member_count,
    }
    # Per-document increment (not a shared global counter) - each session's
    # changeNumber advances independently starting from its own 1.
    doc["changeNumber"] = doc.get("changeNumber", 1) + 1


def _session_ref(scid: str, template: str, name: str) -> dict:
    return {"scid": scid, "templateName": template, "name": name}


def _json_response(doc: dict, status: int = 200) -> web.Response:
    body = json.dumps(doc).encode("utf-8")
    headers = {"Content-Type": "application/json", "ETag": f'"{uuid.uuid4().hex}"'}
    return web.Response(status=status, headers=headers, body=body)


_SESSION_PATH_RE = re.compile(
    r"^/serviceconfigs/(?P<scid>[^/]+)/sessionTemplates/(?P<template>[^/]+)/sessions/(?P<name>[^/?]+)$",
    re.IGNORECASE,
)


async def handle(request: web.Request) -> web.StreamResponse:
    path = request.path
    method = request.method
    body = await request.read()

    log.info("[local-mpsd] %s %s (%d bytes)", method, path, len(body))
    if body:
        try:
            preview = body[:600].decode("utf-8", errors="replace")
        except Exception:
            preview = repr(body[:600])
        log.info("[local-mpsd]   body preview: %s", preview)

    # 2026-08-15: real Xbox Live MPSD "session handle" endpoint - POST here
    # fires exactly twice right after both session PUTs succeed (once per
    # session), previously fell through to the generic unhandled-204
    # fallback below with NO body logged (only PUT got a body preview
    # before today). First real observation of this endpoint firing at
    # all in this project's history. Real XSAPI schema (multiplayer_
    # session.cpp): POST body is {"version":1,"type":"activity","sessionRef":
    # {"scid":...,"templateName":...,"name":...}}, response is the same
    # shape plus a generated "id" (the handle GUID) and "ownerXuid", 201.
    if method == "POST" and path.rstrip("/").lower() == "/handles":
        try:
            req = json.loads(body) if body else {}
        except Exception:
            req = {}
        handle_doc = {
            "id": str(uuid.uuid4()),
            "version": req.get("version", 1),
            "type": req.get("type", "activity"),
            "ownerXuid": _extract_member_xuid(req) or "0",
            "sessionRef": req.get("sessionRef", {}),
        }
        log.info("[local-mpsd] created handle %s for sessionRef=%r", handle_doc["id"], handle_doc["sessionRef"])
        return _json_response(handle_doc, status=201)

    if method == "GET" and _is_session_list(path):
        xuid = request.query.get("xuid", "")
        # 2026-08-15: tried auto-seeding a bare "already joined" session
        # here to fix the empty-list boot-restart loop (see project memory
        # sot-lighthouse-vs-mpsd-diagnosis.md's "coarsebeard" writeup for
        # the real-MITM version's original fix, _ensure_seed_session()) -
        # REVERTED. Live-tested: the client immediately PUT {"members":
        # {"me":null}} to leave the fabricated session (same second, not
        # the real backend's genuine ~30-90s-later leave), then the SAME
        # ~15-17s full boot-restart loop continued regardless - the seed
        # didn't fix anything, just added a spurious extra round-trip. The
        # real cause of the boot-restart loop is still unidentified -
        # don't re-add this seed without new evidence it actually helps.
        results = []
        for name, doc in _LOCAL_SESSIONS.items():
            member_xuids = {
                m.get("constants", {}).get("system", {}).get("xuid")
                for m in doc.get("members", {}).values()
            }
            if xuid and xuid not in member_xuids:
                continue
            results.append({
                "xuid": xuid,
                "sessionRef": _session_ref(_SCID, "smallshipsessiontemplate", name),
                "status": "active",
                "visibility": doc.get("constants", {}).get("system", {}).get("visibility", "open"),
                "joinRestriction": "followed",
                "readRestriction": "followed",
                "startTime": doc.get("startTime"),
                "accepted": doc.get("membersInfo", {}).get("accepted", 1),
                "keywords": [],
                "clubId": "0",
                "firstMemberXuid": xuid,
            })
        log.info("[local-mpsd] session list for xuid=%s -> %d result(s)", xuid, len(results))
        return _json_response({"results": results})

    m = _SESSION_PATH_RE.match(path)
    if m:
        name = m.group("name")

        if method == "PUT":
            try:
                put_body = json.loads(body) if body else {}
            except Exception:
                put_body = {}
            is_new_session = name not in _LOCAL_SESSIONS
            if is_new_session:
                doc = _build_new_session_doc(put_body)
                _LOCAL_SESSIONS[name] = doc
                log.info("[local-mpsd] created session %s", name)
            else:
                doc = _LOCAL_SESSIONS[name]
                _apply_update(doc, put_body)
                log.info("[local-mpsd] updated session %s (changeNumber=%s)", name, doc["changeNumber"])
            resp = _json_response(doc, status=201 if is_new_session else 204)
            if doc.get("members"):
                await bridge_state.push_player_server_assignment(LOCAL_GAMESERVER)
            if not doc.get("members"):
                _LOCAL_SESSIONS.pop(name, None)
                log.info("[local-mpsd] session %s now empty - removed", name)
            return resp

        if method == "GET":
            doc = _LOCAL_SESSIONS.get(name)
            if doc is None:
                log.info("[local-mpsd] GET %s -> 404 (unknown)", name)
                return web.Response(status=404)
            return _json_response(doc)

        if method == "DELETE":
            _LOCAL_SESSIONS.pop(name, None)
            log.info("[local-mpsd] DELETE session %s", name)
            return web.Response(status=204)

    if method == "DELETE" and path.lower().endswith("/members/me"):
        session_part = path.rsplit("/members/me", 1)[0]
        m2 = _SESSION_PATH_RE.match(session_part)
        if m2:
            name = m2.group("name")
            doc = _LOCAL_SESSIONS.get(name)
            if doc is not None:
                doc.get("members", {}).pop("0", None)
                if not doc["members"]:
                    _LOCAL_SESSIONS.pop(name, None)
                    log.info("[local-mpsd] session %s emptied via leave - removed", name)
        return web.Response(status=204)

    log.info("[local-mpsd] unhandled %s %s -> 204", method, path)
    return web.Response(status=204)
