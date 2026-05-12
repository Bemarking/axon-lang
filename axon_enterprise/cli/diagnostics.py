"""``axon-enterprise diagnostics ...`` — Fase 29.f CI compliance gate.

D5 + D9 + Q5 (composite action, not reusable workflow) ratificadas
2026-05-12.

## What this subcommand ships

``axon-enterprise diagnostics gate`` — the CI compliance gate
adopters install in their workflow via the
``.github/actions/axon-enterprise-ci-gate`` composite action (Q5).

Queries ``/api/v1/tenant/diagnostics/recent`` for the authenticated
tenant, applies the configured thresholds, prints a human-readable
summary, exits with a closed exit-code catalog:

==== =============================================================
0    Gate passed — diagnostics ≤ thresholds.
1    Gate failed — diagnostics exceed threshold.
2    Configuration / transport error (auth failure, malformed
     payload, DNS / connect failure, server 5xx).
==== =============================================================

## D-letter trace

- **D5 ratificada** — enforcement at CI integration time, NOT
  inside axon-lang. This CLI lives in axon-enterprise; axon-lang's
  ``axon parse`` contract is unchanged.
- **D9 ratificada** — generic tenants get OSS surface; this CLI is
  opt-in, only adopters who install the composite action use it.
- **D4 ratificada** — output NEVER carries source text (D4
  enforced at the dashboard layer + reaffirmed by the pure
  :mod:`gate` module's :class:`GateResult` having no source field).
- **Q5 ratificada** — wraps as a composite action (not a reusable
  workflow). The composite action calls this CLI as its sole step.

## Env-var contract

Mirrors the existing axon-enterprise integration discipline (Fase
21 — single env var contract, no per-CI handover of internal
infra values):

- ``AXON_ENTERPRISE_ENDPOINT`` — base URL of the enterprise server
  (e.g. ``https://api.example.com``). CLI flag ``--endpoint``
  overrides.
- ``AXON_ENTERPRISE_TOKEN`` — bearer JWT for the authenticated
  tenant. CLI flag ``--token`` overrides. **Adopters MUST NOT
  hard-code this in their workflow file**; pass via
  ``${{ secrets.AXON_ENTERPRISE_TOKEN }}``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import typer

from axon_enterprise.diagnostics.gate import (
    GateConfig,
    GateResult,
    GateVerdict,
    SeverityCounts,
    evaluate,
    format_summary,
)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _diagnostics_callback() -> None:
    """Diagnostics commands — vertical compliance gate + dashboard CLI.

    The callback exists so Typer treats this app as a multi-command
    parent rather than collapsing into a single-command shape (which
    would prevent the `gate` subcommand from being addressable when
    the diagnostics app is invoked directly in tests).
    """


# ──────────────────────────────────────────────────────────────────
#  Env-var contract
# ──────────────────────────────────────────────────────────────────


_ENV_ENDPOINT = "AXON_ENTERPRISE_ENDPOINT"
_ENV_TOKEN = "AXON_ENTERPRISE_TOKEN"

_DEFAULT_PATH = "/api/v1/tenant/diagnostics/recent"
_DEFAULT_TIMEOUT_SECS = 30.0


# ──────────────────────────────────────────────────────────────────
#  Helpers — `since` duration parsing
# ──────────────────────────────────────────────────────────────────


def _parse_since(raw: str | None) -> datetime | None:
    """Parse the ``--since`` flag.

    Two accepted shapes:

    - ISO-8601 timestamp: ``2026-05-12T10:00:00+00:00`` — passed
      verbatim to the dashboard endpoint.
    - Relative duration: ``<N><unit>`` where unit ∈ ``{s, m, h, d}``,
      e.g. ``30m``, ``2h``, ``1d``. Resolved to ``now - duration``
      at CLI invocation time.

    Returns ``None`` for missing input; raises ``ValueError`` on
    malformed input.
    """
    if raw is None or raw == "":
        return None
    raw = raw.strip()

    # Try ISO-8601 first.
    iso_candidate = raw.rstrip("Z")
    if iso_candidate != raw:
        iso_candidate += "+00:00"
    try:
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # Relative duration: <N><unit>.
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if len(raw) >= 2 and raw[-1] in units:
        try:
            n = int(raw[:-1])
        except ValueError as exc:
            raise ValueError(
                f"--since: unparseable duration number in {raw!r}"
            ) from exc
        if n < 0:
            raise ValueError(
                f"--since: relative duration must be non-negative, got {raw!r}"
            )
        delta = timedelta(seconds=n * units[raw[-1]])
        return (datetime.now(timezone.utc) - delta).astimezone(timezone.utc)

    raise ValueError(
        f"--since: not an ISO-8601 timestamp or <N><s|m|h|d> duration: {raw!r}"
    )


# ──────────────────────────────────────────────────────────────────
#  Fetcher — HTTP layer
# ──────────────────────────────────────────────────────────────────


def _fetch_payload(
    *,
    endpoint: str,
    token: str,
    since: datetime | None,
    limit: int,
    mode: str,
    file_path: str | None,
    code: str | None,
    bucket_size: int,
    timeout: float,
    client: httpx.Client | None = None,
) -> dict:
    """Issue the GET request and return the parsed JSON payload.

    Raises :class:`httpx.HTTPError` on transport failure /
    non-2xx response so the CLI's outer exception handler can map
    to exit code 2.
    """
    params: dict[str, str] = {
        "limit": str(limit),
        "aggregated": "true" if mode == "aggregated" else "false",
        "bucket_size": str(bucket_size),
    }
    if since is not None:
        params["since"] = since.isoformat()
    if file_path is not None:
        params["file_path"] = file_path
    if code is not None:
        params["code"] = code

    url = endpoint.rstrip("/") + _DEFAULT_PATH
    headers = {"Authorization": f"Bearer {token}"}

    owned_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owned_client:
            http.close()


# ──────────────────────────────────────────────────────────────────
#  Gate subcommand
# ──────────────────────────────────────────────────────────────────


@app.command("gate")
def gate_command(
    endpoint: str = typer.Option(
        None,
        "--endpoint",
        envvar=_ENV_ENDPOINT,
        help=(
            "Base URL of the axon-enterprise server, e.g. "
            "``https://api.example.com``. Env: ``AXON_ENTERPRISE_ENDPOINT``."
        ),
    ),
    token: str = typer.Option(
        None,
        "--token",
        envvar=_ENV_TOKEN,
        help=(
            "Bearer JWT for the authenticated tenant. Env: "
            "``AXON_ENTERPRISE_TOKEN``. Adopters MUST NOT hard-code "
            "this in workflow files — pass via ``${{ secrets.* }}``."
        ),
    ),
    max_errors: int = typer.Option(
        0,
        "--max-errors",
        min=0,
        help="Maximum error-severity diagnostics before the gate fails (default 0).",
    ),
    max_warnings: int | None = typer.Option(
        None,
        "--max-warnings",
        help=(
            "Maximum warning-severity diagnostics before the gate fails. "
            "Default: warnings don't fail the gate."
        ),
    ),
    fail_on_hint: bool = typer.Option(
        False,
        "--fail-on-hint/--no-fail-on-hint",
        help="Fail the gate when ANY hint-severity diagnostic is present.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "Pagination cursor: ISO-8601 timestamp OR relative duration "
            "(``30m``, ``2h``, ``1d``). Filters to diagnostics emitted "
            "after this point."
        ),
    ),
    limit: int = typer.Option(
        500,
        "--limit",
        min=1,
        max=500,
        help="Max entries pulled from the dashboard endpoint (default 500).",
    ),
    mode: str = typer.Option(
        "aggregated",
        "--mode",
        help="Dashboard response mode: ``aggregated`` (default) or ``raw``.",
    ),
    file_path: str | None = typer.Option(
        None,
        "--file-path",
        help="Equality filter on file_path (raw mode only).",
    ),
    code: str | None = typer.Option(
        None,
        "--code",
        help="Equality filter on error code (raw mode only).",
    ),
    bucket_size: int = typer.Option(
        10,
        "--bucket-size",
        min=1,
        max=1000,
        help="Line bucket size for aggregated mode (default 10).",
    ),
    timeout: float = typer.Option(
        _DEFAULT_TIMEOUT_SECS,
        "--timeout",
        min=1.0,
        help="HTTP timeout in seconds for the dashboard fetch.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON on stdout instead of the human summary.",
    ),
) -> None:
    """Run the CI compliance gate. Exit 0/1/2 per the closed catalog.

    Typical usage (composite action wraps this):

    .. code-block:: shell

        axon-enterprise diagnostics gate \\
            --endpoint $AXON_ENTERPRISE_ENDPOINT \\
            --token $AXON_ENTERPRISE_TOKEN \\
            --max-errors 0 \\
            --since 1h
    """
    # ── Validation gate (FAIL_INPUT before we even ping the server) ─
    if mode not in {"aggregated", "raw"}:
        _print_input_error(f"--mode must be 'aggregated' or 'raw', got {mode!r}")
        raise typer.Exit(code=2)

    if not endpoint:
        _print_input_error(
            f"--endpoint is required (or set {_ENV_ENDPOINT} env var)"
        )
        raise typer.Exit(code=2)
    if not token:
        _print_input_error(
            f"--token is required (or set {_ENV_TOKEN} env var)"
        )
        raise typer.Exit(code=2)

    try:
        since_dt = _parse_since(since)
    except ValueError as exc:
        _print_input_error(str(exc))
        raise typer.Exit(code=2) from exc

    # ── HTTP fetch ───────────────────────────────────────────────
    try:
        payload = _fetch_payload(
            endpoint=endpoint,
            token=token,
            since=since_dt,
            limit=limit,
            mode=mode,
            file_path=file_path,
            code=code,
            bucket_size=bucket_size,
            timeout=timeout,
        )
    except httpx.HTTPStatusError as exc:
        _print_transport_error(
            f"server returned {exc.response.status_code} {exc.response.reason_phrase}"
        )
        raise typer.Exit(code=2) from exc
    except httpx.HTTPError as exc:
        _print_transport_error(f"transport failure: {exc}")
        raise typer.Exit(code=2) from exc
    except ValueError as exc:
        # JSON decode error (non-JSON response body).
        _print_transport_error(f"response was not JSON: {exc}")
        raise typer.Exit(code=2) from exc

    # ── Pure verdict evaluation ──────────────────────────────────
    config = GateConfig(
        max_errors=max_errors,
        max_warnings=max_warnings,
        fail_on_hint=fail_on_hint,
        require_mode=mode,
    )
    result = evaluate(payload, config)

    # ── Output projection ────────────────────────────────────────
    if json_output:
        typer.echo(_result_to_json(result))
    else:
        typer.echo(format_summary(result))
    raise typer.Exit(code=result.exit_code)


# ──────────────────────────────────────────────────────────────────
#  Output helpers (D4-safe — no source text in any branch)
# ──────────────────────────────────────────────────────────────────


def _print_input_error(message: str) -> None:
    """Emit a FAIL_INPUT summary on stderr + return verdict shape."""
    typer.echo(
        f"axon-enterprise-ci-gate: FAIL_INPUT\nreason: {message}",
        err=True,
    )


def _print_transport_error(message: str) -> None:
    """Emit a transport-error summary on stderr. Maps to exit 2
    along with FAIL_INPUT — they are the same exit class from the
    CI workflow's perspective (configuration trouble).
    """
    typer.echo(
        f"axon-enterprise-ci-gate: FAIL_INPUT\nreason: {message}",
        err=True,
    )


def _result_to_json(result: GateResult) -> str:
    """Machine-readable projection for ``--json`` mode.

    Stable wire shape — adopters can build dashboards / Slack
    bots on top.
    """
    return json.dumps(
        {
            "verdict": result.verdict.value,
            "exit_code": result.exit_code,
            "tenant_id": result.tenant_id,
            "vertical": result.vertical,
            "mode": result.mode,
            "counts": {
                "errors": result.counts.errors,
                "warnings": result.counts.warnings,
                "hints": result.counts.hints,
                "unknown": result.counts.unknown,
                "total": result.counts.total,
            },
            "reason": result.reason,
            "threshold_breached": result.threshold_breached,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = ["app", "gate_command"]
