"""Attribute mapping — IdP claims → Axon user + role binding.

Every tenant's ``SsoConfiguration.attribute_map`` tells us which IdP
claim to read for each Axon field. Missing map entries fall back to
sensible defaults (``email`` → ``email``, ``display_name`` → ``name``)
so a zero-config deployment against a standard OIDC provider works
out of the box.

The role mapper is separate because SAML and OIDC surface "groups"
differently (SAML as a repeatable attribute, OIDC as a custom claim
or the ``groups`` scope).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class MappedIdentity:
    """Normalised view of the authenticated person ready to upsert."""

    email: str
    display_name: str | None
    external_subject: str
    raw_claims: Mapping[str, Any]
    groups: tuple[str, ...]


def map_oidc_identity(
    claims: Mapping[str, Any],
    *,
    attribute_map: Mapping[str, str],
) -> MappedIdentity:
    """Read OIDC ID-token claims into the canonical ``MappedIdentity``."""
    email_key = attribute_map.get("email", "email")
    name_key = attribute_map.get("display_name", "name")
    groups_key = attribute_map.get("groups", "groups")

    email = claims.get(email_key)
    if not email:
        raise ValueError(f"OIDC claims missing {email_key!r}")
    display = claims.get(name_key) or claims.get("preferred_username")
    groups_raw = claims.get(groups_key) or []
    if isinstance(groups_raw, str):
        groups_raw = [groups_raw]
    return MappedIdentity(
        email=str(email).lower(),
        display_name=str(display) if display else None,
        external_subject=str(claims.get("sub") or ""),
        raw_claims=dict(claims),
        groups=tuple(str(g) for g in groups_raw),
    )


def map_saml_identity(
    subject_nameid: str,
    attributes: Mapping[str, list[str]],
    *,
    attribute_map: Mapping[str, str],
) -> MappedIdentity:
    """Read SAML attribute statements into the canonical ``MappedIdentity``."""
    email_key = attribute_map.get("email", "email")
    name_key = attribute_map.get("display_name", "displayName")
    groups_key = attribute_map.get("groups", "groups")

    email_vals = attributes.get(email_key) or attributes.get("emailaddress")
    email = email_vals[0] if email_vals else subject_nameid
    if not email:
        raise ValueError("SAML assertion carries no email / nameID")

    name_vals = attributes.get(name_key) or attributes.get("cn")
    display = name_vals[0] if name_vals else None

    return MappedIdentity(
        email=str(email).lower(),
        display_name=str(display) if display else None,
        external_subject=subject_nameid,
        raw_claims={k: list(v) for k, v in attributes.items()},
        groups=tuple(attributes.get(groups_key) or []),
    )


def resolve_axon_roles(
    mapped: MappedIdentity,
    *,
    role_map: Mapping[str, str],
) -> list[str]:
    """Translate IdP groups to Axon role names via ``role_map``.

    Groups absent from ``role_map`` are ignored (no implicit role
    creation). Duplicates are collapsed while preserving first-seen
    order so operators can reason about precedence.
    """
    seen: set[str] = set()
    out: list[str] = []
    for group in mapped.groups:
        axon_role = role_map.get(group)
        if axon_role and axon_role not in seen:
            seen.add(axon_role)
            out.append(axon_role)
    return out
