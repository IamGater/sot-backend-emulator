"""
tls_cert.py — TLS for the emulator, borrowed from the sniffer.

We deliberately reuse the sniffer's root CA (../certs/rootCA.*) instead of
minting a separate one: it's already generated and, per ../README.md,
already installed as a trusted root on this machine — so there's no second
certificate to install just to run the emulator. If that CA is missing
(sniffer never run / certs deleted), ca.CertificateAuthority creates a
fresh one at the same path the first time this runs, and you'd need to
install *that* one exactly as ../README.md describes.
"""
from __future__ import annotations

import ssl
import sys

import config

sys.path.insert(0, str(config.SNIFFER_DIR))
from ca import CertificateAuthority  # noqa: E402 — sniffer's module, path patched above

_ca: CertificateAuthority | None = None


def _get_ca() -> CertificateAuthority:
    global _ca
    if _ca is None:
        _ca = CertificateAuthority(config.CERTS_DIR)
    return _ca


def build_ssl_context(hostname: str = config.REWRITE_HOST) -> ssl.SSLContext:
    cert_path, key_path = _get_ca().get_leaf_cert(hostname)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    ctx.set_alpn_protocols(["http/1.1"])  # matches the sniffer: no HTTP/2 parsing on either side
    return ctx


def build_multi_sni_context(hostnames: list[str]) -> ssl.SSLContext:
    """One listener, several possible TLS identities (SNI-selected).

    We now serve config.REWRITE_HOST (fixture replay - see app.py) *and*
    config.PROXIED_HOSTS (real Microsoft hosts we MITM - see
    session_proxy.py) on the same 0.0.0.0:443, since both get hosts-file
    redirected to 127.0.0.1 and a client only ever presents one hostname
    per TLS handshake via SNI. The default context (first hostname) also
    serves as the fallback for any ClientHello that omits SNI entirely.
    """
    contexts = {h: build_ssl_context(h) for h in hostnames}
    default_ctx = contexts[hostnames[0]]

    def _sni_callback(ssl_socket: ssl.SSLObject, server_name: str | None, ctx: ssl.SSLContext) -> None:
        if server_name and server_name in contexts:
            ssl_socket.context = contexts[server_name]
        # else: leave the default context in place (also covers server_name is None)

    default_ctx.sni_callback = _sni_callback
    # keep the others alive - sni_callback only swaps ssl_socket.context, it
    # doesn't retain a reference to `contexts` on its own beyond the closure
    default_ctx._extra_contexts = contexts  # type: ignore[attr-defined]
    return default_ctx
