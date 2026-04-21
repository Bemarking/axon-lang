"""Unit tests for SP metadata generator."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from axon_enterprise.sso.saml_metadata import (
    SpMetadataInput,
    build_sp_metadata_xml,
)

_DUMMY_CERT = """\
-----BEGIN CERTIFICATE-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAnCGfhXgLCRfVv8VlV4MmuA4
s4MnXWq5n3/HEzPyKAapzMzLd3eO8V9SL4z+JJghJYc9e7cvsNMvmiyPGffVv8ubm8G
RGJo0bfe4X0Fc0tFZGxRKxR8tCqSSqf9w/dtz/u4Zb5bGBzH97z9ajMcNN8I9PhA
-----END CERTIFICATE-----
"""


def _parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_builds_valid_xml_without_cert() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test/metadata",
        acs_url="https://sp.test/acs",
    )
    xml = build_sp_metadata_xml(inp)
    root = _parse(xml)
    assert root.tag.endswith("EntityDescriptor")
    assert root.get("entityID") == "https://sp.test/metadata"


def test_acs_url_is_present() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test", acs_url="https://sp.test/acs"
    )
    xml = build_sp_metadata_xml(inp)
    assert "https://sp.test/acs" in xml


def test_with_cert_includes_key_descriptor() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test",
        acs_url="https://sp.test/acs",
        x509_cert_pem=_DUMMY_CERT,
    )
    xml = build_sp_metadata_xml(inp)
    assert "KeyDescriptor" in xml
    # Both signing + encryption descriptors present.
    assert xml.count("KeyDescriptor") >= 4  # open + close tags
    assert 'use="signing"' in xml
    assert 'use="encryption"' in xml


def test_malformed_pem_rejected() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test",
        acs_url="https://sp.test/acs",
        x509_cert_pem="-----BEGIN CERTIFICATE-----\n!!not-base64!!\n-----END CERTIFICATE-----",
    )
    with pytest.raises(ValueError):
        build_sp_metadata_xml(inp)


def test_slo_url_included_when_provided() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test",
        acs_url="https://sp.test/acs",
        slo_url="https://sp.test/slo",
    )
    xml = build_sp_metadata_xml(inp)
    assert "https://sp.test/slo" in xml
    assert "SingleLogoutService" in xml


def test_output_is_deterministic_across_calls() -> None:
    inp = SpMetadataInput(
        entity_id="https://sp.test",
        acs_url="https://sp.test/acs",
    )
    assert build_sp_metadata_xml(inp) == build_sp_metadata_xml(inp)
