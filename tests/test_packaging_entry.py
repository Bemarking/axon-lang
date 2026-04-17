"""Tests for the packaged AXON MVP entrypoint bootstrap policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from axon.compiler import reset_frontend_implementation


_ENTRYPOINT_PATH = Path(__file__).resolve().parent.parent / "packaging" / "axon_mvp_entry.py"
_SPEC = importlib.util.spec_from_file_location("axon_mvp_entry", _ENTRYPOINT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
main = _MODULE.main


@pytest.fixture(autouse=True)
def _reset_frontend_after_test():
    reset_frontend_implementation()
    try:
        yield
    finally:
        reset_frontend_implementation()


def test_packaging_version_ignores_invalid_frontend_selection(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AXON_FRONTEND_IMPLEMENTATION", "missing-frontend")

    exit_code = main(["version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "axon-lang" in captured.out
    assert captured.err == ""


def test_packaging_check_invalid_frontend_selection_returns_2(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AXON_FRONTEND_IMPLEMENTATION", "missing-frontend")

    exit_code = main(["check", "examples/contract_analyzer.axon", "--no-color"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Frontend bootstrap failed" in captured.err


def test_packaging_check_uses_native_placeholder(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AXON_FRONTEND_IMPLEMENTATION", "native")

    exit_code = main(["check", "examples/contract_analyzer.axon", "--no-color"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Native frontend placeholder is not implemented yet" in (captured.out + captured.err)