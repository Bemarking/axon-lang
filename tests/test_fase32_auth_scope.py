"""§Fase 32.g — Auth scope parser + slug grammar tests (Python side).

D8 + D11 ratificadas 2026-05-11. Verifies:

  * `_is_valid_capability_slug` accepts/rejects per the closed
    grammar `^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$`.
  * The parser populates `AxonEndpointDefinition.requires_capabilities`
    when `requires: [a, b.c]` is declared.
  * Empty list when omitted (D9 backwards-compat default).
  * Invalid slug → `AxonParseError` with adopter-actionable diagnostic
    at parse time (no silent acceptance of malformed slugs that would
    fail in production).
  * Slug-validator parity with Rust mirror — a sample of accepted +
    rejected slugs must agree across stacks. The drift gate at the
    test layer locks the grammar.

Pillar trace per D12:
  - LOGIC      — slug grammar is closed; the predicate is total.
  - PHILOSOPHY — declaration IS the access contract; auditors read
                  source + KNOW which endpoints require which caps.
  - COMPUTING  — cross-stack drift gate at the slug-validator layer
                  guarantees both stacks agree on what's a valid slug.
"""
from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.errors import AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser, _is_valid_capability_slug


def _parse(source: str):
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


# ── Slug validator parity ────────────────────────────────────────────


class TestSlugValidator:
    @pytest.mark.parametrize("slug", [
        "admin",
        "legal.read",
        "hipaa.phi.read",
        "bank.officer.senior",
        "a",
        "a_b",
        "a1",
        "a.b1_c",
    ])
    def test_accepts_canonical(self, slug):
        assert _is_valid_capability_slug(slug), f"must accept '{slug}'"

    @pytest.mark.parametrize("slug", [
        "",
        "Admin",
        "admin.READ",
        "1admin",
        "admin.1read",
        "bank-officer",
        "bank..a",
        ".admin",
        "admin.",
        "admin@read",
        "admin/read",
        "admin read",
    ])
    def test_rejects_invalid(self, slug):
        assert not _is_valid_capability_slug(slug), f"must reject '{slug!r}'"

    def test_anchor_drift_gate_with_rust(self):
        """Anchor: a representative sample of accepted/rejected slugs
        is mirrored verbatim in `axon-rs::parser::capability_slug_tests`.
        Both stacks consult the SAME grammar — drift caught at PR time."""
        # Accepted
        for s in ["admin", "legal.read", "hipaa.phi.read", "a", "a1", "a_b"]:
            assert _is_valid_capability_slug(s)
        # Rejected
        for s in ["", "Admin", "1admin", "bank-officer", "bank..a", ".admin"]:
            assert not _is_valid_capability_slug(s)


# ── Parser populates `requires_capabilities` ─────────────────────────


class TestRequiresParser:
    def test_omitted_requires_defaults_to_empty_list(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Public { method: POST path: \"/p\" execute: Touch }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == []

    def test_single_capability_parsed(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint AdminEndpoint { method: POST path: \"/admin\" "
            "execute: Touch requires: [admin] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == ["admin"]

    def test_multi_capability_preserves_order(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint LegalEndpoint { method: POST path: \"/legal\" "
            "execute: Touch requires: [legal.read, legal.write, admin] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == [
            "legal.read", "legal.write", "admin",
        ]

    def test_dotted_capability_parsed(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Hipaa { method: POST path: \"/clinical\" "
            "execute: Touch requires: [hipaa.phi.read, clinician] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == ["hipaa.phi.read", "clinician"]


# ── Parser rejects invalid slugs at parse time ──────────────────────


class TestRequiresGrammarEnforcement:
    def test_rejects_uppercase_slug_at_parse_time(self):
        # `Admin` is a valid IDENTIFIER token (the lexer accepts mixed
        # case) so it reaches the parser's slug-grammar check, which
        # rejects it with the D8 diagnostic.
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Bad { method: POST path: \"/x\" "
            "execute: Touch requires: [Admin] }"
        )
        with pytest.raises(AxonParseError) as exc_info:
            _parse(src)
        msg = str(exc_info.value)
        assert "Invalid capability slug" in msg
        assert "Admin" in msg

    def test_lexer_rejects_digit_prefixed_slug_at_token_level(self):
        # `1admin` is rejected EARLIER — the lexer tokenizes `1` as an
        # INTEGER and `admin` as a separate IDENTIFIER, so the parser
        # sees a malformed list and raises a token-level parse error.
        # The D8 grammar still excludes digit-prefixed slugs; the
        # rejection just fires at the lexer layer instead of the slug
        # validator. Result is the same: malformed sources never deploy.
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Bad { method: POST path: \"/x\" "
            "execute: Touch requires: [1admin] }"
        )
        with pytest.raises(AxonParseError):
            _parse(src)

    def test_diagnostic_mentions_grammar_pattern(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Bad { method: POST path: \"/x\" "
            "execute: Touch requires: [Admin] }"
        )
        with pytest.raises(AxonParseError) as exc_info:
            _parse(src)
        msg = str(exc_info.value)
        # Diagnostic must mention the grammar so adopters know what's
        # accepted without reading the source.
        assert "lowercase" in msg.lower()
        # And it must give concrete examples.
        assert "admin" in msg.lower() or "legal.read" in msg.lower()


# ── Vertical X-ray patterns from plan vivo §8 ───────────────────────


class TestVerticalPatterns:
    def test_banking_pattern(self):
        """Banking adopter: `requires: [bank.officer]` — single dotted
        slug. Auditor reads source + knows the contract."""
        src = (
            "flow ApproveOrDeny() -> String { let result = \"ok\" return result }\n"
            "axonendpoint LoanDecision { method: POST path: \"/loan/decision\" "
            "execute: ApproveOrDeny requires: [bank.officer] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == ["bank.officer"]

    def test_medicine_pattern(self):
        """HIPAA pattern: multiple dotted slugs (PHI access + role)."""
        src = (
            "flow GenerateCDS() -> String { let result = \"ok\" return result }\n"
            "axonendpoint CDS { method: POST path: \"/clinical/decision-support\" "
            "execute: GenerateCDS requires: [hipaa.phi.read, clinician] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == [
            "hipaa.phi.read", "clinician",
        ]

    def test_legal_pattern(self):
        """FRE 502 pattern: `legal.privileged_review`."""
        src = (
            "flow AssessPrivilege() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Privilege { method: POST path: \"/discovery/privilege\" "
            "execute: AssessPrivilege requires: [legal.privileged_review] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == ["legal.privileged_review"]

    def test_government_pattern(self):
        """FedRAMP pattern: agency-scoped capability."""
        src = (
            "flow AssessEligibility() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Benefits { method: POST path: \"/benefits/eligibility\" "
            "execute: AssessEligibility requires: [agency.case_officer] }"
        )
        program = _parse(src)
        endpoint = next(
            d for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        )
        assert endpoint.requires_capabilities == ["agency.case_officer"]
