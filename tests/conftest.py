"""Pytest fixtures and helpers for folioman-client tests."""

from __future__ import annotations

import base64
import json
import pytest


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


@pytest.fixture
def mock_jwt_factory():
    """Fixture providing create_mock_jwt factory function."""
    return create_mock_jwt
