"""
hosts_redirect.py — points config.DISCOVERY_HOST *and* config.PROXIED_HOSTS
at 127.0.0.1 in the Windows hosts file, so the game's traffic reaches the
emulator instead of Rare's real backend (for DISCOVERY_HOST) or our MITM
proxy in front of real Microsoft infrastructure (for PROXIED_HOSTS — see
session_proxy.py). Mirrors ../winproxy.py's on/off/status style, and the
same warning applies: this edits real system config — turn it off when
you're done, or the game (and only the game — these are specific FQDNs,
not whole domains) will keep failing to reach the real servers.

Requires an elevated (Administrator) shell — the hosts file lives under
C:\\Windows\\System32\\drivers\\etc\\hosts, which a normal user can't write.

Usage (as Administrator):
    python hosts_redirect.py on       # add the redirects
    python hosts_redirect.py off      # remove them
    python hosts_redirect.py status   # show whether they're active
"""
from __future__ import annotations

import pathlib
import sys

import config

HOSTS_PATH = pathlib.Path(r"C:\Windows\System32\drivers\etc\hosts")
_MARKER = "# pysniffer-emulator"


def _hosts() -> list[str]:
    return [config.DISCOVERY_HOST] + list(config.PROXIED_HOSTS)


def _entries() -> list[str]:
    return [f"127.0.0.1 {h} {_MARKER}" for h in _hosts()]


def status() -> bool:
    if not HOSTS_PATH.exists():
        return False
    return any(_MARKER in line for line in HOSTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines())


def on() -> None:
    if status():
        print("already redirecting:", ", ".join(_hosts()))
        return
    try:
        with HOSTS_PATH.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(_entries()) + "\n")
    except PermissionError:
        print("permission denied — re-run this from an Administrator PowerShell/cmd.")
        sys.exit(1)
    print("added:")
    for e in _entries():
        print(" ", e)


def off() -> None:
    if not HOSTS_PATH.exists():
        return
    lines = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept = [line for line in lines if _MARKER not in line]
    if len(kept) == len(lines):
        print("nothing to remove")
        return
    try:
        HOSTS_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except PermissionError:
        print("permission denied — re-run this from an Administrator PowerShell/cmd.")
        sys.exit(1)
    print("removed redirects for:", ", ".join(_hosts()))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "on":
        on()
    elif cmd == "off":
        off()
    elif cmd == "status":
        print("active" if status() else "inactive")
    else:
        print("usage: python hosts_redirect.py [on|off|status]")
