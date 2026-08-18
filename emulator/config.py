"""
config.py — central configuration for the emulator.

Single collapsed backend host: the real game (Sea of Thieves / "Athena")
first calls a fixed, hardcoded "discovery" host to learn the URLs of every
other backend service (catalog, login, commerce, matchmaking, ...) — see
discovery.py. Since we control that response, we don't need to fake dozens
of hostnames: we rewrite every URL discovery hands back to point at ONE
hostname (REWRITE_HOST), differentiated only by path. That single hostname
is the only one that needs a hosts-file redirect and a TLS certificate.

If a future capture shows the client hardcoding some *other* host on top of
discovery (e.g. talking to a maelstrom/xboxlive host directly without going
through discovery first), that host would need its own hosts-file entry too
— see ../README_EMULATOR.md's "known gaps" section.
"""
from __future__ import annotations

import pathlib

DISCOVERY_HOST = "discovery.prod.athena.msrareservices.com"  # hardcoded in the client
REWRITE_HOST = DISCOVERY_HOST  # every rewritten service URL reuses this same host

LISTEN_ADDR = "0.0.0.0"
HTTPS_PORT = 443

# sessiondirectory.xboxlive.com is REAL, still-live Microsoft infrastructure
# (discovery.py deliberately leaves it unredirected — see that file). But its
# session documents' "servers" field always comes back empty for this old
# build: there's no Rare-hosted dedicated server left to register into it,
# which is the actual root cause of the "(Bronzebeard)" matchmaking failure
# (confirmed via extensive Frida/Ghidra investigation — see conversation
# history / README). PROXIED_HOSTS lists real hosts we MITM (genuine
# pass-through to the real service, patching only specific response fields)
# rather than fully replacing like REWRITE_HOST — see session_proxy.py.
PROXIED_HOSTS = ["sessiondirectory.xboxlive.com", "rta.xboxlive.com"]

# Where our own local gameserver/server.py listens - injected into session
# documents' "servers" field in place of the real (nonexistent) Rare server.
GAMESERVER_HOST = "127.0.0.1"
GAMESERVER_PORT = 7777

# The sniffer's project root (this file lives in <root>/emulator/).
SNIFFER_DIR = pathlib.Path(__file__).resolve().parent.parent
CERTS_DIR = SNIFFER_DIR / "certs"  # reuse the sniffer's already-trusted rootCA
DISCOVERY_SOURCE = SNIFFER_DIR / "discovery_full.json"
FLOWS_LOG = SNIFFER_DIR / "flows.jsonl"

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "data"
