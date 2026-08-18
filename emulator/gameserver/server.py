"""
gameserver/server.py — the actual "Sea of Thieves dedicated game server"
emulator. This is step 1: a bare listener (TCP + UDP) that accepts
connections/packets and logs every raw byte it receives, plus every UDP
datagram, to both the console and a timestamped log file.

Why this exists: the real bootflow failure (confirmed via extensive Frida/
Ghidra investigation - see conversation history / README) is that
matchmaking creates a real Xbox Live session (Ship + Crew, via genuine
sessiondirectory.xboxlive.com calls) but the session's "servers" field
comes back empty - there's no Rare-hosted dedicated server left to
register into it, so the client can't ever connect to a game and gives up
citing "BootflowGenericMatcmakingFailureMessage" (shown to the player as
"(Bronzebeard)").

The plan: get something OUR OWN into that "servers" field (still to be
solved separately - see gameserver/README.md once written), pointing at
this listener's IP:port, so the client tries to talk to *us* instead of a
nonexistent Rare server. Once that happens, whatever bytes the client
sends here are the real, live Unreal Engine connection handshake for this
build - we reverse-engineer the protocol INCREMENTALLY from real captured
traffic, not from a spec (there isn't a public one for this exact engine
version/build).

Usage:
    python server.py [--tcp-port 7777] [--udp-port 7777]

Everything received is logged to gameserver_capture.log (raw hex + ascii)
in this directory, so a session can be inspected/replayed later even if
the console scrollback is lost.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os

LOG_PATH = os.path.join(os.path.dirname(__file__), "gameserver_capture.log")


def _log(line: str) -> None:
    ts = datetime.datetime.now().isoformat(timespec="milliseconds")
    full = f"[{ts}] {line}"
    print(full)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(full + "\n")


def hex_dump(data: bytes, width: int = 16) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"    {i:06x}  {hex_part:<{width * 3}}  {ascii_part}")
    return "\n".join(lines)


class TcpCaptureProtocol(asyncio.Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport
        peer = transport.get_extra_info("peername")
        self.peer = peer
        _log(f"[tcp] connection from {peer}")

    def data_received(self, data: bytes) -> None:
        _log(f"[tcp] {self.peer} -> {len(data)} bytes:")
        _log(hex_dump(data))

    def connection_lost(self, exc: Exception | None) -> None:
        _log(f"[tcp] connection from {self.peer} closed" + (f" ({exc})" if exc else ""))


class UdpCaptureProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        _log(f"[udp] {addr} -> {len(data)} bytes:")
        _log(hex_dump(data))
        # NOTE: not replying yet - step 1 is just observing what the real
        # client sends first, unprompted. Once we see real traffic we'll
        # start crafting responses based on what the handshake looks like.

    def error_received(self, exc: Exception) -> None:
        _log(f"[udp] error: {exc}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tcp-port", type=int, default=7777)
    parser.add_argument("--udp-port", type=int, default=7777)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()

    loop = asyncio.get_running_loop()

    _log(f"=== gameserver starting: TCP {args.bind}:{args.tcp_port}, UDP {args.bind}:{args.udp_port} ===")
    _log(f"logging to {LOG_PATH}")

    tcp_server = await loop.create_server(TcpCaptureProtocol, args.bind, args.tcp_port)
    udp_transport, _ = await loop.create_datagram_endpoint(
        UdpCaptureProtocol, local_addr=(args.bind, args.udp_port)
    )

    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        udp_transport.close()


if __name__ == "__main__":
    asyncio.run(main())
