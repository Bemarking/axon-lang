"""AWS Secrets Manager backend.

Every operation maps 1-to-1 with an AWS SM API call. Minimal state is
kept in-process — we always hit AWS so tenants that rotate or revoke
outside our control (incident response) are reflected on the next
read.

``boto3`` is imported lazily so tests without AWS deps still pass.
The settings validator enforces ``backend=aws_sm`` in production so
forgetting to install the extras is caught at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from axon_enterprise.config import SecretsSettings, get_settings
from axon_enterprise.secrets.backend import SecretStoreEntry, SecretsBackend
from axon_enterprise.secrets.errors import (
    SecretNotFound,
    SecretValueTooLarge,
    SecretsBackendError,
)
from axon_enterprise.secrets.value import SecretValue

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.secrets.aws_sm"
)

_MAX_VALUE_BYTES: int = 65_536  # AWS SM hard limit for SecretString/Binary


@dataclass
class AwsSmBackend(SecretsBackend):
    """AWS Secrets Manager-backed implementation."""

    _client: Any
    settings: SecretsSettings

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_settings(cls) -> AwsSmBackend:
        settings = get_settings().secrets
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise SecretsBackendError(
                "boto3 required for the AWS Secrets Manager backend. "
                "Install with `pip install 'axon-enterprise[aws]'`."
            ) from exc
        kwargs: dict[str, Any] = {}
        if settings.aws_region:
            kwargs["region_name"] = settings.aws_region
        client = boto3.client("secretsmanager", **kwargs)
        return cls(_client=client, settings=settings)

    @classmethod
    def for_testing(cls, client: Any) -> AwsSmBackend:
        """Constructor with an injected (moto / stub) client."""
        return cls(_client=client, settings=get_settings().secrets)

    # ── SecretsBackend protocol ───────────────────────────────────────

    async def put(
        self, path: str, value: SecretValue, *, description: str | None = None
    ) -> SecretStoreEntry:
        self._check_size(value)
        if await self.exists(path):
            return await self._put_new_version(path, value, description=description)
        return await self._create(path, value, description=description)

    async def get(self, path: str) -> tuple[SecretValue, SecretStoreEntry]:
        try:
            resp = self._call("get_secret_value", SecretId=path)
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                raise SecretNotFound(path) from exc
            raise SecretsBackendError(
                f"AWS SM get_secret_value {path} failed: {exc}"
            ) from exc
        raw = resp.get("SecretString")
        if raw is None:
            binary = resp.get("SecretBinary")
            if binary is None:
                raise SecretsBackendError(
                    f"AWS SM returned neither SecretString nor SecretBinary for {path}"
                )
            value = SecretValue(binary)
        else:
            value = SecretValue(raw)
        entry = SecretStoreEntry(
            path=path,
            version_id=str(resp.get("VersionId") or ""),
            arn=resp.get("ARN"),
            size_bytes=value.length,
        )
        return value, entry

    async def delete(self, path: str, *, recovery_window_days: int) -> None:
        try:
            self._call(
                "delete_secret",
                SecretId=path,
                RecoveryWindowInDays=recovery_window_days,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                raise SecretNotFound(path) from exc
            raise SecretsBackendError(
                f"AWS SM delete_secret {path} failed: {exc}"
            ) from exc

    async def rotate(
        self, path: str, new_value: SecretValue
    ) -> SecretStoreEntry:
        # AWS SM handles AWSCURRENT/AWSPREVIOUS on every put_secret_value
        # — no explicit rotation call needed from our side.
        return await self._put_new_version(path, new_value, description=None)

    async def exists(self, path: str) -> bool:
        try:
            self._call("describe_secret", SecretId=path)
            return True
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                return False
            raise SecretsBackendError(
                f"AWS SM describe_secret {path} failed: {exc}"
            ) from exc

    # ── Internals ─────────────────────────────────────────────────────

    async def _create(
        self,
        path: str,
        value: SecretValue,
        *,
        description: str | None,
    ) -> SecretStoreEntry:
        kwargs: dict[str, Any] = {
            "Name": path,
            "SecretString": value.reveal(),
        }
        if description:
            kwargs["Description"] = description
        try:
            resp = self._call("create_secret", **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise SecretsBackendError(
                f"AWS SM create_secret {path} failed: {exc}"
            ) from exc
        return SecretStoreEntry(
            path=path,
            version_id=str(resp.get("VersionId") or ""),
            arn=resp.get("ARN"),
            size_bytes=value.length,
        )

    async def _put_new_version(
        self,
        path: str,
        value: SecretValue,
        *,
        description: str | None,
    ) -> SecretStoreEntry:
        try:
            resp = self._call(
                "put_secret_value",
                SecretId=path,
                SecretString=value.reveal(),
            )
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                raise SecretNotFound(path) from exc
            raise SecretsBackendError(
                f"AWS SM put_secret_value {path} failed: {exc}"
            ) from exc
        # Description is only set via update_secret, which must be a
        # separate call (AWS SM api limitation).
        if description:
            try:
                self._call("update_secret", SecretId=path, Description=description)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "secrets_update_description_failed",
                    path=path,
                    error=str(exc),
                )
        return SecretStoreEntry(
            path=path,
            version_id=str(resp.get("VersionId") or ""),
            arn=resp.get("ARN"),
            size_bytes=value.length,
        )

    def _check_size(self, value: SecretValue) -> None:
        if value.length > _MAX_VALUE_BYTES:
            raise SecretValueTooLarge(
                f"value of {value.length} bytes exceeds AWS SM's "
                f"{_MAX_VALUE_BYTES}-byte limit"
            )

    def _call(self, op: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a boto3 method. boto3 is sync — wrap at call site if needed."""
        method = getattr(self._client, op)
        return method(**kwargs)


def _is_not_found(exc: Exception) -> bool:
    """Heuristic for ResourceNotFoundException across boto3 / moto / stubs."""
    name = type(exc).__name__
    if name.endswith("ResourceNotFoundException"):
        return True
    # Fallback: boto3 wraps AWS errors in ClientError with a response dict.
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            return True
    return False
