"""
run.py — entry point. Starts the emulator's HTTPS listener.

Before running this:
  1. python extract_fixtures.py     (turns captured traffic into replayable fixtures)
  2. python hosts_redirect.py on    (as Administrator — see that file's docstring)
  3. make sure ../certs/rootCA.cer is already trusted (it is, if you've used
     the sniffer before — see ../README.md)

Then:
  python run.py
"""
from __future__ import annotations

import logging

from aiohttp import web

import app as app_module
import config
import tls_cert


def main() -> None:
    # Also mirror everything to a file (mirrors tools/run_frida_probe.bat's
    # dual console+file output) - session_proxy.py's "injected servers
    # entry" / "no member connection GUID found yet" / "servers empty"
    # messages are the ground truth for whether the servers-field injection
    # experiment actually fires on a given run, and scrolling back through
    # a live console window to find them is error-prone.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("run_session.log", mode="w", encoding="utf-8"),
        ],
    )
    application = app_module.build_app()
    hosts = [config.REWRITE_HOST] + list(config.PROXIED_HOSTS)
    ssl_context = tls_cert.build_multi_sni_context(hosts)
    print(f"emulator listening on :{config.HTTPS_PORT} for: {', '.join(hosts)}")
    print(f"  {config.REWRITE_HOST} -> fixture replay (Rare's retired backend)")
    for h in config.PROXIED_HOSTS:
        print(f"  {h} -> MITM pass-through to the real service (session_proxy.py)")
    print("(make sure hosts_redirect.py is 'on' and the game is actually pointed here)")
    web.run_app(application, host=config.LISTEN_ADDR, port=config.HTTPS_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
