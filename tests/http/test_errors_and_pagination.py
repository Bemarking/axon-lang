"""Unit tests for the error mapping + pagination helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from axon_enterprise.http import (
    CursorPage,
    OffsetPage,
    error_response_for,
    json_error,
    parse_cursor,
    parse_pagination_params,
)
from axon_enterprise.http.pagination import Cursor
from axon_enterprise.identity.errors import (
    AccountLockedError,
    InvalidCredentialsError,
    PasswordPolicyViolation,
    SessionExpiredError,
    TotpVerificationError,
)
from axon_enterprise.metering.errors import QuotaExceeded, RateLimited
from axon_enterprise.rbac.errors import PermissionDenied
from axon_enterprise.secrets.errors import SecretNotFound, SecretValueTooLarge


# ── error_response_for ───────────────────────────────────────────────


def test_invalid_credentials_collapses_to_generic_401() -> None:
    status, body = error_response_for(InvalidCredentialsError())
    assert status == 401
    assert body["error"]["code"] == "auth.invalid_credentials"
    # reveal_to_client=False → generic message
    assert body["error"]["message"] == "Authentication required"


def test_session_expired_reveals_message() -> None:
    status, body = error_response_for(SessionExpiredError())
    assert status == 401
    # reveal_to_client=True on SessionExpiredError
    # (but collapsed to generic when reveal=False; here reveal=True)
    assert body["error"]["code"] == "auth.session_expired"


def test_permission_denied_403_with_identifier() -> None:
    status, body = error_response_for(PermissionDenied("secret:write"))
    assert status == 403
    assert "secret:write" in body["error"]["message"]


def test_quota_exceeded_402_carries_metric_and_limit() -> None:
    status, body = error_response_for(
        QuotaExceeded(metric="flow.execution", quantity=1.0, limit=1000.0)
    )
    assert status == 402
    assert body["error"]["metric"] == "flow.execution"
    assert body["error"]["limit"] == 1000.0


def test_rate_limited_429_with_retry_after() -> None:
    status, body = error_response_for(
        RateLimited(metric="flow.execution", retry_after_seconds=42)
    )
    assert status == 429
    assert body["error"]["retry_after_seconds"] == 42


def test_rate_limited_json_response_sets_retry_after_header() -> None:
    resp = json_error(RateLimited(metric="m", retry_after_seconds=10))
    assert resp.headers["retry-after"] == "10"


def test_account_locked_403_reveals_until_timestamp() -> None:
    until = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    status, body = error_response_for(AccountLockedError(until))
    assert status == 403
    assert "2026-04-21" in body["error"]["message"]


def test_secret_not_found_404() -> None:
    status, _ = error_response_for(SecretNotFound("openai_api_key"))
    assert status == 404


def test_secret_too_large_413() -> None:
    status, _ = error_response_for(SecretValueTooLarge("60KB"))
    assert status == 413


def test_password_policy_400_reveals_violations() -> None:
    exc = PasswordPolicyViolation(["too short", "weak zxcvbn score"])
    status, body = error_response_for(exc)
    assert status == 400
    assert "too short" in body["error"]["message"]


def test_totp_verification_401_generic() -> None:
    status, body = error_response_for(TotpVerificationError())
    assert status == 401
    assert body["error"]["message"] == "Authentication required"


def test_unknown_exception_returns_500_opaque() -> None:
    status, body = error_response_for(RuntimeError("surprise"))
    assert status == 500
    assert body["error"]["code"] == "internal"
    # Never leak the raw exception text.
    assert "surprise" not in json.dumps(body)


# ── pagination ─────────────────────────────────────────────────────


def test_cursor_encodes_and_decodes() -> None:
    c = Cursor(
        last_created_at=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        last_id="abc123",
    )
    encoded = c.encode()
    parsed = parse_cursor(encoded)
    assert parsed is not None
    assert parsed.last_id == "abc123"
    assert parsed.last_created_at == c.last_created_at


def test_parse_cursor_none_returns_none() -> None:
    assert parse_cursor(None) is None
    assert parse_cursor("") is None


def test_parse_cursor_malformed_raises() -> None:
    with pytest.raises(ValueError):
        parse_cursor("not-valid-base64!")


def test_pagination_params_defaults() -> None:
    limit, offset, cursor = parse_pagination_params({})
    assert limit == 50
    assert offset == 0
    assert cursor is None


def test_pagination_params_accepts_both_dict_shapes() -> None:
    # Single-value
    limit, offset, _ = parse_pagination_params(
        {"limit": "10", "offset": "20"}
    )
    assert (limit, offset) == (10, 20)
    # Starlette parse_qs style
    limit, offset, _ = parse_pagination_params(
        {"limit": ["10"], "offset": ["20"]}
    )
    assert (limit, offset) == (10, 20)


def test_pagination_rejects_bad_limit() -> None:
    with pytest.raises(ValueError):
        parse_pagination_params({"limit": "nonint"})
    with pytest.raises(ValueError):
        parse_pagination_params({"limit": "0"})
    with pytest.raises(ValueError):
        parse_pagination_params({"limit": "10000"})  # > max_limit default 500


def test_pagination_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        parse_pagination_params({"offset": "-1"})


def test_offset_page_serialises_with_custom_item_fn() -> None:
    page = OffsetPage(items=[1, 2, 3], total=10, limit=5, offset=0)
    out = page.to_dict(lambda i: {"v": i})
    assert out == {
        "items": [{"v": 1}, {"v": 2}, {"v": 3}],
        "total": 10,
        "limit": 5,
        "offset": 0,
    }


def test_cursor_page_serialises() -> None:
    page: CursorPage[int] = CursorPage(items=[1, 2], next="abc")
    out = page.to_dict(lambda i: i)
    assert out == {"items": [1, 2], "next": "abc"}
