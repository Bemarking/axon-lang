"""SAML SP Metadata — deterministic XML generator.

Pure-Python, no xmlsec dependency. Emits the Service Provider
metadata XML every enterprise IdP expects when a tenant first
registers the integration. Sorted attributes + stable namespace
prefixes → identical bytes across Python versions and re-generations,
useful for audit comparison.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from xml.etree import ElementTree as ET

# SAML 2.0 namespaces
_NS_MD = "urn:oasis:names:tc:SAML:2.0:metadata"
_NS_DS = "http://www.w3.org/2000/09/xmldsig#"
_NS_SAML = "urn:oasis:names:tc:SAML:2.0:assertion"

ET.register_namespace("md", _NS_MD)
ET.register_namespace("ds", _NS_DS)
ET.register_namespace("saml", _NS_SAML)


@dataclass(frozen=True)
class SpMetadataInput:
    """Inputs needed to emit the SP metadata document."""

    entity_id: str              # sp_entity_id
    acs_url: str                # Assertion Consumer Service endpoint
    slo_url: str | None = None  # Single Logout Service (optional)
    x509_cert_pem: str | None = None  # SP signing / encryption certificate
    organisation_name: str = "Axon Enterprise"
    organisation_url: str = "https://bemarking.com"
    contact_email: str = "support@bemarking.com.co"


def build_sp_metadata_xml(inp: SpMetadataInput) -> str:
    """Return a standards-compliant SP metadata XML string."""
    root = ET.Element(
        f"{{{_NS_MD}}}EntityDescriptor",
        attrib={"entityID": inp.entity_id},
    )

    sp_sso = ET.SubElement(
        root,
        f"{{{_NS_MD}}}SPSSODescriptor",
        attrib={
            "AuthnRequestsSigned": "true" if inp.x509_cert_pem else "false",
            "WantAssertionsSigned": "true",
            "protocolSupportEnumeration": "urn:oasis:names:tc:SAML:2.0:protocol",
        },
    )

    if inp.x509_cert_pem:
        for use in ("signing", "encryption"):
            key_desc = ET.SubElement(
                sp_sso, f"{{{_NS_MD}}}KeyDescriptor", attrib={"use": use}
            )
            key_info = ET.SubElement(key_desc, f"{{{_NS_DS}}}KeyInfo")
            x509_data = ET.SubElement(key_info, f"{{{_NS_DS}}}X509Data")
            x509_cert = ET.SubElement(x509_data, f"{{{_NS_DS}}}X509Certificate")
            x509_cert.text = _strip_pem(inp.x509_cert_pem)

    if inp.slo_url:
        ET.SubElement(
            sp_sso,
            f"{{{_NS_MD}}}SingleLogoutService",
            attrib={
                "Binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                "Location": inp.slo_url,
            },
        )

    ET.SubElement(
        sp_sso,
        f"{{{_NS_MD}}}NameIDFormat",
    ).text = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

    ET.SubElement(
        sp_sso,
        f"{{{_NS_MD}}}AssertionConsumerService",
        attrib={
            "Binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            "Location": inp.acs_url,
            "index": "0",
            "isDefault": "true",
        },
    )

    # Organization
    org = ET.SubElement(root, f"{{{_NS_MD}}}Organization")
    ET.SubElement(
        org,
        f"{{{_NS_MD}}}OrganizationName",
        attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en"},
    ).text = inp.organisation_name
    ET.SubElement(
        org,
        f"{{{_NS_MD}}}OrganizationDisplayName",
        attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en"},
    ).text = inp.organisation_name
    ET.SubElement(
        org,
        f"{{{_NS_MD}}}OrganizationURL",
        attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en"},
    ).text = inp.organisation_url

    # Contact
    contact = ET.SubElement(
        root,
        f"{{{_NS_MD}}}ContactPerson",
        attrib={"contactType": "technical"},
    )
    ET.SubElement(contact, f"{{{_NS_MD}}}EmailAddress").text = inp.contact_email

    # Emit
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    # ET.tostring doesn't always emit the declaration; prepend if missing.
    if not xml.lstrip().startswith("<?xml"):
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    return xml


def _strip_pem(pem: str) -> str:
    """Return only the base64 body of a PEM-armoured certificate."""
    body_lines = [
        line.strip()
        for line in pem.strip().splitlines()
        if not line.startswith("-----")
    ]
    body = "".join(body_lines)
    # Validate it's base64 so we don't emit garbage.
    try:
        base64.b64decode(body)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid PEM body: {exc}") from exc
    return body
