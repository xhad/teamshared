"""Envelope encryption for connector OAuth tokens (AES-256-GCM).

The data key comes from ``settings.connector_encryption_key``. Only ciphertext,
nonce, and a key id are persisted, so a database dump never exposes a usable
token. The key id lets us rotate keys (decrypt-with-old, re-encrypt-with-new)
without ambiguity.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from teamshared.logging import get_logger

log = get_logger(__name__)


def _load_key(raw: str | None) -> tuple[bytes, str]:
    """Return a 32-byte key + a short key id. Derives a dev key when unset."""
    if not raw:
        log.warning("connector_vault_dev_key", reason="no connector_encryption_key set")
        material = b"teamshared-dev-connector-key"
    else:
        try:
            material = base64.b64decode(raw, validate=True)
            if len(material) != 32:
                raise ValueError
        except (ValueError, binascii.Error):
            try:
                material = bytes.fromhex(raw)
            except ValueError:
                material = raw.encode()
    key = hashlib.sha256(material).digest()
    key_id = hashlib.sha256(key).hexdigest()[:12]
    return key, key_id


class TokenVault:
    def __init__(self, encryption_key: str | None) -> None:
        self._key, self.key_id = _load_key(encryption_key)
        self._aes = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes, str]:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode(), None)
        return ct, nonce, self.key_id

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        return self._aes.decrypt(bytes(nonce), bytes(ciphertext), None).decode()
