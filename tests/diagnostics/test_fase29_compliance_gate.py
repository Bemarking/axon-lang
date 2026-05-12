"""§Fase 29.f — Tests for the CI compliance gate.

Three layers under test:

  1. **Pure verdict logic** (``gate.evaluate``) — exhaustive over
     thresholds + payload shapes + closed-catalog verdicts.
  2. **CLI argv + env-var contract** — Typer `CliRunner` exercises
     the subcommand surface end-to-end.
  3. **HTTP integration** — runs against a Starlette in-process
     mock of `/api/v1/tenant/diagnostics/recent`, exercising the
     end-to-end flow CLI → httpx → dashboard handler → verdict.

D-letter pins:
  * D4 — output NEVER carries source text (forbidden-key disjointness).
  * D5 — verdict logic operates AFTER axon-lang runs; CLI never
    invokes the parser.
  * D9 — generic tenants pass trivially.
  * Q5 — composite-action shape (verified in the YAML lint test).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from axon_enterprise.cli.diagnostics import _parse_since
from axon_enterprise.cli.diagnostics import app as diagnostics_app
from axon_enterprise.diagnostics.gate import (
    GateConfig,
    GateResult,
    GateVerdict,
    SeverityCounts,
    evaluate,
    format_summary,
)


# ──────────────────────────────────────────────────────────────────
#  §1 — Pure verdict logic (no HTTP)
# ──────────────────────────────────────────────────────────────────


def _payload(
    *,
    mode: str = "aggregated",
    entries: list[dict[str, Any]] | None = None,
    tenant_id: str | None = "clinic-x",
    vertical: str | None = "hipaa",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "vertical": vertical,
        "mode": mode,
        "limit": 50,
        "entries": entries or [],
    }


# ── §1.1 — Closed verdict catalog


def test_gate_verdict_catalog_has_three_variants() -> None:
    assert set(GateVerdict) == {
        GateVerdict.PASS,
        GateVerdict.FAIL_EXCEEDED,
        GateVerdict.FAIL_INPUT,
    }


def test_exit_code_projection_closed_mapping() -> None:
    """Closed mapping: PASS=0, FAIL_EXCEEDED=1, FAIL_INPUT=2."""
    for verdict, expected_code in (
        (GateVerdict.PASS, 0),
        (GateVerdict.FAIL_EXCEEDED, 1),
        (GateVerdict.FAIL_INPUT, 2),
    ):
        result = GateResult(
            verdict=verdict,
            counts=SeverityCounts(),
            reason="",
        )
        assert result.exit_code == expected_code


# ── §1.2 — PASS path


def test_pass_when_empty_entries() -> None:
    result = evaluate(_payload(entries=[]))
    assert result.verdict is GateVerdict.PASS
    assert result.exit_code == 0
    assert result.counts.total == 0


def test_pass_aggregated_below_threshold() -> None:
    """Aggregated entries count as errors; threshold respected."""
    result = evaluate(
        _payload(entries=[{"count": 2, "code": "AX-0001"}]),
        config=GateConfig(max_errors=5),
    )
    assert result.verdict is GateVerdict.PASS
    assert result.counts.errors == 2


def test_pass_raw_below_threshold() -> None:
    result = evaluate(
        _payload(
            mode="raw",
            entries=[{"severity": "error", "code": "AX-1"}],
        ),
        config=GateConfig(max_errors=3),
    )
    assert result.verdict is GateVerdict.PASS
    assert result.counts.errors == 1


# ── §1.3 — FAIL_EXCEEDED on error threshold


def test_fail_when_errors_exceed_default_threshold() -> None:
    """Default max_errors=0; any error fails the gate."""
    result = evaluate(
        _payload(entries=[{"count": 1, "code": "AX-0001"}]),
    )
    assert result.verdict is GateVerdict.FAIL_EXCEEDED
    assert result.exit_code == 1
    assert result.threshold_breached == "errors"


def test_fail_when_aggregated_count_exceeds_threshold() -> None:
    result = evaluate(
        _payload(
            entries=[
                {"count": 3, "code": "AX-0001"},
                {"count": 4, "code": "AX-0002"},
            ]
        ),
        config=GateConfig(max_errors=5),
    )
    assert result.verdict is GateVerdict.FAIL_EXCEEDED
    assert result.counts.errors == 7
    assert result.threshold_breached == "errors"


# ── §1.4 — FAIL_EXCEEDED on warning threshold (raw mode only)


def test_fail_when_warnings_exceed_threshold_raw_mode() -> None:
    entries = [
        {"severity": "warning", "code": "AX-W001"},
        {"severity": "warning", "code": "AX-W002"},
    ]
    result = evaluate(
        _payload(mode="raw", entries=entries),
        config=GateConfig(max_warnings=1),
    )
    assert result.verdict is GateVerdict.FAIL_EXCEEDED
    assert result.threshold_breached == "warnings"


def test_pass_when_max_warnings_unset_ignores_warnings() -> None:
    entries = [{"severity": "warning", "code": f"AX-W{i}"} for i in range(10)]
    result = evaluate(
        _payload(mode="raw", entries=entries),
        config=GateConfig(max_warnings=None),
    )
    assert result.verdict is GateVerdict.PASS


# ── §1.5 — fail_on_hint


def test_fail_on_hint_triggers_when_hint_present() -> None:
    entries = [{"severity": "hint", "code": "AX-H001"}]
    result = evaluate(
        _payload(mode="raw", entries=entries),
        config=GateConfig(fail_on_hint=True),
    )
    assert result.verdict is GateVerdict.FAIL_EXCEEDED
    assert result.threshold_breached == "hints"


def test_fail_on_hint_default_false() -> None:
    entries = [{"severity": "hint", "code": "AX-H001"}]
    result = evaluate(_payload(mode="raw", entries=entries))
    assert result.verdict is GateVerdict.PASS


# ── §1.6 — FAIL_INPUT (malformed payloads)


def test_fail_input_when_payload_not_a_dict() -> None:
    result = evaluate([1, 2, 3])  # type: ignore[arg-type]
    assert result.verdict is GateVerdict.FAIL_INPUT
    assert result.exit_code == 2


def test_fail_input_when_mode_missing() -> None:
    result = evaluate({"entries": []})
    assert result.verdict is GateVerdict.FAIL_INPUT


def test_fail_input_when_mode_invalid() -> None:
    result = evaluate({"mode": "bogus", "entries": []})
    assert result.verdict is GateVerdict.FAIL_INPUT


def test_fail_input_when_entries_not_a_list() -> None:
    result = evaluate({"mode": "raw", "entries": "not-a-list"})
    assert result.verdict is GateVerdict.FAIL_INPUT


def test_fail_input_when_required_mode_mismatch() -> None:
    """Explicit require_mode mismatch → FAIL_INPUT."""
    result = evaluate(
        _payload(mode="aggregated"),
        config=GateConfig(require_mode="raw"),
    )
    assert result.verdict is GateVerdict.FAIL_INPUT


# ── §1.7 — D4 privacy: result has no source field


def test_result_carries_no_source_text_field() -> None:
    forbidden = {"source", "snippet", "content", "text", "body", "excerpt"}
    field_names = set(GateResult.__dataclass_fields__)
    assert field_names.isdisjoint(forbidden)


# ── §1.8 — Severity counts arithmetic


def test_severity_counts_total_is_sum() -> None:
    counts = SeverityCounts(errors=3, warnings=2, hints=1, unknown=4)
    assert counts.total == 10


def test_severity_counts_default_zero() -> None:
    counts = SeverityCounts()
    assert counts.total == 0


# ── §1.9 — Unknown severity counted toward "unknown" (raw mode)


def test_unknown_severity_counted_separately() -> None:
    entries = [{"severity": "panic", "code": "AX-0001"}]
    result = evaluate(_payload(mode="raw", entries=entries))
    assert result.counts.unknown == 1
    # Doesn't trigger error threshold.
    assert result.verdict is GateVerdict.PASS


# ── §1.10 — Aggregated count field robustness


def test_aggregated_count_non_numeric_silently_zero() -> None:
    """A malformed aggregated entry with non-numeric count is
    counted as 0 — defensive parsing, no crash."""
    entries = [
        {"count": "not-a-number", "code": "AX-0001"},
        {"count": 3, "code": "AX-0002"},
    ]
    result = evaluate(_payload(entries=entries), config=GateConfig(max_errors=5))
    # Only the valid count contributes.
    assert result.counts.errors == 3


def test_aggregated_negative_count_clamped_to_zero() -> None:
    """Negative count is treated as 0 (defensive)."""
    entries = [{"count": -5, "code": "AX-0001"}]
    result = evaluate(_payload(entries=entries))
    assert result.counts.errors == 0
    assert result.verdict is GateVerdict.PASS


# ── §1.11 — format_summary


def test_format_summary_has_no_source_text() -> None:
    """Summary output is plain-text + carries no source content."""
    result = GateResult(
        verdict=GateVerdict.PASS,
        counts=SeverityCounts(errors=0),
        reason="all clear",
        tenant_id="clinic-x",
        vertical="hipaa",
        mode="aggregated",
    )
    summary = format_summary(result)
    # Doesn't leak any source-text-shaped content.
    for forbidden in ("def ", "class ", "import ", "function "):
        # These are markers of leaked code; permissive heuristic.
        # The summary is fully structured + has none of these.
        assert forbidden not in summary
    # Required keys present.
    assert "tenant_id: clinic-x" in summary
    assert "vertical:  hipaa" in summary
    assert "mode:      aggregated" in summary
    assert "PASS" in summary


def test_format_summary_with_breach_includes_breach_field() -> None:
    result = GateResult(
        verdict=GateVerdict.FAIL_EXCEEDED,
        counts=SeverityCounts(errors=3),
        reason="errors=3 exceeds threshold max_errors=0",
        threshold_breached="errors",
    )
    summary = format_summary(result)
    assert "breached_threshold: errors" in summary


# ──────────────────────────────────────────────────────────────────
#  §2 — `_parse_since` duration + ISO parser
# ──────────────────────────────────────────────────────────────────


def test_parse_since_none_returns_none() -> None:
    assert _parse_since(None) is None
    assert _parse_since("") is None


def test_parse_since_iso_round_trips() -> None:
    raw = "2026-05-12T10:00:00+00:00"
    dt = _parse_since(raw)
    assert dt is not None
    assert dt == datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_since_iso_z_suffix_accepted() -> None:
    dt = _parse_since("2026-05-12T10:00:00Z")
    assert dt == datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_since_naive_iso_assumed_utc() -> None:
    dt = _parse_since("2026-05-12T10:00:00")
    assert dt == datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_since_relative_minutes() -> None:
    before = datetime.now(timezone.utc)
    dt = _parse_since("30m")
    after = datetime.now(timezone.utc)
    assert dt is not None
    # dt is approximately 30 minutes ago, within a one-second window.
    expected_lower = before - timedelta(minutes=30, seconds=1)
    expected_upper = after - timedelta(minutes=30) + timedelta(seconds=1)
    assert expected_lower <= dt <= expected_upper


def test_parse_since_relative_hours_days_seconds() -> None:
    """All four units {s, m, h, d} accepted."""
    for raw in ("60s", "1h", "1d"):
        dt = _parse_since(raw)
        assert dt is not None


def test_parse_since_unknown_unit_raises() -> None:
    with pytest.raises(ValueError):
        _parse_since("30y")


def test_parse_since_negative_duration_raises() -> None:
    with pytest.raises(ValueError):
        _parse_since("-30m")


def test_parse_since_malformed_raises() -> None:
    with pytest.raises(ValueError):
        _parse_since("not-a-time")


# ──────────────────────────────────────────────────────────────────
#  §3 — CLI integration via Typer CliRunner
# ──────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_help_exits_zero(runner: CliRunner) -> None:
    # Force a wide pseudo-terminal so Rich/Click never wraps the long
    # `--max-errors` flag mid-name; strip ANSI escapes before the
    # substring check so styled help output still passes on CI where
    # the renderer emits colour codes by default.
    import re as _re

    result = runner.invoke(
        diagnostics_app,
        ["gate", "--help"],
        env={"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    plain = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout)
    plain = plain.replace("\n", " ").replace("  ", " ")
    assert "max-errors" in plain, (
        f"help output missing --max-errors flag; got:\n{result.stdout}"
    )


def test_cli_missing_endpoint_exits_2(runner: CliRunner) -> None:
    """No --endpoint + no AXON_ENTERPRISE_ENDPOINT → exit 2."""
    result = runner.invoke(
        diagnostics_app,
        ["gate", "--token", "fake-jwt"],
        env={"AXON_ENTERPRISE_ENDPOINT": "", "AXON_ENTERPRISE_TOKEN": ""},
    )
    assert result.exit_code == 2
    assert "endpoint" in result.stderr.lower()


def test_cli_missing_token_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(
        diagnostics_app,
        ["gate", "--endpoint", "http://example.com"],
        env={"AXON_ENTERPRISE_ENDPOINT": "", "AXON_ENTERPRISE_TOKEN": ""},
    )
    assert result.exit_code == 2
    assert "token" in result.stderr.lower()


def test_cli_invalid_mode_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(
        diagnostics_app,
        [
            "gate",
            "--endpoint",
            "http://example.com",
            "--token",
            "fake",
            "--mode",
            "bogus",
        ],
    )
    assert result.exit_code == 2


def test_cli_malformed_since_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(
        diagnostics_app,
        [
            "gate",
            "--endpoint",
            "http://example.com",
            "--token",
            "fake",
            "--since",
            "30y",
        ],
    )
    assert result.exit_code == 2


def test_cli_env_var_endpoint_and_token_picked_up(runner: CliRunner) -> None:
    """When --endpoint / --token are not passed but env vars are set,
    the CLI proceeds to the HTTP fetch (and then fails at transport
    because the URL is unreachable — exit 2 expected).
    """
    result = runner.invoke(
        diagnostics_app,
        ["gate"],
        env={
            "AXON_ENTERPRISE_ENDPOINT": "http://127.0.0.1:1",
            "AXON_ENTERPRISE_TOKEN": "fake",
        },
    )
    # Exit 2 because of transport failure (unreachable port 1) —
    # confirms env vars were picked up + the CLI proceeded past
    # the validation gate.
    assert result.exit_code == 2
    # The error message should reflect transport, not config.
    assert "transport" in result.stderr.lower() or "connect" in result.stderr.lower()


# ──────────────────────────────────────────────────────────────────
#  §4 — HTTP integration against in-process mock dashboard
# ──────────────────────────────────────────────────────────────────


class _FetchOutcome:
    """Test double that the patched ``_fetch_payload`` returns or
    raises. Lets E2E tests pin the CLI's behavior across the verdict
    pipeline without spinning up a real HTTP server (the transport
    layer itself is covered by §6 below against ``httpx.MockTransport``).
    """

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.raise_exc = raise_exc


def _run_gate_with_fetch(
    outcome: _FetchOutcome,
    *,
    args: list[str],
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run the CLI gate against a stubbed ``_fetch_payload`` outcome.
    Returns ``(exit_code, stdout, stderr)``.

    The stub replaces ``_fetch_payload`` at the module level via
    direct attribute assignment — Python looks the function up in
    the module's globals at call time, so the patched version wins.
    """
    runner = CliRunner()
    import axon_enterprise.cli.diagnostics as diag_cli

    real_fetch = diag_cli._fetch_payload

    def patched_fetch(**_kwargs: Any) -> dict[str, Any]:
        if outcome.raise_exc is not None:
            raise outcome.raise_exc
        return outcome.payload or {}

    diag_cli._fetch_payload = patched_fetch  # type: ignore[assignment]
    try:
        env = {
            "AXON_ENTERPRISE_ENDPOINT": "http://testserver",
            "AXON_ENTERPRISE_TOKEN": "test-jwt",
        }
        if env_extra:
            env.update(env_extra)
        result = runner.invoke(diagnostics_app, ["gate", *args], env=env)
        return result.exit_code, result.stdout, result.stderr
    finally:
        diag_cli._fetch_payload = real_fetch  # type: ignore[assignment]


def test_e2e_empty_payload_passes() -> None:
    outcome = _FetchOutcome(payload=_payload(entries=[]))
    exit_code, stdout, _stderr = _run_gate_with_fetch(outcome, args=[])
    assert exit_code == 0
    assert "PASS" in stdout


def test_e2e_payload_with_errors_fails_with_exit_1() -> None:
    outcome = _FetchOutcome(
        payload=_payload(entries=[{"count": 3, "code": "AX-0001"}])
    )
    exit_code, stdout, _stderr = _run_gate_with_fetch(outcome, args=[])
    assert exit_code == 1
    assert "FAIL_EXCEEDED" in stdout


def test_e2e_max_errors_threshold_respected() -> None:
    outcome = _FetchOutcome(
        payload=_payload(entries=[{"count": 5, "code": "AX-0001"}])
    )
    # 5 errors > max_errors=10 is False → PASS.
    exit_code, _stdout, _stderr = _run_gate_with_fetch(
        outcome, args=["--max-errors", "10"]
    )
    assert exit_code == 0
    # 5 errors > max_errors=3 → FAIL.
    exit_code, _stdout, _stderr = _run_gate_with_fetch(
        outcome, args=["--max-errors", "3"]
    )
    assert exit_code == 1


def test_e2e_json_output_machine_readable() -> None:
    outcome = _FetchOutcome(
        payload=_payload(entries=[{"count": 2, "code": "AX-0001"}])
    )
    exit_code, stdout, _stderr = _run_gate_with_fetch(
        outcome, args=["--max-errors", "10", "--json"]
    )
    assert exit_code == 0
    data = json.loads(stdout.strip())
    assert data["verdict"] == "pass"
    assert data["counts"]["errors"] == 2
    assert data["tenant_id"] == "clinic-x"
    assert data["vertical"] == "hipaa"


def test_e2e_server_500_exits_2() -> None:
    """A non-200 HTTP response is bubbled up by ``_fetch_payload`` as
    :class:`httpx.HTTPStatusError`; the CLI maps it to exit 2.
    """
    fake_request = httpx.Request("GET", "http://testserver/x")
    fake_response = httpx.Response(500, request=fake_request)
    outcome = _FetchOutcome(
        raise_exc=httpx.HTTPStatusError(
            "synthetic 500", request=fake_request, response=fake_response
        )
    )
    exit_code, _stdout, stderr = _run_gate_with_fetch(outcome, args=[])
    assert exit_code == 2
    assert "500" in stderr or "transport" in stderr.lower()


def test_e2e_d8_response_carries_no_source_text() -> None:
    """End-to-end D4 pin: even when the server (hypothetically) leaks
    source content, the gate's stdout summary NEVER prints it.

    The gate reads only structural fields; non-declared fields are
    ignored at the projection layer.
    """
    leaky_payload = _payload(
        mode="raw",
        entries=[
            {
                "severity": "error",
                "code": "AX-0001",
                "file_path": "src/x.axon",
                "line": 1,
                "column": 1,
                # Hypothetical leak vector (the dashboard does NOT
                # do this, but the gate must be robust):
                "source": "secret_password_123",
                "snippet": "internal API key xyz",
            }
        ],
    )
    outcome = _FetchOutcome(payload=leaky_payload)
    exit_code, stdout, _stderr = _run_gate_with_fetch(
        outcome, args=["--mode", "raw"]
    )
    # Verdict still computed correctly.
    assert exit_code == 1
    # Source text NEVER reaches stdout.
    assert "secret_password_123" not in stdout
    assert "internal API key" not in stdout


# ──────────────────────────────────────────────────────────────────
#  §6 — Transport layer: `_fetch_payload` against httpx.MockTransport
# ──────────────────────────────────────────────────────────────────
#
# The §4 e2e tests stub `_fetch_payload` to isolate verdict logic
# from HTTP. This section exercises the transport layer DIRECTLY
# using `httpx.MockTransport` (sync handler) so the real
# `_fetch_payload` is hit + we still avoid spinning up a real HTTP
# server.


def _mock_transport_handler(
    *,
    payload: dict[str, Any] | None = None,
    status_code: int = 200,
):
    """Build a sync httpx mock-transport handler returning ``payload``."""

    body = payload if payload is not None else _payload(entries=[])

    def _handler(request: httpx.Request) -> httpx.Response:
        # Sanity: the CLI MUST send a Bearer token.
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            return httpx.Response(401, json={"error": "no bearer"})
        return httpx.Response(status_code, json=body)

    return _handler


def test_fetch_payload_round_trip_via_mock_transport() -> None:
    """The real ``_fetch_payload`` issues a GET that the mock
    transport handles. Verifies URL composition + auth header +
    JSON decode path.
    """
    from axon_enterprise.cli.diagnostics import _fetch_payload

    transport = httpx.MockTransport(_mock_transport_handler(payload=_payload()))
    with httpx.Client(transport=transport) as client:
        payload = _fetch_payload(
            endpoint="http://testserver",
            token="test-jwt",
            since=None,
            limit=50,
            mode="aggregated",
            file_path=None,
            code=None,
            bucket_size=10,
            timeout=5.0,
            client=client,
        )
    assert payload["tenant_id"] == "clinic-x"
    assert payload["mode"] == "aggregated"


def test_fetch_payload_non_200_raises_http_status_error() -> None:
    """Non-2xx responses bubble up as :class:`httpx.HTTPStatusError`
    which the CLI's outer handler maps to exit 2.
    """
    from axon_enterprise.cli.diagnostics import _fetch_payload

    transport = httpx.MockTransport(_mock_transport_handler(status_code=500))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            _fetch_payload(
                endpoint="http://testserver",
                token="t",
                since=None,
                limit=50,
                mode="aggregated",
                file_path=None,
                code=None,
                bucket_size=10,
                timeout=5.0,
                client=client,
            )


def test_fetch_payload_passes_since_filter_and_token() -> None:
    """Verifies the URL query string carries `since` + `Authorization`
    header carries the bearer token. Catches header / param drift.
    """
    from axon_enterprise.cli.diagnostics import _fetch_payload

    seen_url: dict[str, Any] = {}
    seen_headers: dict[str, str] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_url["url"] = str(request.url)
        seen_headers["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=_payload(entries=[]))

    transport = httpx.MockTransport(_handler)
    since = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    with httpx.Client(transport=transport) as client:
        _fetch_payload(
            endpoint="http://testserver/",  # trailing slash stripped
            token="my-jwt-token",
            since=since,
            limit=42,
            mode="raw",
            file_path="src/x.axon",
            code="AX-0001",
            bucket_size=25,
            timeout=5.0,
            client=client,
        )
    # URL composition: endpoint trailing slash + canonical path.
    assert "/api/v1/tenant/diagnostics/recent" in seen_url["url"]
    # Query params present + correctly encoded.
    assert "since=2026-05-12T10" in seen_url["url"]
    assert "limit=42" in seen_url["url"]
    assert "aggregated=false" in seen_url["url"]  # raw mode
    assert "file_path=src" in seen_url["url"]
    assert "code=AX-0001" in seen_url["url"]
    # Bearer auth header present.
    assert seen_headers["auth"] == "Bearer my-jwt-token"


# ──────────────────────────────────────────────────────────────────
#  §5 — Composite-action YAML lint (Q5)
# ──────────────────────────────────────────────────────────────────


def _action_yaml_path() -> Path:
    # The composite action lives at the repo root, NOT inside the
    # axon_enterprise package — adopters reference it via
    # `Bemarking/axon-enterprise@vX.Y.Z` in their workflow.
    return Path(__file__).resolve().parents[2] / ".github" / "actions" / "axon-enterprise-ci-gate" / "action.yml"


def test_composite_action_yaml_exists() -> None:
    """Q5 ratificada — wrap as composite action (file present + valid)."""
    path = _action_yaml_path()
    assert path.exists(), f"composite action file missing at {path}"


def test_composite_action_yaml_parses() -> None:
    """YAML lint: the action must parse + carry the required keys."""
    import yaml

    path = _action_yaml_path()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    assert data.get("name")
    assert data.get("description")
    assert data.get("inputs"), "action must declare inputs"
    runs = data.get("runs")
    assert isinstance(runs, dict)
    assert runs.get("using") == "composite", "Q5 — must be a composite action"
    steps = runs.get("steps")
    assert isinstance(steps, list) and len(steps) >= 1


def test_composite_action_declares_required_inputs() -> None:
    """Every input the CLI accepts must be declarable from the action
    surface (otherwise adopters can't pass it through)."""
    import yaml

    path = _action_yaml_path()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    inputs = data["inputs"]
    # Required: endpoint + token. Optional: thresholds.
    assert "endpoint" in inputs
    assert "token" in inputs
    # Sanity: token input should NOT have a default (must be a secret).
    assert "default" not in inputs["token"] or inputs["token"]["default"] == ""


def test_composite_action_steps_invoke_diagnostics_gate() -> None:
    """The composite action MUST call the gate subcommand on its
    primary step.
    """
    import yaml

    path = _action_yaml_path()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    steps = data["runs"]["steps"]
    # Find at least one step that mentions the gate subcommand.
    matched = False
    for step in steps:
        run_text = step.get("run", "")
        if "axon-enterprise diagnostics gate" in run_text:
            matched = True
            break
    assert matched, "no composite-action step invokes `axon-enterprise diagnostics gate`"
