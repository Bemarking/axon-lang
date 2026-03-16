"""
AXON Shield Primitive — Runtime Tests
=========================================
Verifies shield-related runtime errors, tracer events,
and executor shield step logic.
"""

import pytest

from axon.runtime.runtime_errors import (
    AxonRuntimeError,
    CapabilityViolationError,
    ErrorContext,
    ShieldBreachError,
    TaintViolationError,
)
from axon.runtime.tracer import TraceEventType


# ═══════════════════════════════════════════════════════════════════
#  SHIELD RUNTIME ERRORS
# ═══════════════════════════════════════════════════════════════════


class TestShieldBreachError:
    """ShieldBreachError is a level-9 runtime error."""

    def test_level(self):
        err = ShieldBreachError("prompt injection detected", ErrorContext())
        assert err.level == 9

    def test_inherits(self):
        err = ShieldBreachError("breach", ErrorContext())
        assert isinstance(err, AxonRuntimeError)

    def test_message(self):
        err = ShieldBreachError("prompt injection", ErrorContext(step_name="scan"))
        assert err.message == "prompt injection"
        assert err.context.step_name == "scan"

    def test_to_dict(self):
        err = ShieldBreachError("threat", ErrorContext(step_name="guard"))
        d = err.to_dict()
        assert d["error_type"] == "ShieldBreachError"
        assert d["level"] == 9
        assert d["message"] == "threat"

    def test_str_format(self):
        err = ShieldBreachError("detected", ErrorContext())
        s = str(err)
        assert "ShieldBreachError" in s
        assert "detected" in s


class TestTaintViolationError:
    """TaintViolationError is a level-10 runtime error."""

    def test_level(self):
        err = TaintViolationError("taint violation", ErrorContext())
        assert err.level == 10

    def test_inherits(self):
        err = TaintViolationError("taint", ErrorContext())
        assert isinstance(err, AxonRuntimeError)

    def test_higher_than_shield_breach(self):
        breach = ShieldBreachError("breach", ErrorContext())
        taint = TaintViolationError("taint", ErrorContext())
        assert taint.level > breach.level


class TestCapabilityViolationError:
    """CapabilityViolationError is a level-11 runtime error."""

    def test_level(self):
        err = CapabilityViolationError("denied", ErrorContext())
        assert err.level == 11

    def test_inherits(self):
        err = CapabilityViolationError("denied", ErrorContext())
        assert isinstance(err, AxonRuntimeError)

    def test_highest_shield_error(self):
        breach = ShieldBreachError("", ErrorContext())
        taint = TaintViolationError("", ErrorContext())
        cap = CapabilityViolationError("", ErrorContext())
        assert cap.level > taint.level > breach.level

    def test_to_dict(self):
        err = CapabilityViolationError("no access", ErrorContext())
        d = err.to_dict()
        assert d["error_type"] == "CapabilityViolationError"
        assert d["level"] == 11


class TestShieldErrorHierarchy:
    """Shield errors form a severity ladder: 9 < 10 < 11."""

    def test_all_levels_ordered(self):
        errors = [
            ShieldBreachError("", ErrorContext()),
            TaintViolationError("", ErrorContext()),
            CapabilityViolationError("", ErrorContext()),
        ]
        levels = [e.level for e in errors]
        assert levels == [9, 10, 11]

    def test_all_are_exceptions(self):
        for cls in (ShieldBreachError, TaintViolationError, CapabilityViolationError):
            err = cls("msg", ErrorContext())
            assert isinstance(err, Exception)


# ═══════════════════════════════════════════════════════════════════
#  TRACER EVENTS
# ═══════════════════════════════════════════════════════════════════


class TestShieldTracerEvents:
    """Tracer has shield-specific event types."""

    def test_shield_scan_start(self):
        assert TraceEventType.SHIELD_SCAN_START.value == "shield_scan_start"

    def test_shield_scan_pass(self):
        assert TraceEventType.SHIELD_SCAN_PASS.value == "shield_scan_pass"

    def test_shield_scan_breach(self):
        assert TraceEventType.SHIELD_SCAN_BREACH.value == "shield_scan_breach"

    def test_shield_taint_check(self):
        assert TraceEventType.SHIELD_TAINT_CHECK.value == "shield_taint_check"

    def test_shield_capability_check(self):
        assert TraceEventType.SHIELD_CAPABILITY_CHECK.value == "shield_capability_check"

    def test_all_shield_events_exist(self):
        shield_events = [e for e in TraceEventType if e.value.startswith("shield_")]
        assert len(shield_events) == 5
        names = {e.value for e in shield_events}
        assert names == {
            "shield_scan_start",
            "shield_scan_pass",
            "shield_scan_breach",
            "shield_taint_check",
            "shield_capability_check",
        }


# ═══════════════════════════════════════════════════════════════════
#  EXECUTOR IMPORT CHECK
# ═══════════════════════════════════════════════════════════════════


class TestExecutorShieldImports:
    """Executor correctly imports shield-related runtime components."""

    def test_executor_importable(self):
        from axon.runtime.executor import Executor
        assert Executor is not None

    def test_executor_has_shield_step_method(self):
        from axon.runtime.executor import Executor
        assert hasattr(Executor, '_execute_shield_step')
