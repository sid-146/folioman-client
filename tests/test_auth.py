"""Unit tests for Folioman JWTAuthManager."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
import respx

from folioman_client.auth import (
    JWTAuthManager,
    _extract_jwt_expiry,
    _is_expired,
)
from folioman_client.errors import FoliomanAuthError


def create_mock_jwt(exp: float) -> str:
    """Create a mock JWT with the given expiration timestamp."""
    header = (
        base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}')
        .decode("ascii")
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(json.dumps({"user_id": 1, "exp": exp}).encode("ascii"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"{header}.{payload}.mock_sig"


@pytest.mark.asyncio
async def test_jwt_expiry_parsing() -> None:
    now = time.time()
    token = create_mock_jwt(now + 3600)
    parsed_exp = _extract_jwt_expiry(token)
    assert parsed_exp is not None
    assert abs(parsed_exp - (now + 3600)) < 1.0

    assert not _is_expired(token, skew=30)
    assert _is_expired(token, skew=7200)


@pytest.mark.asyncio
async def test_successful_initial_authentication() -> None:
    base_url = "http://folioman.test"
    auth = JWTAuthManager(
        base_url=base_url, username="advisor", password="secretpassword"
    )

    valid_token = create_mock_jwt(time.time() + 3600)
    refresh_token = create_mock_jwt(time.time() + 86400)

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url=base_url) as respx_mock:
            auth_route = respx_mock.post("/api/auth/token/pair").respond(
                200,
                json={"access": valid_token, "refresh": refresh_token},
            )

            token = await auth.get_valid_token(client)
            assert token == valid_token
            assert auth_route.called
            assert auth.has_tokens


@pytest.mark.asyncio
async def test_invalid_credentials_raises_folioman_auth_error() -> None:
    base_url = "http://folioman.test"
    auth = JWTAuthManager(
        base_url=base_url, username="advisor", password="wrongpassword"
    )

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url=base_url) as respx_mock:
            respx_mock.post("/api/auth/token/pair").respond(
                401,
                json={"detail": "Invalid credentials."},
            )

            with pytest.raises(FoliomanAuthError, match="Invalid username or password"):
                await auth.get_valid_token(client)


@pytest.mark.asyncio
async def test_proactive_token_refresh() -> None:
    base_url = "http://folioman.test"
    auth = JWTAuthManager(
        base_url=base_url, username="advisor", password="secretpassword"
    )

    # Access token expiring in 10s (within 30s skew window)
    expiring_access = create_mock_jwt(time.time() + 10)
    refresh_token = create_mock_jwt(time.time() + 86400)
    new_access = create_mock_jwt(time.time() + 3600)

    auth._access_token = expiring_access
    auth._refresh_token = refresh_token

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url=base_url) as respx_mock:
            refresh_route = respx_mock.post("/api/auth/token/refresh").respond(
                200,
                json={"access": new_access},
            )

            token = await auth.get_valid_token(client)
            assert token == new_access
            assert refresh_route.called
            sent_body = json.loads(refresh_route.calls.last.request.content)
            assert sent_body == {"refresh": refresh_token}


@pytest.mark.asyncio
async def test_refresh_rejected_falls_back_to_login() -> None:
    base_url = "http://folioman.test"
    auth = JWTAuthManager(
        base_url=base_url, username="advisor", password="secretpassword"
    )

    expired_access = create_mock_jwt(time.time() - 100)
    stale_refresh = create_mock_jwt(time.time() - 50)
    new_access = create_mock_jwt(time.time() + 3600)
    new_refresh = create_mock_jwt(time.time() + 86400)

    auth._access_token = expired_access
    auth._refresh_token = stale_refresh

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url=base_url) as respx_mock:
            # Refresh returns 401
            respx_mock.post("/api/auth/token/refresh").respond(
                401, json={"detail": "Token expired"}
            )
            # Re-login succeeds
            respx_mock.post("/api/auth/token/pair").respond(
                200,
                json={"access": new_access, "refresh": new_refresh},
            )

            token = await auth.get_valid_token(client)
            assert token == new_access
            assert auth._refresh_token == new_refresh


@pytest.mark.asyncio
async def test_concurrent_token_refresh_single_flight() -> None:
    import asyncio

    base_url = "http://folioman.test"
    auth = JWTAuthManager(
        base_url=base_url, username="advisor", password="secretpassword"
    )

    auth._access_token = create_mock_jwt(time.time() - 100)
    auth._refresh_token = create_mock_jwt(time.time() + 86400)
    new_access = create_mock_jwt(time.time() + 3600)

    async with httpx.AsyncClient() as client:
        with respx.mock(base_url=base_url) as respx_mock:
            refresh_route = respx_mock.post("/api/auth/token/refresh").respond(
                200,
                json={"access": new_access},
            )

            tokens = await asyncio.gather(
                auth.get_valid_token(client),
                auth.get_valid_token(client),
                auth.get_valid_token(client),
                auth.get_valid_token(client),
            )

            assert all(t == new_access for t in tokens)
            # Exactly 1 refresh request was fired despite 4 concurrent calls
            assert refresh_route.call_count == 1
