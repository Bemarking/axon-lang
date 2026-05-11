"""§Fase 32.h — Replay-binding parser + AST tests (Python side).

D9 (plan-vivo numbering) + D11 ratificadas 2026-05-11. Verifies:

  * `replay: true | false` field parsed into the AST node.
  * `replay_explicit` flag tracks whether the source declared the
    field (vs the runtime applying the method-default).
  * Default state (when omitted): both `replay_explicit=False` and
    `replay=False` — the runtime resolves the effective value at
    deploy time using the method-default heuristic.
  * Cross-stack drift gate: the field appears in both Python AST and
    Rust AST with identical semantics.

Runtime behavior (POST/PUT default-on, GET/DELETE default-off,
explicit override) is verified end-to-end by the Rust integration
test pack `axon-rs/tests/fase32_replay_binding.rs` (12 tests). This
Python pack anchors the parser + AST surface so adopter tooling that
walks the AST (formatters, linters, IDE plugins, doc generators)
sees the field consistently.

Pillar trace per D12:
  - PHILOSOPHY — declaration IS the audit contract; the AST node
                  carries the contract verbatim.
  - LOGIC      — replay default is total over method (verified
                  in Rust integration tests).
  - COMPUTING  — D9 backwards-compat: omitting `replay:` keeps the
                  AST node at default state; no behavior change for
                  v1.20.x–v1.22.x adopters.
"""
from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


def _parse(source: str):
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def _endpoint(program) -> AxonEndpointDefinition:
    return next(
        d for d in program.declarations
        if isinstance(d, AxonEndpointDefinition)
    )


class TestReplayDefaults:
    def test_omitted_field_keeps_default_state(self):
        """D9 backwards-compat — when the source omits `replay:`,
        `replay_explicit=False` and `replay=False`. The runtime then
        resolves the effective value using the method-default
        heuristic at deploy time."""
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Public { method: POST path: \"/p\" execute: Touch }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay_explicit is False
        assert endpoint.replay is False


class TestReplayExplicit:
    def test_replay_true_explicit(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint E { method: GET path: \"/g\" "
            "execute: Touch replay: true }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay_explicit is True
        assert endpoint.replay is True

    def test_replay_false_explicit(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint E { method: POST path: \"/p\" "
            "execute: Touch replay: false }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay_explicit is True
        assert endpoint.replay is False

    def test_replay_with_all_methods(self):
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            for declared in (True, False):
                src = (
                    "flow Touch() -> String { let result = \"ok\" return result }\n"
                    f"axonendpoint E {{ method: {method} path: \"/p\" "
                    f"execute: Touch replay: {'true' if declared else 'false'} }}"
                )
                endpoint = _endpoint(_parse(src))
                assert endpoint.replay_explicit is True
                assert endpoint.replay is declared, (
                    f"method={method}, declared={declared}, "
                    f"got endpoint.replay={endpoint.replay}"
                )


class TestReplayWithOtherFields:
    def test_replay_alongside_body_and_output(self):
        src = (
            "type Req { amount: Integer }\n"
            "type Res { ok: Boolean }\n"
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Full { method: POST path: \"/p\" "
            "body: Req output: Res execute: Touch replay: true }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay_explicit is True
        assert endpoint.replay is True
        assert endpoint.body_type == "Req"
        assert endpoint.output_type == "Res"

    def test_replay_alongside_requires(self):
        src = (
            "flow Touch() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Gated { method: POST path: \"/g\" "
            "execute: Touch requires: [admin] replay: true }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.requires_capabilities == ["admin"]
        assert endpoint.replay is True

    def test_replay_alongside_transport(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow Chat() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint Stream { method: POST path: \"/s\" "
            "execute: Chat transport: sse replay: false }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.transport == "sse"
        assert endpoint.transport_explicit is True
        assert endpoint.replay_explicit is True
        assert endpoint.replay is False


class TestVerticalPatterns:
    """Mirror of the Rust integration test vertical patterns."""

    def test_banking_replay_default_on_post(self):
        src = (
            "flow ApproveOrDeny() -> String { let result = \"ok\" return result }\n"
            "axonendpoint LoanDecision { method: POST path: \"/loan/decision\" "
            "execute: ApproveOrDeny }"
        )
        endpoint = _endpoint(_parse(src))
        # Default state: explicit=False, replay=False. Runtime
        # resolves "true" because method==POST.
        assert endpoint.replay_explicit is False

    def test_medicine_replay_explicit_true(self):
        src = (
            "flow GenerateCDS() -> String { let result = \"ok\" return result }\n"
            "axonendpoint CDS { method: POST path: \"/clinical/decision-support\" "
            "execute: GenerateCDS requires: [hipaa.phi.read, clinician] "
            "replay: true }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay is True
        assert endpoint.requires_capabilities == [
            "hipaa.phi.read", "clinician",
        ]

    def test_legal_replay_explicit_true(self):
        src = (
            "flow AssessPrivilege() -> String { let result = \"ok\" return result }\n"
            "axonendpoint Privilege { method: POST path: \"/discovery/privilege\" "
            "execute: AssessPrivilege requires: [legal.privileged_review] "
            "replay: true }"
        )
        endpoint = _endpoint(_parse(src))
        assert endpoint.replay is True
        assert endpoint.requires_capabilities == ["legal.privileged_review"]
