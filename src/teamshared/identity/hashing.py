"""Password/secret hashing using stdlib scrypt (no extra dependency).

Format: ``scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>``. Verification is
constant-time. scrypt is memory-hard and adequate for API-key secrets, which
are already high-entropy random tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(dk, expected)
