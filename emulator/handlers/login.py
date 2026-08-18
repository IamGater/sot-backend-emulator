"""
handlers/login.py — the game's initial POST to /ares/login/.

History of attempts (all failed identically until now): bare `{}` body, a
guessed full PlayFab LoginResult body, an exact 404 mirroring the real (now
retired) server, and a header-only theory (X-PlayFab-TitleId/EntityId/
EntityToken/EntityToken-Expiry) derived from binary string analysis - with
several variations on EntityToken length and expiry encoding. None of these
changed the client's behavior (always ends in the "Strawberrybeard" beard
error, confirmed via Frida live crash/behavior analysis to be unrelated to
header value length).

The breakthrough: `fixtures/data/POST_ares_login_api_token_client.json` is a
*genuinely captured* 200 response from the real backend, for the *current*
build's equivalent endpoint (`/ares/login/api/token/client`, not the old
build's bare `/ares/login/`). It reveals two things our every previous guess
got wrong:

1. The body is NOT `{}` - it's an OAuth2-style token response:
   `{"access_token": "<JWT>", "token_type": "bearer", "expires_in": N}`.
   Given the log string `FLogonAuthenticationHandler::!TokenResult.IsValid`,
   "TokenResult" is almost certainly exactly this {access_token, token_type,
   expires_in} struct - which we had literally never populated before.
2. `X-PlayFab-TitleId` is a short PlayFab-style id ("E5ED"), NOT the numeric
   `tid` query param (1717113201) we'd been reusing - those are two
   different identifiers (Microsoft/Xbox title id vs PlayFab title id).
   Likewise `X-PlayFab-EntityId` is a short hex id ("D7A9B14BD7EE295D"),
   distinct from PLAYFAB_ID (the numeric XUID baked into every other
   fixture's URL path - confirmed via grep that ENTITY_ID never appears in
   any other fixture path, so it's safe to use the real hex value here
   without breaking fixture lookups elsewhere).
   `X-PlayFab-EntityToken-Expiry` is ISO8601 with 7 fractional digits, not
   Unix epoch seconds.

The access_token JWT's payload is copied structurally from the real capture
(same field set: tid/gtg/xid/dty/sbx/p-xuid/p-device/r-pfid/r-pfeid/r-pftk/
r-stampid/etc, confirmed internally self-consistent with our TITLE_ID/
PLAYFAB_ID/ENTITY_ID), just re-signed with fresh exp/iat/nbf timestamps
since the captured one expires the same day it was captured. The signature
segment is garbage - HS256 needs a shared secret we don't have, and it's
very unlikely the *client* re-verifies a signature on a token it just
received over TLS from the server it trusts (only the issuer needs the
secret); if that assumption is wrong, this will need real disassembly to
confirm the client rejects unverified signatures specifically.
"""
from __future__ import annotations

import base64
import json
import time

from aiohttp import web

from . import route

TITLE_ID = "E5ED"  # real PlayFab-style TitleId (was wrongly "1717113201" - that's the *Microsoft* tid query param, a different id)
PLAYFAB_ID = "2535422034996422"  # numeric XUID - this old build reads it from the local Xbox Identity Provider
# (already signed in at the OS level), NOT from anything in our login response -
# confirmed via run.py's access log requesting /ares/pirate/api/user/2535422034996422/...
# after our first successful login, which didn't match the id baked into the
# fixtures (2535468076948547, from the *original* capture's different account).
# All fixtures/data/*.json paths have been bulk-renamed/patched to this id.
ENTITY_ID = "D7A9B14BD7EE295D"  # real PlayFab-style EntityId (hex) - never appears in any other fixture path, safe to use as-is
OLD_BUILD_VERSION = "2.95.1936.0"  # matches this old build's X-Rare-Version
STAMP_ID = "stamp3"

EXPIRES_IN_SECONDS = 4 * 60 * 60  # 4 hours, matches the real capture's expires_in


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _iso8601(ts: float) -> str:
    # matches the real capture's format: 2026-08-08T14:28:57.0000000Z (7 fractional digits)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".0000000Z"


def _build_entity_token() -> str:
    # the outer X-PlayFab-EntityToken header value itself - real one is a long
    # opaque base64-ish blob; structure doesn't matter since nothing else
    # decodes it, just needs to be long/plausible (definitively NOT limited
    # to 63 chars - the real one is ~300+ chars, confirmed by capture).
    now = int(time.time())
    payload = {
        "et": "title_player_account",
        "ei": ENTITY_ID,
        "ec": f"title_player_account!{TITLE_ID}/{PLAYFAB_ID}/{ENTITY_ID}/",
        "i": _iso8601(now),
        "fi": _iso8601(now),
        "e": _iso8601(now + EXPIRES_IN_SECONDS),
        "h": "internal",
        "idp": "XBoxLive",
        "idt": "Unknown",
        "idi": PLAYFAB_ID,
        "tid": TITLE_ID,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return f"{_b64url(b'placeholder-key-id')}|{_b64url(raw)}"


def _build_access_token(entity_token: str) -> str:
    now = int(time.time())
    exp = now + EXPIRES_IN_SECONDS
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "tid": "1717113201",  # the Microsoft/Xbox tid query param value
        "gtg": "SoT Network",
        "xid": PLAYFAB_ID,
        "dlt": "",
        "ctr": "102",
        "dty": "WindowsOneCore",
        "did": "F900F5E84A1E5D91",
        "sbx": "RETAIL",
        "tvr": OLD_BUILD_VERSION,
        "p-xuid": PLAYFAB_ID,
        "p-device": "Xbox",
        "r-rle": "client",
        "exp": exp,
        "sid": "L:AEfTLy8ydkKdfHF66ZTx6A",
        "src": "EpCb0BPh6Eig76D9HCLVWw",
        "r-licenf": "1",
        "r-licvalid": "1",
        "r-clm-pltfm": "WindowsOneCore",
        "r-pfid": TITLE_ID,
        "r-pftkx": _iso8601(exp),
        "r-pftid": TITLE_ID,
        "r-pfeid": ENTITY_ID,
        "r-pftk": entity_token,
        "r-pftre": "",
        "r-stampid": STAMP_ID,
        "nbf": now,
        "iat": now,
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    # signature is unverifiable garbage - HS256 needs a shared secret we
    # don't have, and the client can't practically re-verify a token it just
    # received from a server it trusts over TLS without embedding that same
    # secret itself.
    sig = _b64url(b"unverified-signature-placeholder")
    return f"{h}.{p}.{sig}"


@route("POST", "/ares/login/")
async def login(request: web.Request) -> web.Response:
    entity_token = _build_entity_token()
    access_token = _build_access_token(entity_token)
    expiry_iso = _iso8601(time.time() + EXPIRES_IN_SECONDS)

    return web.json_response(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": EXPIRES_IN_SECONDS,
        },
        headers={
            "X-PlayFab-TitleId": TITLE_ID,
            "X-PlayFab-EntityId": ENTITY_ID,
            "X-PlayFab-EntityToken": entity_token,
            "X-PlayFab-EntityToken-Expiry": expiry_iso,
            "X-Rare-StampId": STAMP_ID,
        },
    )
