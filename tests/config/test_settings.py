"""Unit tests for ``axon_enterprise.config.settings``."""

from __future__ import annotations

import pytest

from axon_enterprise.config import get_settings
from axon_enterprise.config.settings import DatabaseSettings, Environment, Settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _base_env() -> dict[str, str]:
    return {
        "AXON_ENV": "development",
        "AXON_DB__URL": "postgresql+asyncpg://u:p@localhost:5432/axon_test",
    }


def test_settings_loads_minimum_required_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.env is Environment.DEVELOPMENT
    assert s.db.pool_size == 10
    assert s.db.control_schema == "axon_control"
    assert s.rls_guc_name == "axon.current_tenant"


def test_production_rejects_plaintext_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AXON_ENV", "production")
    monkeypatch.setenv("AXON_DB__SSL_MODE", "prefer")
    with pytest.raises(ValueError, match="ssl_mode"):
        Settings()


def test_production_rejects_echo_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AXON_ENV", "production")
    monkeypatch.setenv("AXON_DB__ECHO_SQL", "true")
    with pytest.raises(ValueError, match="echo_sql"):
        Settings()


def test_secret_url_is_redacted_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert "p@localhost" not in repr(s)
    assert "p@localhost" not in repr(s.db)
    assert "**" in repr(s.db.url) or "SecretStr" in repr(s.db.url)


def test_guc_name_must_be_qualified() -> None:
    with pytest.raises(ValueError, match="qualified GUC name"):
        Settings(
            env=Environment.DEVELOPMENT,
            db=DatabaseSettings(
                url="postgresql+asyncpg://u:p@h/d",  # type: ignore[arg-type]
                ssl_mode="disable",
            ),
            rls_guc_name="no_dot",
        )
