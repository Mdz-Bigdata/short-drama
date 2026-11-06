"""Reading RSA keys, and the one signature scheme both channels use: SHA256 with RSA."""

from __future__ import annotations

import base64
import textwrap
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _as_pem(text: str, kind: str) -> bytes:
    """Alipay hands out keys as one bare line of base64; everything expects PEM."""
    clean = text.strip()
    if clean.startswith("-----BEGIN"):
        return clean.encode()
    body = "\n".join(textwrap.wrap("".join(clean.split()), 64))
    return f"-----BEGIN {kind}-----\n{body}\n-----END {kind}-----\n".encode()


def load_private_key(path: str):
    return serialization.load_pem_private_key(_as_pem(Path(path).read_text(), "PRIVATE KEY"), password=None)


def load_public_key(path: str):
    return serialization.load_pem_public_key(_as_pem(Path(path).read_text(), "PUBLIC KEY"))


def sign(private_key, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()


def verify(public_key, message: bytes, signature: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature, validate=True), message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
