"""Unit tests for ``PasswordPolicy``. HIBP is stubbed — no network calls."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.errors import PasswordPolicyViolation
from axon_enterprise.identity.password_policy import PasswordPolicy


def _policy(**overrides: Any) -> PasswordPolicy:
    base = dict(
        password_min_length=12,
        password_zxcvbn_min_score=3,
        password_check_hibp=False,  # default off for most tests
    )
    base.update(overrides)
    return PasswordPolicy(settings=IdentitySettings(**base))


@pytest.mark.asyncio
async def test_too_short_rejected() -> None:
    p = _policy()
    with pytest.raises(PasswordPolicyViolation) as exc:
        await p.validate("short")
    assert any("at least" in v for v in exc.value.violations)


@pytest.mark.asyncio
async def test_weak_rejected_by_zxcvbn() -> None:
    # 12 chars but trivially guessable.
    p = _policy()
    with pytest.raises(PasswordPolicyViolation):
        await p.validate("passwordpass")


@pytest.mark.asyncio
async def test_strong_accepted() -> None:
    p = _policy()
    await p.validate("correct-horse-battery-staple-9")


@pytest.mark.asyncio
async def test_user_inputs_penalise_echo() -> None:
    p = _policy()
    # Password containing the email stem is penalised.
    with pytest.raises(PasswordPolicyViolation):
        await p.validate(
            "alice-acme-2026!",
            user_inputs=["alice", "alice@acme.com"],
        )


class _MockResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _MockAsyncClient:
    def __init__(self, response: _MockResponse, **_: Any) -> None:
        self._response = response

    async def __aenter__(self) -> _MockAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str) -> _MockResponse:
        return self._response


@pytest.mark.asyncio
async def test_hibp_breached_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    password = "correct-horse-battery-staple-breached"
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    mock_resp = _MockResponse(200, f"{suffix}:42\r\nOTHER:1\r\n")

    def _fake_async_client(*args: Any, **kwargs: Any) -> _MockAsyncClient:
        return _MockAsyncClient(mock_resp)

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client)

    p = _policy(password_check_hibp=True)
    with pytest.raises(PasswordPolicyViolation) as exc:
        await p.validate(password)
    assert any("breaches" in v for v in exc.value.violations)


@pytest.mark.asyncio
async def test_hibp_network_error_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise httpx.RequestError("boom")

    class _RaisingClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> _RaisingClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url: str) -> None:
            raise httpx.RequestError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", _RaisingClient)

    p = _policy(password_check_hibp=True)
    # Network failure MUST NOT cause a policy violation — fail open.
    await p.validate("correct-horse-battery-staple-9")
