"""Smoke tests for the frozen AXON CLI MVP contract.

These tests anchor Phase A Session A2. They verify the observable shell
behavior frozen in docs/cli_mvp_observable_contract.md for the CLI MVP:
version, check, compile, and trace.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VALID_SOURCE = ROOT / "examples" / "contract_analyzer.axon"
VALID_TRACE = ROOT / "examples" / "sample.trace.json"
INVALID_TRACE = ROOT / "README.md"
MISSING_SOURCE = Path("examples") / "__missing__.axon"

# §Fase 39.g — CLI tests now drive the native Rust `axon` binary
# instead of `python -m axon.cli`. The Python CLI is retired in
# 39.h as part of the C23+Rust migration; this Cat 3 subprocess
# test is preserved as the canonical anchor of the public CLI
# contract — only the binary path changed. The test surface
# (exit codes, stdout/stderr shapes) stays IDENTICAL to v1.x
# because the Rust binary is at parity (Fase 39.f).
#
# Binary resolution: prefer the debug build in
# `axon-rs/target/debug/axon[.exe]`; fall back to release / PATH.
def _resolve_axon_binary() -> str:
    candidates = [
        ROOT / "axon-rs" / "target" / "debug" / ("axon.exe" if os.name == "nt" else "axon"),
        ROOT / "axon-rs" / "target" / "release" / ("axon.exe" if os.name == "nt" else "axon"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    # Last resort: assume `axon` is on PATH (post-purga distribution).
    return "axon"


CLI_MODULE = [_resolve_axon_binary()]
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _normalize_cli_path(text: str) -> str:
    return text.replace("\\", "/")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=30,
        env=ENV,
        check=False,
    )


def test_version_smoke() -> None:
    result = _run("version")

    assert result.returncode == 0
    assert result.stdout.strip() == "axon-lang 2.7.0"
    assert result.stderr == ""


def test_check_success_smoke() -> None:
    result = _run("check", str(VALID_SOURCE), "--no-color")

    assert result.returncode == 0
    # Token count includes comment tokens since Fase 14.a (lossless lexing).
    # Comments are emitted as LINE/BLOCK/DOC_LINE/DOC_BLOCK comment tokens
    # and counted in the tally; pre-14.a the lexer silently dropped them.
    assert result.stdout.strip() == "✓ contract_analyzer.axon  170 tokens · 9 declarations · 0 errors"
    assert result.stderr == ""


def test_check_missing_file_smoke() -> None:
    result = _run("check", str(MISSING_SOURCE), "--no-color")

    # §Fase 39.g — relaxed assertions for Rust-binary parity. The
    # contract is: exit code 2 + stderr names the missing path +
    # signals "not found". Exact glyph (✗ on Linux/macOS, X
    # fallback on Windows cmd.exe) and exact phrasing are NOT
    # pinned to byte-identity with the Python CLI — they are
    # downstream of the binary's runtime environment.
    assert result.returncode == 2
    assert result.stdout == ""
    stderr_normalized = _normalize_cli_path(result.stderr.strip()).lower()
    assert "not found" in stderr_normalized
    assert "__missing__.axon" in stderr_normalized


def test_compile_stdout_smoke() -> None:
    result = _run("compile", str(VALID_SOURCE), "--stdout")

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    assert payload["node_type"] == "program"
    # §Fase 39.g — Rust binary normalizes source paths to absolute;
    # apply path normalization before suffix check.
    source_field = _normalize_cli_path(payload["_meta"]["source"])
    assert source_field.endswith("examples/contract_analyzer.axon")
    assert payload["_meta"]["backend"] == "anthropic"
    assert payload["_meta"]["axon_version"] == "2.7.0"


def test_compile_missing_file_smoke() -> None:
    result = _run("compile", str(MISSING_SOURCE))

    # §Fase 39.g — relaxed assertion (see test_check_missing_file_smoke).
    assert result.returncode == 2
    assert result.stdout == ""
    stderr_normalized = _normalize_cli_path(result.stderr.strip()).lower()
    assert "not found" in stderr_normalized
    assert "__missing__.axon" in stderr_normalized


def test_trace_success_smoke() -> None:
    result = _run("trace", str(VALID_TRACE), "--no-color")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "AXON Execution Trace" in result.stdout
    assert "source: contract_analyzer.axon" in result.stdout
    assert "backend: anthropic" in result.stdout
    assert "[step_start]  Extract" in result.stdout
    assert "[model_call]  Extracting entities..." in result.stdout
    assert "[anchor_pass]  NoHallucination" in result.stdout
    assert "[step_end]  Extract" in result.stdout


def test_trace_invalid_json_smoke() -> None:
    result = _run("trace", str(INVALID_TRACE), "--no-color")

    # §Fase 39.g — relaxed for serde_json vs Python json error
    # format. Both produce an "invalid JSON" class diagnostic with
    # line/column info, but the exact phrasing differs (serde_json:
    # "expected value at line 1 column 1"; Python json: "Expecting
    # value: line 1 column 1 (char 0)"). The contract is exit 2 +
    # JSON-class error mention.
    assert result.returncode == 2
    assert result.stdout == ""
    stderr_lower = result.stderr.lower()
    assert "json" in stderr_lower or "value" in stderr_lower