"""Tests for apps/api/auth_utils.py

Covers JWT creation/validation and password hashing/verification.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import jwt as pyjwt
import pytest

from apps.api.auth_utils import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Password hashing / verification
# ---------------------------------------------------------------------------

class TestHashPassword:
    def test_returns_bcrypt_hash(self):
        hashed = hash_password("hello")
        assert hashed.startswith("$2")
        assert len(hashed) == 60

    def test_different_calls_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestVerifyPassword:
    def test_correct_password(self):
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("x", hashed) is False


# ---------------------------------------------------------------------------
# JWT creation
# ---------------------------------------------------------------------------

class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token(user_id=1, role="superadmin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_payload_contains_expected_claims(self):
        token = create_access_token(user_id=42, role="operator")
        payload = pyjwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "42"
        assert payload["role"] == "operator"
        assert "exp" in payload
        assert "iat" in payload

    def test_custom_expiration(self):
        token = create_access_token(user_id=1, role="superadmin", exp_minutes=1)
        payload = pyjwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        # exp should be close to now + 1 minute
        assert payload["exp"] - payload["iat"] <= 120  # allow some tolerance


# ---------------------------------------------------------------------------
# JWT decoding
# ---------------------------------------------------------------------------

class TestDecodeAccessToken:
    def test_valid_token(self):
        token = create_access_token(user_id=7, role="superadmin")
        payload = decode_access_token(token)
        assert payload["sub"] == "7"
        assert payload["role"] == "superadmin"

    def test_expired_token_raises(self):
        token = create_access_token(user_id=1, role="superadmin", exp_minutes=-1)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_invalid_token_raises(self):
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token("not.a.valid.token")

    def test_tampered_token_raises(self):
        token = create_access_token(user_id=1, role="superadmin")
        # Tamper with the token
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_wrong_secret_raises(self):
        payload = {"sub": "1", "role": "superadmin", "exp": int(time.time()) + 3600}
        token = pyjwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(token)
