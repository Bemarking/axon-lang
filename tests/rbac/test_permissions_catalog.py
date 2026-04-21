"""Unit tests for the permission catalog + parser."""

from __future__ import annotations

import pytest

from axon_enterprise.rbac import (
    BUILT_IN_ROLE_DESCRIPTIONS,
    BUILT_IN_ROLE_NAMES,
    BUILT_IN_ROLE_PERMISSIONS,
    InvalidPermissionString,
    PERMISSION_KEY_SET,
    SYSTEM_PERMISSIONS,
    parse_permission,
)


def test_catalog_has_no_duplicates() -> None:
    keys = [p.key for p in SYSTEM_PERMISSIONS]
    assert len(keys) == len(set(keys)), "duplicate permission key in catalog"


def test_catalog_covers_expected_resources() -> None:
    resources = {p.resource for p in SYSTEM_PERMISSIONS}
    assert resources == {
        "tenant",
        "user",
        "role",
        "flow",
        "secret",
        "audit",
        "metering",
        "observability",
    }


def test_catalog_every_entry_has_non_empty_description() -> None:
    for p in SYSTEM_PERMISSIONS:
        assert p.description.strip(), f"{p.key} has empty description"


def test_builtin_role_names_are_the_canonical_four() -> None:
    assert BUILT_IN_ROLE_NAMES == {"owner", "admin", "developer", "viewer"}


def test_owner_has_every_permission() -> None:
    assert set(BUILT_IN_ROLE_PERMISSIONS["owner"]) == PERMISSION_KEY_SET


def test_admin_excludes_only_destructive_and_impersonate() -> None:
    admin = set(BUILT_IN_ROLE_PERMISSIONS["admin"])
    assert "tenant:delete" not in admin
    assert "tenant:suspend" not in admin
    assert "user:impersonate" not in admin
    assert "tenant:update" in admin  # regression: admin still updates


def test_viewer_is_strictly_read_only() -> None:
    for key in BUILT_IN_ROLE_PERMISSIONS["viewer"]:
        resource, action = key.split(":", 1)
        assert action.startswith("read"), f"viewer holds non-read permission {key}"


def test_developer_has_flow_lifecycle() -> None:
    dev = set(BUILT_IN_ROLE_PERMISSIONS["developer"])
    for key in (
        "flow:create",
        "flow:read",
        "flow:update",
        "flow:execute",
        "flow:deploy",
    ):
        assert key in dev, f"developer missing {key}"


def test_builtin_role_descriptions_are_complete() -> None:
    assert set(BUILT_IN_ROLE_DESCRIPTIONS.keys()) == BUILT_IN_ROLE_NAMES


def test_parse_permission_happy_path() -> None:
    assert parse_permission("flow:execute") == ("flow", "execute")


def test_parse_permission_rejects_bad_shape() -> None:
    for bad in ("no-colon", "too:many:colons", ":missing", "missing:", ": :"):
        with pytest.raises(InvalidPermissionString):
            parse_permission(bad)


def test_parse_permission_rejects_unknown_pair() -> None:
    # Shape is fine, but the key is not in the catalog.
    with pytest.raises(InvalidPermissionString, match="not in the system catalog"):
        parse_permission("flow:teleport")
