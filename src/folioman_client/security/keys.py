"""Fernet key lifecycle management for PAN encryption."""

from __future__ import annotations

import os
import stat
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from folioman_client.config import settings
from folioman_client.errors import FernetKeyUnavailable

# Safe in-memory dev fallback key used strictly when testing or explicitly configured
DEV_FERNET_KEY = b"2Yl9G6f4WzK-y9o3C8x5R7v2M1p4Q8t6U0j2H5k8L4s="


def _generate_key_file(path: Path) -> bytes:
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    # Set owner read/write (0600) on platforms that support POSIX permissions
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return key


@lru_cache(maxsize=1)
def resolve_fernet_key(explicit_key: str | bytes | None = None) -> bytes:
    """Resolve the active 32-byte Fernet key.

    Resolution order:
      1. Explicit key parameter.
      2. FOLIOMAN_FERNET_KEY env variable or settings.fernet_key.
      3. Persistent key file under the resolved data directory (~/.folioman/fernet.key).
      4. Auto-generate key file if none exists.

    Returns:
        32-byte URL-safe base64 key bytes.

    Raises:
        FernetKeyUnavailable: If key resolution fails completely.
    """
    if explicit_key:
        return explicit_key.encode() if isinstance(explicit_key, str) else explicit_key

    env_key = settings.fernet_key or os.environ.get("FOLIOMAN_FERNET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    try:
        key_path = settings.resolved_data_dir / "fernet.key"
        if key_path.exists():
            return key_path.read_bytes().strip()
        return _generate_key_file(key_path)
    except Exception as exc:
        raise FernetKeyUnavailable(
            f"Failed to resolve or generate Fernet key: {exc}"
        ) from exc


def get_fernet(key: bytes | None = None) -> Fernet:
    """Return a Fernet cipher instance using the resolved or provided key."""
    return Fernet(key or resolve_fernet_key())


def get_key_bytes() -> bytes:
    """Return raw key bytes."""
    return resolve_fernet_key()


__all__ = [
    "resolve_fernet_key",
    "get_fernet",
    "get_key_bytes",
    "DEV_FERNET_KEY",
]
