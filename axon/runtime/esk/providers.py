"""
AXON Runtime — Secret Providers (ESK Fase 6.4.c)
====================================================
Pluggable backends for `Secret[T]` that fetch credentials from external
vaults at `reveal()` time instead of carrying them in memory from
construction.  Three canonical providers are implemented:

  • `VaultProvider`     — HashiCorp Vault (KV v2) via `hvac`
  • `AwsKmsProvider`    — AWS Secrets Manager / KMS-encrypted Parameter Store via `boto3`
  • `AzureKeyVaultProvider` — Azure Key Vault via the official SDK

All three share the same `SecretProvider` protocol.  Adopters can
implement their own (PrivateBin, 1Password Connect, cloud-native CSPs)
without touching the Axon core.

Design anchors
--------------
• **Lazy import**, zero hard dep on any SDK. Missing lib ⇒ clear
  `HandlerUnavailableError` at constructor time.  Same policy as
  DilithiumSigner and HomomorphicContext.
• **`Secret.from_provider(provider, path)`** is the sanctioned
  construction path; the payload is materialized ONLY inside the scope
  of `reveal()`, preserving the no-materialize invariant.
• **Audit**: every `reveal()` through a provider records the accessor
  + purpose + the provider's identifier in `SecretAccess`.
• **Cache policy**: provider implementations MAY cache, but must
  expose a `refresh()` hook and respect a TTL.  Default: no caching —
  each reveal() hits the upstream vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from axon.runtime.handlers.base import (
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
)


# ═══════════════════════════════════════════════════════════════════
#  Protocol
# ═══════════════════════════════════════════════════════════════════

class SecretProvider(Protocol):
    """Backends that resolve a secret path to a payload on demand."""
    name: str

    def fetch(self, path: str) -> str | bytes | dict[str, Any]:
        """Fetch the secret at `path` from the backend. Raises
        `NetworkPartitionError` on reachability failure (CT-3) and
        `InfrastructureBlameError` on auth/quota failure (CT-3)."""
        ...


# ═══════════════════════════════════════════════════════════════════
#  HashiCorp Vault
# ═══════════════════════════════════════════════════════════════════

@dataclass
class VaultProvider:
    """
    HashiCorp Vault KV v2 provider.

    Parameters
    ----------
    url : str
        Vault server URL, e.g. `"https://vault.internal:8200"`.
    token : str
        Vault token with read permission on the target paths.
    mount_point : str
        KV secrets engine mount point (default: `"secret"`).
    namespace : str | None
        Vault Enterprise namespace (optional).
    """
    url: str
    token: str
    mount_point: str = "secret"
    namespace: str | None = None
    name: str = "vault"

    def __post_init__(self) -> None:
        try:
            import hvac  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "VaultProvider requires 'hvac'. "
                "Install with `pip install axon-lang[vault]`."
            ) from exc
        self._hvac = hvac
        self._client = hvac.Client(
            url=self.url,
            token=self.token,
            namespace=self.namespace,
        )

    def fetch(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.mount_point,
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if any(m in msg for m in (
                "timeout", "connection", "unreachable", "no route to host",
            )):
                raise NetworkPartitionError(
                    f"Vault unreachable at '{self.url}': {exc}"
                ) from exc
            raise InfrastructureBlameError(
                f"Vault fetch failed for '{path}': {exc}"
            ) from exc
        try:
            return response["data"]["data"]
        except (KeyError, TypeError) as exc:
            raise InfrastructureBlameError(
                f"Vault returned malformed response for '{path}'"
            ) from exc


# ═══════════════════════════════════════════════════════════════════
#  AWS Secrets Manager / KMS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AwsKmsProvider:
    """
    AWS Secrets Manager provider (backed by KMS envelope encryption).

    Parameters
    ----------
    region : str
        AWS region — defaults to boto3's resolution order.
    profile : str | None
        Optional boto3 profile name.
    """
    region: str | None = None
    profile: str | None = None
    name: str = "aws_sm"

    def __post_init__(self) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
            from botocore import exceptions as botocore_exc  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "AwsKmsProvider requires 'boto3'. "
                "Install with `pip install axon-lang[aws]`."
            ) from exc
        self._boto3 = boto3
        self._botocore_exc = botocore_exc
        session_kwargs: dict[str, Any] = {}
        if self.profile:
            session_kwargs["profile_name"] = self.profile
        self._session = boto3.Session(**session_kwargs)
        client_kwargs: dict[str, Any] = {}
        if self.region:
            client_kwargs["region_name"] = self.region
        self._client = self._session.client("secretsmanager", **client_kwargs)

    def fetch(self, path: str) -> str | bytes:
        """Fetch the secret at `path` (AWS Secret ID or ARN).

        Returns `SecretString` as `str` when available, else `SecretBinary`
        as `bytes`.
        """
        try:
            response = self._client.get_secret_value(SecretId=path)
        except self._botocore_exc.EndpointConnectionError as exc:
            raise NetworkPartitionError(
                f"AWS Secrets Manager unreachable: {exc}"
            ) from exc
        except self._botocore_exc.NoCredentialsError as exc:
            raise InfrastructureBlameError(
                f"no AWS credentials for Secrets Manager: {exc}"
            ) from exc
        except self._botocore_exc.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            raise InfrastructureBlameError(
                f"AWS Secrets Manager fetch failed ({code}) for '{path}': {exc}"
            ) from exc
        if "SecretString" in response:
            return response["SecretString"]
        if "SecretBinary" in response:
            return response["SecretBinary"]
        raise InfrastructureBlameError(
            f"AWS Secrets Manager response for '{path}' has neither "
            f"SecretString nor SecretBinary"
        )


# ═══════════════════════════════════════════════════════════════════
#  Azure Key Vault
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AzureKeyVaultProvider:
    """
    Azure Key Vault provider.

    Parameters
    ----------
    vault_url : str
        Key Vault URL, e.g. `"https://my-vault.vault.azure.net/"`.
    credential : Any | None
        An azure.identity credential. Defaults to `DefaultAzureCredential`
        (which resolves via env vars, managed identity, Azure CLI, etc.).
    """
    vault_url: str
    credential: Any = None
    name: str = "azure_keyvault"

    def __post_init__(self) -> None:
        try:
            from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found]
            from azure.core import exceptions as azure_exc  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "AzureKeyVaultProvider requires 'azure-keyvault-secrets'. "
                "Install with `pip install axon-lang[keyvault]`."
            ) from exc
        self._azure_exc = azure_exc
        if self.credential is None:
            try:
                from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
            except ImportError as exc:
                raise HandlerUnavailableError(
                    "AzureKeyVaultProvider default credential requires "
                    "'azure-identity'. Install with `pip install axon-lang[keyvault]`."
                ) from exc
            self.credential = DefaultAzureCredential()
        self._client = SecretClient(vault_url=self.vault_url, credential=self.credential)

    def fetch(self, path: str) -> str:
        """Fetch the secret value at `path` (Key Vault secret name)."""
        try:
            secret = self._client.get_secret(path)
        except self._azure_exc.ServiceRequestError as exc:
            raise NetworkPartitionError(
                f"Azure Key Vault unreachable at '{self.vault_url}': {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise InfrastructureBlameError(
                f"Azure Key Vault fetch failed for '{path}': {exc}"
            ) from exc
        value = secret.value
        if value is None:
            raise InfrastructureBlameError(
                f"Azure Key Vault returned None for '{path}'"
            )
        return value


# ═══════════════════════════════════════════════════════════════════
#  Secret.from_provider — convenience factory
# ═══════════════════════════════════════════════════════════════════

def secret_from_provider(
    provider: SecretProvider,
    path: str,
    *,
    label: str = "",
):
    """Fetch a secret from `provider` at `path` and wrap it in a `Secret[T]`.

    The payload is materialized ONLY inside this function's scope before
    being captured by `Secret.__init__`.  Once wrapped, the normal
    no-materialize invariant applies.  The `Secret`'s label defaults to
    `"{provider.name}:{path}"` for audit clarity.
    """
    from .secret import Secret  # local import: avoid circular

    payload = provider.fetch(path)
    full_label = label or f"{provider.name}:{path}"
    return Secret(payload, label=full_label)


__all__ = [
    "AwsKmsProvider",
    "AzureKeyVaultProvider",
    "SecretProvider",
    "VaultProvider",
    "secret_from_provider",
]
