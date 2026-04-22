"""Smoke tests for the frozen AXON CLI MVP contract.

These tests anchor Phase A Session A2. They verify the observable shell
behavior frozen in docs/cli_mvp_observable_contract.md for the CLI MVP:
version, check, compile, and trace.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VALID_SOURCE = ROOT / "examples" / "contract_analyzer.axon"
VALID_TRACE = ROOT / "examples" / "sample.trace.json"
INVALID_TRACE = ROOT / "README.md"
MISSING_SOURCE = Path("examples") / "__missing__.axon"
CLI_MODULE = [sys.executable, "-m", "axon.cli"]
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
    assert result.stdout.strip() == "axon-lang 1.4.0"
    assert result.stderr == ""


def test_check_success_smoke() -> None:
    result = _run("check", str(VALID_SOURCE), "--no-color")

    assert result.returncode == 0
    assert result.stdout.strip() == "✓ contract_analyzer.axon  168 tokens · 9 declarations · 0 errors"
    assert result.stderr == ""


def test_check_missing_file_smoke() -> None:
    result = _run("check", str(MISSING_SOURCE), "--no-color")

    assert result.returncode == 2
    assert result.stdout == ""
    assert _normalize_cli_path(result.stderr.strip()) == "✗ File not found: examples/__missing__.axon"


def test_compile_stdout_smoke() -> None:
    result = _run("compile", str(VALID_SOURCE), "--stdout")

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    assert payload["node_type"] == "program"
    assert payload["_meta"]["source"].endswith("examples/contract_analyzer.axon")
    assert payload["_meta"]["backend"] == "anthropic"
    assert payload["_meta"]["axon_version"] == "1.4.0"


def test_compile_missing_file_smoke() -> None:
    result = _run("compile", str(MISSING_SOURCE))

    assert result.returncode == 2
    assert result.stdout == ""
    assert _normalize_cli_path(result.stderr.strip()) == "✗ File not found: examples/__missing__.axon"


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

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "✗ Invalid JSON: Expecting value: line 1 column 1 (char 0)"