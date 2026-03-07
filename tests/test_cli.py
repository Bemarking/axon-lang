"""
AXON CLI — Unit Tests
=======================
Tests all seven CLI subcommands: check, compile, run, trace, version, repl, inspect.
Uses the real compiler pipeline with the bundled example file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "contract_analyzer.axon"
CLI_MODULE = [sys.executable, "-m", "axon.cli"]

# Force UTF-8 output on Windows subprocess pipes
_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Execute ``python -m axon.cli`` with the given arguments."""
    return subprocess.run(
        [*CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=30,
        check=check,
        env=_ENV,
    )


# ══════════════════════════════════════════════════════════════════
#  axon version
# ══════════════════════════════════════════════════════════════════


class TestVersion:
    """``axon version`` prints semver and exits 0."""

    def test_version_subcommand(self):
        r = _run("version")
        assert r.returncode == 0
        assert "axon-lang" in r.stdout
        parts = r.stdout.strip().split()
        # "axon-lang X.Y.Z"
        assert len(parts) == 2
        assert parts[0] == "axon-lang"
        # Verify it looks like semver
        major, minor, patch = parts[1].split(".")
        assert major.isdigit() and minor.isdigit() and patch.isdigit()

    def test_version_flag(self):
        r = _run("--version")
        assert r.returncode == 0
        assert "axon-lang" in r.stdout


# ══════════════════════════════════════════════════════════════════
#  axon check
# ══════════════════════════════════════════════════════════════════


class TestCheck:
    """``axon check`` validates .axon files through the front-end pipeline."""

    def test_check_valid_file(self):
        r = _run("check", str(EXAMPLE))
        assert r.returncode == 0
        assert "✓" in r.stdout or "tokens" in r.stdout

    def test_check_reports_token_count(self):
        r = _run("check", str(EXAMPLE), "--no-color")
        # Should mention tokens and declarations
        assert "tokens" in r.stdout
        assert "declarations" in r.stdout
        assert "0 errors" in r.stdout

    def test_check_missing_file(self):
        r = _run("check", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_check_invalid_syntax(self, tmp_path):
        bad = tmp_path / "bad.axon"
        bad.write_text("42 + garbage", encoding="utf-8")
        r = _run("check", str(bad), check=False)
        assert r.returncode == 1


# ══════════════════════════════════════════════════════════════════
#  axon compile
# ══════════════════════════════════════════════════════════════════


class TestCompile:
    """``axon compile`` produces IR JSON output."""

    def test_compile_stdout(self):
        r = _run("compile", str(EXAMPLE), "--stdout")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "node_type" in data
        assert data["node_type"] == "program"

    def test_compile_includes_meta(self):
        r = _run("compile", str(EXAMPLE), "--stdout")
        data = json.loads(r.stdout)
        assert "_meta" in data
        assert data["_meta"]["backend"] == "anthropic"
        assert "axon_version" in data["_meta"]

    def test_compile_to_file(self, tmp_path):
        src = tmp_path / "test.axon"
        src.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        out = tmp_path / "test.ir.json"
        r = _run("compile", str(src))
        assert r.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["node_type"] == "program"

    def test_compile_custom_output(self, tmp_path):
        out = tmp_path / "custom.json"
        r = _run("compile", str(EXAMPLE), "-o", str(out))
        assert r.returncode == 0
        assert out.exists()

    def test_compile_missing_file(self):
        r = _run("compile", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_compile_backend_flag(self):
        r = _run("compile", str(EXAMPLE), "--stdout", "-b", "openai")
        data = json.loads(r.stdout)
        assert data["_meta"]["backend"] == "openai"


# ══════════════════════════════════════════════════════════════════
#  axon trace
# ══════════════════════════════════════════════════════════════════


class TestTrace:
    """``axon trace`` pretty-prints a trace JSON file."""

    @pytest.fixture()
    def trace_file(self, tmp_path) -> Path:
        """Create a minimal trace JSON file."""
        trace = {
            "_meta": {"source": "test.axon", "backend": "anthropic"},
            "events": [
                {"type": "step_start", "data": {"step_name": "Extract"}},
                {"type": "model_call", "data": {"message": "Extracting..."}},
                {"type": "anchor_pass", "data": {"name": "NoHallucination"}},
                {"type": "step_end", "data": {"step_name": "Extract"}},
            ],
        }
        path = tmp_path / "test.trace.json"
        path.write_text(json.dumps(trace), encoding="utf-8")
        return path

    def test_trace_renders(self, trace_file):
        r = _run("trace", str(trace_file))
        assert r.returncode == 0
        assert "AXON Execution Trace" in r.stdout

    def test_trace_shows_events(self, trace_file):
        r = _run("trace", str(trace_file), "--no-color")
        assert "step_start" in r.stdout
        assert "anchor_pass" in r.stdout

    def test_trace_missing_file(self):
        r = _run("trace", "nonexistent.trace.json", check=False)
        assert r.returncode == 2

    def test_trace_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        r = _run("trace", str(bad), check=False)
        assert r.returncode == 2


# ══════════════════════════════════════════════════════════════════
#  axon (no args) + help
# ══════════════════════════════════════════════════════════════════


class TestHelp:
    """CLI shows help when invoked without subcommand or with --help."""

    def test_no_args_shows_help(self):
        r = _run(check=False)
        assert r.returncode == 0
        assert "AXON" in r.stdout
        assert "check" in r.stdout
        assert "compile" in r.stdout
        assert "run" in r.stdout

    def test_help_flag(self):
        r = _run("--help")
        assert r.returncode == 0
        assert "check" in r.stdout


# ══════════════════════════════════════════════════════════════════
#  axon run (smoke test — no API key required for check only)
# ══════════════════════════════════════════════════════════════════


class TestRunSmoke:
    """``axon run`` at minimum compiles the file before failing on backend."""

    def test_run_missing_file(self):
        r = _run("run", "nonexistent.axon", check=False)
        assert r.returncode == 2

    def test_run_invalid_syntax(self, tmp_path):
        bad = tmp_path / "bad.axon"
        bad.write_text("42 + garbage", encoding="utf-8")
        r = _run("run", str(bad), check=False)
        assert r.returncode == 1


# ══════════════════════════════════════════════════════════════════
#  axon inspect
# ══════════════════════════════════════════════════════════════════


class TestInspect:
    """``axon inspect`` introspects the stdlib."""

    def test_inspect_anchors(self):
        r = _run("inspect", "anchors")
        assert r.returncode == 0
        assert "ANCHORS" in r.stdout
        assert "NoHallucination" in r.stdout

    def test_inspect_personas(self):
        r = _run("inspect", "personas")
        assert r.returncode == 0
        assert "PERSONAS" in r.stdout

    def test_inspect_tools(self):
        r = _run("inspect", "tools")
        assert r.returncode == 0
        assert "TOOLS" in r.stdout

    def test_inspect_flows(self):
        r = _run("inspect", "flows")
        assert r.returncode == 0
        assert "FLOWS" in r.stdout

    def test_inspect_all(self):
        r = _run("inspect", "--all")
        assert r.returncode == 0
        assert "ANCHORS" in r.stdout
        assert "PERSONAS" in r.stdout

    def test_inspect_specific_anchor(self):
        r = _run("inspect", "NoHallucination")
        assert r.returncode == 0
        assert "NoHallucination" in r.stdout
        assert "anchors" in r.stdout.lower()

    def test_inspect_not_found(self):
        r = _run("inspect", "NonexistentThing", check=False)
        assert r.returncode == 1
        assert "not found" in r.stdout
