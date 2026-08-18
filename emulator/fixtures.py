"""
fixtures.py — in-memory store of pre-extracted real request/response pairs,
used to answer emulator requests with data the real game backend actually
sent at capture time. Populated by extract_fixtures.py from ../flows.jsonl;
see that script's docstring for the file format under fixtures/data/.

Each fixture's body is tagged "body_encoding": "utf8" | "base64" | "empty"
(app.py._fixture_response reads this to send bytes back exactly as
captured, not just as text) — see extract_fixtures.py and
../http_message.py's raw_body_for_storage() for why that distinction
exists.
"""
from __future__ import annotations

import json
import re

import config

_store: dict[tuple[str, str], dict] = {}


def _normalize(path: str) -> str:
    return path.rstrip("/") or "/"


# XUIDs are long numeric path segments (.../user/<xuid>/...) - the client
# uses whichever REAL Microsoft account is signed in at the OS level for
# these (confirmed in handlers/login.py's docstring: our fake login
# response's own PLAYFAB_ID has no effect on it), so it will essentially
# never match whatever account flows.jsonl happened to be captured from.
# Strip XUIDs (and pirate-id GUIDs, same reasoning) from both sides before
# comparing, so a fixture captured under one account still answers the
# same *shape* of request for a different one. Only the PATH is touched -
# encrypted (X-Encoding: sot / body_encoding: base64) response bodies are
# replayed byte-for-byte verbatim regardless, since rewriting an id inside
# ciphertext is meaningless (can't produce different valid plaintext) and
# at best a no-op, at worst breaks the GCM auth tag.
_XUID_RE = re.compile(r"/user/\d{10,20}")
_GUID_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _strip_ids(path: str) -> str:
    path = _XUID_RE.sub("/user/XUID", path)
    path = _GUID_RE.sub("/GUID", path)
    return path


def load() -> dict[tuple[str, str], dict]:
    global _store
    store: dict[tuple[str, str], dict] = {}
    if config.FIXTURES_DIR.exists():
        for f in config.FIXTURES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            key = (data["method"].upper(), _normalize(data["path"]))
            store[key] = data
    _store = store
    return store


def find(method: str, path: str) -> dict | None:
    method = method.upper()
    path = _normalize(path)

    exact = _store.get((method, path))
    if exact:
        return exact

    # id-agnostic exact match — same endpoint shape, different account/xuid
    # or pirate GUID than whatever flows.jsonl was captured from.
    stripped_request = _strip_ids(path)
    for (m, p), fixture in _store.items():
        if m == method and _strip_ids(p) == stripped_request:
            return fixture

    # fallback: longest stored path that's a prefix of the request path —
    # covers endpoints with a dynamic trailing id/segment (.../SOURCE_ID etc.)
    best: tuple[str, dict] | None = None
    for (m, p), fixture in _store.items():
        if m == method and path.startswith(p) and (best is None or len(p) > len(best[0])):
            best = (p, fixture)
    if best:
        return best[1]

    # id-agnostic prefix match — same idea as above, for paths with both a
    # mid-path id AND a dynamic trailing segment.
    for (m, p), fixture in _store.items():
        if m == method and stripped_request.startswith(_strip_ids(p)):
            if best is None or len(p) > len(best[0]):
                best = (p, fixture)
    return best[1] if best else None


def find_any_under(method: str, path_prefix: str) -> dict | None:
    """First stored fixture whose path starts with `path_prefix` — for
    endpoints whose real path segment we can't match exactly (e.g. the
    client's OWN version number embedded in the configurationproxy URL,
    which will never equal whatever version happened to be running when
    flows.jsonl was captured). Unlike find()'s prefix fallback (which
    requires the STORED path to be a prefix of the REQUEST), this is the
    other direction: we already know the request doesn't have a fixture,
    so serve whatever's available under the same endpoint family rather
    than falling through to an empty 200 (which some old clients treat as
    a hard "services unavailable" error instead of just missing data)."""
    method = method.upper()
    for (m, p), fixture in _store.items():
        if m == method and p.startswith(path_prefix):
            return fixture
    return None
