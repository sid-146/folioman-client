"""JWT Authentication Manager for Folioman.

Handles initial token generation, automatic refresh, proactive expiry detection,
and concurrency-safe token renewal.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import TYPE_CHECKING, Any

from folioman_client.errors import FoliomanAuthError

if TYPE_CHECKING:
    import httpx

# Refresh slightly before the token's real expiry to absorb clock skew and network latency.
EXP_SKEW_SECONDS = 30


def _extract_jwt_expiry(token: str) -> float | None:
    """Extract expiry timestamp (seconds since epoch) from a JWT payload without external deps.

    Args:
        token: The encoded JWT string.

    Returns:
        The float expiration timestamp (UNIX epoch), or None if unparseable.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        # Add required base64 padding
        payload_segment = parts[1]
        rem = len(payload_segment) % 4
        if rem > 0:
            payload_segment += "=" * (4 - rem)
        decoded = base64.urlsafe_b64decode(payload_segment.encode("ascii"))
        payload: dict[str, Any] = json.loads(decoded)
        exp = payload.get("exp")
        return float(exp) if isinstance(exp, (int, float)) else None
    except Exception:
        return None


def _is_expired(token: str, skew: int = EXP_SKEW_SECONDS) -> bool:
    """True when token is within skew seconds of expiring or unreadable.

    Args:
        token: The encoded JWT string.
        skew: Lead time in seconds before actual expiry to consider expired.

    Returns:
        True if the token is considered expired, False otherwise.
    """
    exp = _extract_jwt_expiry(token)
    if exp is None:
        # Treat unreadable token as usable; backend 401 will trigger recovery
        return False
    return time.time() >= (exp - skew)


class JWTAuthManager:
    """Manages JWT authentication state, token storage, and refresh lifecycle.

    Keeps tokens private so they are never leaked outside the client.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize JWTAuthManager with API credentials.

        Args:
            base_url: Base URL of the Folioman server.
            username: Username for authentication.
            password: Password for authentication.
        """
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._lock = asyncio.Lock()

    @property
    def has_tokens(self) -> bool:
        """True if the manager currently holds an access or refresh token."""
        return self._access_token is not None or self._refresh_token is not None

    def clear(self) -> None:
        """Clear cached access and refresh tokens."""
        self._access_token = None
        self._refresh_token = None

    async def get_valid_token(self, client: httpx.AsyncClient) -> str:
        """Return a valid access token, proactively refreshing or authenticating if needed.

        Args:
            client: The httpx AsyncClient transport instance to execute requests.

        Returns:
            A valid JWT access token string.

        Raises:
            FoliomanAuthError: If authentication or refresh fails.
        """
        # Fast path outside the lock if the current access token is fresh
        if self._access_token and not _is_expired(self._access_token):
            return self._access_token

        async with self._lock:
            # Re-check under lock in case another coroutine refreshed it
            if self._access_token and not _is_expired(self._access_token):
                return self._access_token

            # Try refresh if we have a refresh token
            if self._refresh_token:
                try:
                    return await self._refresh_access_token(client)
                except Exception:
                    # If refresh fails, fall back to initial authentication
                    pass

            # Otherwise, authenticate from credentials
            return await self._authenticate(client)

    async def force_refresh(self, client: httpx.AsyncClient) -> str:
        """Force a refresh or re-authentication after receiving a 401.

        Args:
            client: The httpx AsyncClient transport instance to execute requests.

        Returns:
            A new valid JWT access token string.

        Raises:
            FoliomanAuthError: If renewal or re-authentication fails.
        """
        async with self._lock:
            if self._refresh_token:
                try:
                    return await self._refresh_access_token(client)
                except Exception:
                    pass

            return await self._authenticate(client)

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Authenticate with username and password (/api/auth/token/pair).

        Args:
            client: The httpx AsyncClient transport instance.

        Returns:
            A newly acquired access token string.

        Raises:
            FoliomanAuthError: If authentication fails or response is invalid.
        """
        url = f"{self._base_url}/api/auth/token/pair"
        payload = {"username": self._username, "password": self._password}

        try:
            response = await client.post(url, json=payload)
        except Exception as exc:
            raise FoliomanAuthError(
                f"Network error during authentication: {exc}"
            ) from exc

        if response.status_code == 401:
            raise FoliomanAuthError("Invalid username or password.")
        if not response.is_success:
            raise FoliomanAuthError(
                f"Authentication failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        access = data.get("access")
        refresh = data.get("refresh")
        if not access or not refresh:
            raise FoliomanAuthError(
                "Malformed authentication response: missing tokens."
            )

        self._access_token = access
        self._refresh_token = refresh
        return access

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> str:
        """Mint a fresh access token from the refresh token (/api/auth/token/refresh).

        Args:
            client: The httpx AsyncClient transport instance.

        Returns:
            A refreshed access token string.

        Raises:
            FoliomanAuthError: If refresh token is expired, invalid, or missing.
        """
        if not self._refresh_token:
            raise FoliomanAuthError("No refresh token available.")

        url = f"{self._base_url}/api/auth/token/refresh"
        payload = {"refresh": self._refresh_token}

        try:
            response = await client.post(url, json=payload)
        except Exception as exc:
            raise FoliomanAuthError(
                f"Network error during token refresh: {exc}"
            ) from exc

        if response.status_code == 401:
            self.clear()
            raise FoliomanAuthError("Refresh token expired or invalid.")
        if not response.is_success:
            self.clear()
            raise FoliomanAuthError(
                f"Token refresh failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        access = data.get("access")
        if not access:
            self.clear()
            raise FoliomanAuthError("Malformed refresh response: missing access token.")

        self._access_token = access
        return access


__all__ = [
    "JWTAuthManager",
    "EXP_SKEW_SECONDS",
]
