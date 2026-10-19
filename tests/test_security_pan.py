"""Tests for PAN normalization, masking, hashing, and Fernet encryption."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from folioman_client.security.keys import (
    resolve_fernet_key,
)
from folioman_client.security.pan import (
    decrypt_pan,
    encrypt_pan,
    mask_pan,
    normalize_pan,
    pan_hash,
)


def test_normalize_pan() -> None:
    assert normalize_pan("abcde1234f") == "ABCDE1234F"
    assert normalize_pan("  ABCDE1234F  ") == "ABCDE1234F"
    assert normalize_pan("aBcDe1234F") == "ABCDE1234F"
    assert normalize_pan("") == ""


def test_mask_pan() -> None:
    assert mask_pan("ABCDE1234F") == "XXXXXX234F"
    assert mask_pan("abcde1234f") == "XXXXXX234F"
    assert mask_pan("  ABCDE1234F  ") == "XXXXXX234F"
    # Short inputs
    assert mask_pan("1234") == "1234"
    assert mask_pan("12") == "12"
    assert mask_pan("") == ""


def test_pan_hash_determinism_and_normalization() -> None:
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()

    hash_upper = pan_hash("ABCDE1234F", key_bytes=key1)
    hash_lower = pan_hash("abcde1234f", key_bytes=key1)
    hash_spaced = pan_hash("  ABCDE1234F  ", key_bytes=key1)

    # Identical PAN with casing/whitespace differences produces identical hash
    assert hash_upper == hash_lower == hash_spaced
    assert len(hash_upper) == 64  # SHA-256 hex digest length

    # Different key produces different hash
    hash_different_key = pan_hash("ABCDE1234F", key_bytes=key2)
    assert hash_upper != hash_different_key


def test_encrypt_and_decrypt_pan_roundtrip() -> None:
    key = Fernet.generate_key()
    pan = "ABCDE1234F"

    token = encrypt_pan(pan, key_bytes=key)
    assert isinstance(token, bytes)
    assert token != pan.encode()

    decrypted = decrypt_pan(token, key_bytes=key)
    assert decrypted == pan


def test_encrypt_pan_normalizes_casing() -> None:
    key = Fernet.generate_key()
    token = encrypt_pan("abcde1234f", key_bytes=key)
    assert decrypt_pan(token, key_bytes=key) == "ABCDE1234F"


def test_decrypt_pan_with_invalid_key_fails() -> None:
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()

    token = encrypt_pan("ABCDE1234F", key_bytes=key1)
    with pytest.raises(InvalidToken):
        decrypt_pan(token, key_bytes=key2)


def test_decrypt_tampered_token_fails() -> None:
    key = Fernet.generate_key()
    token = bytearray(encrypt_pan("ABCDE1234F", key_bytes=key))
    # Mutate a byte in ciphertext
    token[-5] ^= 0xFF

    with pytest.raises(InvalidToken):
        decrypt_pan(bytes(token), key_bytes=key)


def test_resolve_fernet_key_explicit() -> None:
    test_key = Fernet.generate_key()
    assert resolve_fernet_key(test_key) == test_key
    assert resolve_fernet_key(test_key.decode("ascii")) == test_key


def test_resolve_fernet_key_from_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "fernet.key"
    test_key = Fernet.generate_key()
    key_file.write_bytes(test_key)

    # Reset LRU cache
    resolve_fernet_key.cache_clear()
    monkeypatch.setattr("folioman_client.config.settings.data_dir", str(tmp_path))
    monkeypatch.setattr("folioman_client.config.settings.fernet_key", "")
    monkeypatch.delenv("FOLIOMAN_FERNET_KEY", raising=False)

    resolved = resolve_fernet_key()
    assert resolved == test_key
    resolve_fernet_key.cache_clear()


def test_resolve_fernet_key_generates_file_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "new_dir"
    resolve_fernet_key.cache_clear()
    monkeypatch.setattr("folioman_client.config.settings.data_dir", str(data_dir))
    monkeypatch.setattr("folioman_client.config.settings.fernet_key", "")
    monkeypatch.delenv("FOLIOMAN_FERNET_KEY", raising=False)

    resolved = resolve_fernet_key()
    assert isinstance(resolved, bytes)
    assert len(resolved) == 44  # Base64 encoded 32-byte key
    # Check that file was created on disk
    key_path = data_dir / "fernet.key"
    assert key_path.exists()
    assert key_path.read_bytes().strip() == resolved
    resolve_fernet_key.cache_clear()
