"""
discovery.py — builds the fake response for the game's "discovery" service.

The real discovery.prod.athena.msrareservices.com/discovery/app/endpoint
returns a JSON map of serviceName -> {"url": "https://<cluster-host>/<path>"}
telling the client where every other backend service lives, picking one of
several interchangeable clusters (stamp1/stamp3/stamp6/...) on each call.
We serve the same map (loaded from ../discovery_full.json, itself a real
captured copy) with every URL's host replaced by config.REWRITE_HOST, so
every follow-up request the client makes lands on us instead.

Path namespaces don't collide once merged onto one host (checked against
the real discovery_full.json: /ares/*, /catalog/app/, /redeem/app/, etc. are
all distinct) — except "bridge"/"bridge2", which both use path "/ws" on
their own distinct real hosts; those get distinct local paths here so
app.py can route them to two separate websocket handlers.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import config

_PATH_OVERRIDE = {
    "bridge": "/ws/bridge",
    "bridge2": "/ws/bridge2",
}


def _load_source() -> dict:
    with open(config.DISCOVERY_SOURCE, "r", encoding="utf-8") as f:
        return json.load(f)


def build(source: dict | None = None) -> dict:
    source = source if source is not None else _load_source()
    out: dict[str, dict] = {}
    for name, entry in source.items():
        url = entry.get("url", "")
        if name == "test":
            # "http://testurl/test" is an inert placeholder in every real
            # capture (invalid TLD) — the client never actually resolves it.
            out[name] = {"url": url}
            continue
        parts = urlsplit(url)
        if parts.netloc.lower().endswith("xboxlive.com"):
            # Real Microsoft/Xbox Live infrastructure (matchmaking/session
            # directory etc, e.g. maelstrom1/maelstrom2), not Rare's own
            # retired backend. We have no way to fake real-time session
            # creation with static fixtures anyway - leave these pointing at
            # the genuine host so the client talks to the real, still-live
            # Xbox Live service instead of us. hosts_redirect.py only ever
            # redirects config.DISCOVERY_HOST, so xboxlive.com already
            # resolves normally - we just need to stop overwriting the URL.
            out[name] = {"url": url}
            continue
        path = _PATH_OVERRIDE.get(name, parts.path)
        out[name] = {"url": urlunsplit((parts.scheme, config.REWRITE_HOST, path, parts.query, parts.fragment))}
    return out


_cache: dict | None = None


def get() -> dict:
    global _cache
    if _cache is None:
        _cache = build()
    return _cache
