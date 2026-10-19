"""PAN normalization, masking, encryption, and keyed lookup hashing."""

from __future__ import annotations

import hashlib
import hmac

from folioman_client.security.keys import get_fernet, get_key_bytes


def normalize_pan(pan: str) -> str:
    """Normalize a PAN string by stripping surrounding whitespace and uppercasing."""
    return pan.strip().upper()


def mask_pan(pan: str) -> str:
    """Mask sensitive characters of a PAN for safe display (e.g. 'XXXXXX1234F').

    Keeps the last 4 characters visible, replacing the prefix with 'X'.
    """
    normalized = normalize_pan(pan)
    if len(normalized) > 4:
        return "X" * (len(normalized) - 4) + normalized[-4:]
    return normalized


def pan_hash(pan: str, key_bytes: bytes | None = None) -> str:
    """Compute a keyed HMAC-SHA256 hex digest of the normalized PAN.

    Using an HMAC seeded with the encryption secret prevents dictionary and rainbow-table
    attacks on low-entropy PANs while allowing deterministic equality lookups in SQL.
    """
    secret = key_bytes or get_key_bytes()
    return hmac.new(secret, normalize_pan(pan).encode(), hashlib.sha256).hexdigest()


def encrypt_pan(pan: str, key_bytes: bytes | None = None) -> bytes:
    """Encrypt a plaintext PAN into authenticated Fernet ciphertext bytes."""
    cipher = get_fernet(key_bytes)
    return cipher.encrypt(normalize_pan(pan).encode())


def decrypt_pan(token: bytes, key_bytes: bytes | None = None) -> str:
    """Decrypt authenticated Fernet ciphertext bytes back into the plaintext PAN."""
    cipher = get_fernet(key_bytes)
    return cipher.decrypt(bytes(token)).decode("utf-8")


__all__ = [
    "decrypt_pan",
    "encrypt_pan",
    "mask_pan",
    "normalize_pan",
    "pan_hash",
]
