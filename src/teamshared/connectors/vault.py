"""Envelope encryption for connector OAuth tokens (AES-256-GCM).

The data key comes from ``settings.connector_encryption_key``. Only ciphertext,
nonce, and a key id are persisted, so a database dump never exposes a usable
token. The key id lets us rotate keys (decrypt-with-old, re-encrypt-with-new)
without ambiguity.

The vault stores a *token bundle* (JSON) inside the envelope so a single
encrypted record can carry the access token, refresh token, expiry, token type,
and granted scope together. Callers pass/recvieve a :class:`TokenBundle`; the
``access_token`` convenience accessors keep the legacy single-token path
(:meth:`encrypt` / :meth:`decrypt`) working for connectors that only need one
secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from teamshared.logging import get_logger

log = get_logger(__name__)


@dataclass
class TokenBundle:
    """All secrets + metadata for one connector credential, in plaintext."""

    access_token: str
    refresh_token: str | None = None
    token_type: str | None = None
    scope: str | None = None
    expires_at: str | None = None  # ISO-8601; None = no expiry (or unknown)

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_type": self.token_type,
                "scope": self.scope,
                "expires_at": self.expires_at,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "TokenBundle":
        data = json.loads(raw)
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type"),
            scope=data.get("scope"),
            expires_at=data.get("expires_at"),
        )

    def is_expired(self, *, skew_seconds: int = 60) -> bool:
        """True when the access token has expired (or will within ``skew_seconds``)."""
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        now = datetime.now(exp.tzinfo) if exp.tzinfo else datetime.utcnow()
        return (exp.timestamp() - now.timestamp()) <= skew_seconds


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
        """Encrypt a single plaintext token (legacy single-secret path)."""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode(), None)
        return ct, nonce, self.key_id

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """Decrypt a single plaintext token (legacy single-secret path)."""
        return self._aes.decrypt(bytes(nonce), bytes(ciphertext), None).decode()

    def encrypt_bundle(self, bundle: TokenBundle) -> tuple[bytes, bytes, str]:
        """Encrypt a full token bundle (access + refresh + expiry + scope)."""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, bundle.to_json().encode(), None)
        return ct, nonce, self.key_id

    def decrypt_bundle(self, ciphertext: bytes, nonce: bytes) -> TokenBundle:
        """Decrypt a token bundle previously stored with :meth:`encrypt_bundle`."""
        raw = self._aes.decrypt(bytes(nonce), bytes(ciphertext), None).decode()
        return TokenBundle.from_json(raw)
