"""
ca.py — Certificate Authority helper.

Generates (once) a self-signed root CA key/certificate pair used to sign
on-the-fly "leaf" certificates for every host the proxy intercepts over
HTTPS — the same trick Proxyman/Charles/mitmproxy use to see inside TLS.

The root certificate has to be installed as *trusted* on the device/browser
you want to sniff (see README.md) — that's what lets it accept the fake
per-host certificates we hand out instead of the real one.

Leaf certificates are generated lazily on first sight of a host and cached
on disk, so repeated runs don't regenerate one for a host already seen.
"""

from __future__ import annotations

import datetime
import ipaddress
import pathlib
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ONE_DAY = datetime.timedelta(days=1)


class CertificateAuthority:
    def __init__(self, storage_dir: str | pathlib.Path):
        self.dir = pathlib.Path(storage_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.leaf_dir = self.dir / "leaf-certs"
        self.leaf_dir.mkdir(exist_ok=True)

        self._lock = threading.Lock()
        self._ca_key, self._ca_cert = self._load_or_create_ca()
        # Windows only wires up the "Install Certificate..." double-click wizard
        # for extensions like .cer/.crt — .pem often just opens in a text editor.
        # Keep an identical byte-for-byte copy under that name for convenience.
        if not self.root_cert_cer_path.exists():
            self.root_cert_cer_path.write_bytes(self.root_cert_path.read_bytes())

    # ---- root CA ---------------------------------------------------------

    @property
    def root_cert_path(self) -> pathlib.Path:
        return self.dir / "rootCA.pem"

    @property
    def root_cert_cer_path(self) -> pathlib.Path:
        return self.dir / "rootCA.cer"

    def _load_or_create_ca(self):
        key_path = self.dir / "rootCA.key"
        cert_path = self.root_cert_path

        if key_path.exists() and cert_path.exists():
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            return key, cert

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "PySniffer Root CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PySniffer (local dev only)"),
        ])

        now = datetime.datetime.utcnow()
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - ONE_DAY)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=True,
                    crl_sign=True, encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256())
        )

        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return key, cert

    # ---- per-host leaf certs ----------------------------------------------

    def get_leaf_cert(self, hostname: str) -> tuple[pathlib.Path, pathlib.Path]:
        """Return (cert_path, key_path) for hostname, generating + caching on first use."""
        safe = hostname.replace("*", "_wildcard_")
        cert_path = self.leaf_dir / f"{safe}.pem"
        key_path = self.leaf_dir / f"{safe}.key"

        if cert_path.exists() and key_path.exists():
            return cert_path, key_path

        with self._lock:
            if cert_path.exists() and key_path.exists():
                return cert_path, key_path

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])

            try:
                san = x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(hostname))])
            except ValueError:
                san = x509.SubjectAlternativeName([x509.DNSName(hostname)])

            ca_ski = self._ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value

            now = datetime.datetime.utcnow()
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(self._ca_cert.subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - ONE_DAY)
                .not_valid_after(now + datetime.timedelta(days=825))
                .add_extension(san, critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                # Some strict verifiers (recent OpenSSL, Windows chain building)
                # refuse to build/verify the chain without this — it links the
                # leaf back to the issuing CA's Subject Key Identifier.
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
                .sign(self._ca_key, hashes.SHA256())
            )

            key_path.write_bytes(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            return cert_path, key_path
