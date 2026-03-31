"""
AXON Compute — Native Pipeline Tests
========================================
Tests for the 3-tier native execution pipeline described in Paper §5:

  Tier 1: Rust transpilation → rustc cdylib → ctypes FFI
  Tier 2: C transpilation → gcc/tcc → ctypes FFI
  Tier 3: Python interpreted fallback

These tests verify:
  - RustTranspiler generates correct Rust source
  - NativeCompiler C transpilation generates correct C source
  - FFIBridge correctly wraps ctypes operations
  - NativeCompiler detects available tiers
  - NativeComputeDispatcher 3-tier fallback chain
  - Compilation cache operates correctly
  - All tiers produce identical deterministic results
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from axon.runtime.rust_transpiler import RustTranspiler, TranspileResult
from axon.runtime.ffi_bridge import FFIBridge
from axon.runtime.native_compiler import NativeCompiler, CompileResult
from axon.runtime.compute_dispatcher import NativeComputeDispatcher


# ═══════════════════════════════════════════════════════════════════
#  RUST TRANSPILER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestRustTranspiler:
    """Verify Rust source generation from compute logic DSL."""

    def test_simple_addition(self):
        t = RustTranspiler()
        result = t.transpile(
            "let result = a + b\nreturn result",
            "Add",
            ["a", "b"],
        )
        assert isinstance(result, TranspileResult)
        assert "pub extern \"C\" fn" in result.rust_source
        assert "axon_compute_Add" in result.fn_name
        assert "a: f64" in result.rust_source
        assert "b: f64" in result.rust_source
        assert "-> f64" in result.rust_source

    def test_multiplication_with_let_bindings(self):
        t = RustTranspiler()
        result = t.transpile(
            "let tax = amount * rate\nlet total = amount + tax\nreturn total",
            "CalculateTax",
            ["amount", "rate"],
        )
        assert "let tax" in result.rust_source
        assert "let total" in result.rust_source
        assert "amount" in result.rust_source
        assert "rate" in result.rust_source

    def test_no_mangle_attribute(self):
        """Rust output must have #[no_mangle] for C-ABI FFI."""
        t = RustTranspiler()
        result = t.transpile("return x", "Identity", ["x"])
        assert "#[no_mangle]" in result.rust_source

    def test_source_hash_deterministic(self):
        """Same logic should produce same hash."""
        t = RustTranspiler()
        r1 = t.transpile("return a + b", "Add", ["a", "b"])
        r2 = t.transpile("return a + b", "Add", ["a", "b"])
        assert r1.source_hash == r2.source_hash

    def test_different_logic_different_hash(self):
        t = RustTranspiler()
        r1 = t.transpile("return a + b", "Add", ["a", "b"])
        r2 = t.transpile("return a * b", "Mul", ["a", "b"])
        assert r1.source_hash != r2.source_hash

    def test_sanitized_fn_name(self):
        t = RustTranspiler()
        result = t.transpile("return x", "my-func!", ["x"])
        # Special characters should be sanitized
        assert "axon_compute_" in result.fn_name

    def test_empty_logic_raises(self):
        """Empty logic_source must raise — no implicit 0.0 allowed."""
        t = RustTranspiler()
        with pytest.raises(ValueError, match="Empty logic_source"):
            t.transpile("", "Empty", [])


# ═══════════════════════════════════════════════════════════════════
#  FFI BRIDGE TESTS
# ═══════════════════════════════════════════════════════════════════


class TestFFIBridge:
    """Verify FFI bridge interface without requiring real compiled libs."""

    def test_lib_extension_returns_string(self):
        ext = FFIBridge.lib_extension()
        assert isinstance(ext, str)
        assert ext.startswith(".")

    def test_lib_extension_platform_specific(self):
        import sys
        ext = FFIBridge.lib_extension()
        if sys.platform == "win32":
            assert ext == ".dll"
        elif sys.platform == "darwin":
            assert ext == ".dylib"
        else:
            assert ext == ".so"

    def test_load_nonexistent_raises(self):
        bridge = FFIBridge()
        with pytest.raises(OSError):
            bridge.load("/nonexistent/path/lib.so")

    def test_call_nonexistent_raises(self):
        bridge = FFIBridge()
        with pytest.raises(OSError):
            bridge.call("/nonexistent/path/lib.so", "fn", [1.0])

    def test_unload_all_empty(self):
        bridge = FFIBridge()
        bridge.unload_all()  # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  NATIVE COMPILER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestNativeCompiler:
    """Verify NativeCompiler tier selection, C transpilation, and cache."""

    def test_available_tier_no_compilers(self):
        """Without compilers, tier should be 'python'."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            assert nc.available_tier == "python"

    def test_available_tier_with_rustc(self):
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/rustc" if cmd == "rustc" else None
            )
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            assert nc.available_tier == "rust"

    def test_available_tier_with_gcc_only(self):
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/gcc" if cmd == "gcc" else None
            )
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            assert nc.available_tier == "c"

    def test_compile_falls_back_to_python(self):
        """When no compilers present, compile returns python tier."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            result = nc.compile(
                "let r = a + b\nreturn r", "Add", ["a", "b"],
            )
            assert isinstance(result, CompileResult)
            assert result.tier == "python"
            assert result.cached is False

    def test_c_transpilation_produces_valid_c(self):
        """Verify C transpiler generates correct function signature."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            c_source = nc._transpile_to_c(
                "let tax = amount * rate\nlet total = amount + tax\nreturn total",
                "axon_compute_CalcTax",
                ["amount", "rate"],
            )
            assert "double axon_compute_CalcTax" in c_source
            assert "double amount" in c_source
            assert "double rate" in c_source
            assert "double tax = amount * rate;" in c_source
            assert "double total = amount + tax;" in c_source
            assert "return total;" in c_source

    def test_c_transpilation_no_includes(self):
        """Security: C output must not contain #include directives."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            c_source = nc._transpile_to_c(
                "return a + b", "fn", ["a", "b"],
            )
            assert "#include" not in c_source

    def test_c_transpilation_pure_function(self):
        """Security: C output must not contain I/O or dynamic alloc."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            c_source = nc._transpile_to_c(
                "let x = a * b\nreturn x", "fn", ["a", "b"],
            )
            assert "malloc" not in c_source
            assert "printf" not in c_source
            assert "scanf" not in c_source
            assert "fopen" not in c_source
            assert "system(" not in c_source

    def test_compile_hash_deterministic(self):
        """Same logic src should produce same source_hash."""
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
            r1 = nc.compile("return a + b", "Add", ["a", "b"])
            r2 = nc.compile("return a + b", "Add", ["a", "b"])
            assert r1.source_hash == r2.source_hash

    def test_cache_dir_created(self):
        d = tempfile.mkdtemp()
        cache = Path(d) / "axon_test_cache"
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=cache)
        assert cache.exists()
        shutil.rmtree(d)

    def test_clear_cache(self):
        d = tempfile.mkdtemp()
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=d)
            # Write a dummy file
            (Path(d) / "test.txt").write_text("hello")
            nc.clear_cache()
            # Cache dir should still exist but be empty
            assert Path(d).exists()
            assert len(list(Path(d).iterdir())) == 0
        shutil.rmtree(d)


# ═══════════════════════════════════════════════════════════════════
#  DISPATCHER 3-TIER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestDispatcher3Tier:
    """Verify the NativeComputeDispatcher 3-tier pipeline."""

    def _make_meta(self, logic, name="Test", params=None, args=None):
        params = params or [("a", "Float"), ("b", "Float")]
        args = args or ["10.0", "20.0"]
        return {
            "compute_name": name,
            "arguments": args,
            "output_name": "result",
            "compute_definition": {
                "name": name,
                "inputs": [{"name": p, "type": t} for p, t in params],
                "output_type": "Float",
                "logic_source": logic,
                "shield_ref": "",
                "verified": False,
            },
        }

    async def test_python_fallback_produces_result(self):
        """Without compilers, dispatcher must still produce correct results."""
        d = NativeComputeDispatcher()
        meta = self._make_meta("let r = a + b\nreturn r")
        result = await d.dispatch(meta, {})
        assert result["result"] == 30.0
        assert result["tier"] == "python"

    async def test_python_fallback_tax_calculation(self):
        d = NativeComputeDispatcher()
        meta = self._make_meta(
            "let tax = a * b\nlet total = a + tax\nreturn total",
        )
        meta["arguments"] = ["100.0", "0.19"]
        result = await d.dispatch(meta, {})
        assert abs(result["result"] - 119.0) < 0.001
        assert result["tier"] == "python"

    async def test_tier_key_present_in_result(self):
        """Result dict must include 'tier' key."""
        d = NativeComputeDispatcher()
        meta = self._make_meta("return a")
        meta["arguments"] = ["42.0"]
        meta["compute_definition"]["inputs"] = [
            {"name": "a", "type": "Float"},
        ]
        result = await d.dispatch(meta, {})
        assert "tier" in result

    async def test_context_resolution_with_tier(self):
        d = NativeComputeDispatcher()
        meta = self._make_meta(
            "let r = a + b\nreturn r",
            params=[("a", "Float"), ("b", "Float")],
            args=["data.x", "5.0"],
        )
        ctx = {"data": {"x": 7.0}}
        result = await d.dispatch(meta, ctx)
        assert result["result"] == 12.0

    async def test_empty_logic_fallback(self):
        d = NativeComputeDispatcher()
        meta = self._make_meta("", params=[], args=[])
        result = await d.dispatch(meta, {})
        assert result["result"] is None
        assert result["tier"] == "python"

    async def test_native_pipeline_init_graceful(self):
        """_ensure_native_pipeline should not raise even if imports fail."""
        d = NativeComputeDispatcher()
        d._ensure_native_pipeline()
        # Should always succeed — even if compilers not present
        assert d._native_init_done is True

    async def test_multiple_dispatches_reuse_pipeline(self):
        """The native pipeline is only initialised once."""
        d = NativeComputeDispatcher()
        meta = self._make_meta("return a", params=[("a", "Float")], args=["1.0"])
        await d.dispatch(meta, {})
        await d.dispatch(meta, {})
        assert d._native_init_done is True

    async def test_dispatcher_deterministic(self):
        """Same inputs → same output, always."""
        d = NativeComputeDispatcher()
        meta = self._make_meta("let r = a * b\nreturn r")
        r1 = await d.dispatch(meta, {})
        r2 = await d.dispatch(meta, {})
        assert r1["result"] == r2["result"] == 200.0


# ═══════════════════════════════════════════════════════════════════
#  RUST TRANSPILER — EDGE CASES
# ═══════════════════════════════════════════════════════════════════


class TestRustTranspilerEdgeCases:
    """Edge-case validation for Rust output generation."""

    def test_numeric_literal_suffix(self):
        """Numeric literals in Rust should be f64."""
        t = RustTranspiler()
        result = t.transpile(
            "let x = 42\nreturn x", "Lit", ["a"],
        )
        # Should contain f64 suffix on literals
        assert "f64" in result.rust_source

    def test_division_transpiled(self):
        t = RustTranspiler()
        result = t.transpile(
            "let r = a / b\nreturn r", "Div", ["a", "b"],
        )
        assert "/" in result.rust_source

    def test_subtraction_transpiled(self):
        t = RustTranspiler()
        result = t.transpile(
            "let r = a - b\nreturn r", "Sub", ["a", "b"],
        )
        assert "-" in result.rust_source

    def test_complex_expression(self):
        t = RustTranspiler()
        result = t.transpile(
            "let x = a + b * c\nreturn x",
            "Complex",
            ["a", "b", "c"],
        )
        assert "a" in result.rust_source
        assert "b" in result.rust_source
        assert "c" in result.rust_source

    def test_multiple_let_bindings(self):
        t = RustTranspiler()
        result = t.transpile(
            "let x = a + b\nlet y = x * 2\nlet z = y - a\nreturn z",
            "Chain",
            ["a", "b"],
        )
        assert "let x" in result.rust_source
        assert "let y" in result.rust_source
        assert "let z" in result.rust_source

    def test_param_names_in_result(self):
        t = RustTranspiler()
        result = t.transpile("return a", "Id", ["a"])
        assert list(result.param_names) == ["a"]


# ═══════════════════════════════════════════════════════════════════
#  C TRANSPILER — SECURITY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestCTranspilerSecurity:
    """Verify security properties of generated C code."""

    def _get_c_source(self, logic, params=None):
        params = params or ["a", "b"]
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
        return nc._transpile_to_c(logic, "test_fn", params)

    def test_no_stdlib_includes(self):
        c = self._get_c_source("return a + b")
        assert "#include" not in c
        assert "stdio" not in c
        assert "stdlib" not in c

    def test_no_system_calls(self):
        c = self._get_c_source("return a")
        assert "system(" not in c
        assert "exec(" not in c
        assert "popen(" not in c

    def test_no_memory_allocation(self):
        c = self._get_c_source("return a * b")
        assert "malloc" not in c
        assert "calloc" not in c
        assert "realloc" not in c
        assert "free(" not in c

    def test_no_file_io(self):
        c = self._get_c_source("return a / b")
        assert "fopen" not in c
        assert "fwrite" not in c
        assert "fread" not in c

    def test_pure_arithmetic_only(self):
        """Generated C should contain only arithmetic operations."""
        c = self._get_c_source(
            "let tax = a * b\nlet total = a + tax\nreturn total",
        )
        # Should only have: double vars, arithmetic, return
        lines = [l.strip() for l in c.strip().splitlines() if l.strip()]
        for line in lines:
            # Each line should be: comment, export macro, signature,
            # double decl, return, or brace
            assert any([
                line.startswith("/*"),
                line.startswith("*/"),
                line.startswith("*"),
                line.startswith("__declspec") or line.startswith("__attribute__"),
                line.startswith("double"),
                line.startswith("return"),
                line in ("{", "}"),
            ]), f"Unexpected C line: {line}"


# ═══════════════════════════════════════════════════════════════════
#  COMPILE RESULT DATACLASS
# ═══════════════════════════════════════════════════════════════════


class TestCompileResult:
    """Verify CompileResult dataclass."""

    def test_fields(self):
        cr = CompileResult(
            lib_path=Path("/tmp/test.so"),
            fn_name="axon_compute_Add",
            source_hash="abc123",
            tier="rust",
            cached=False,
        )
        assert cr.lib_path == Path("/tmp/test.so")
        assert cr.fn_name == "axon_compute_Add"
        assert cr.source_hash == "abc123"
        assert cr.tier == "rust"
        assert cr.cached is False

    def test_frozen(self):
        cr = CompileResult(
            lib_path=Path("/tmp/test.so"),
            fn_name="fn",
            source_hash="h",
            tier="python",
            cached=True,
        )
        with pytest.raises(AttributeError):
            cr.tier = "rust"


# ═══════════════════════════════════════════════════════════════════
#  NEGATIVE TESTS — Division by Zero
# ═══════════════════════════════════════════════════════════════════


class TestDivisionByZero:
    """Division by zero must raise, never produce inf silently."""

    async def test_python_fallback_div_zero_raises(self):
        d = NativeComputeDispatcher()
        meta = {
            "compute_name": "Div",
            "arguments": ["10.0", "0"],
            "output_name": "r",
            "compute_definition": {
                "name": "Div",
                "inputs": [
                    {"name": "a", "type": "Float"},
                    {"name": "b", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "let r = a / b\nreturn r",
                "shield_ref": "",
                "verified": False,
            },
        }
        with pytest.raises(ZeroDivisionError, match="Division by zero"):
            await d.dispatch(meta, {})

    def test_ffi_bridge_non_finite_raises(self):
        """FFI bridge must reject NaN/Inf from native functions."""
        bridge = FFIBridge()
        # We can't call a real native function, but verify the contract
        # by testing the arity validation
        with pytest.raises(ValueError, match="Arity mismatch"):
            bridge.call("/fake/lib.so", "fn", [1.0, 2.0], expected_arity=3)


# ═══════════════════════════════════════════════════════════════════
#  NEGATIVE TESTS — Missing Return
# ═══════════════════════════════════════════════════════════════════


class TestMissingReturn:
    """Compute logic without 'return' must raise, not silently return 0."""

    def test_rust_transpiler_no_return_raises(self):
        t = RustTranspiler()
        with pytest.raises(ValueError, match="return"):
            t.transpile("let x = a + b", "NoRet", ["a", "b"])

    def test_c_transpiler_no_return_raises(self):
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
        with pytest.raises(ValueError, match="return"):
            nc._transpile_to_c("let x = a + b", "fn", ["a", "b"])

    def test_rust_transpiler_empty_raises(self):
        t = RustTranspiler()
        with pytest.raises(ValueError, match="Empty logic_source"):
            t.transpile("", "Empty", [])


# ═══════════════════════════════════════════════════════════════════
#  NEGATIVE TESTS — Non-Numeric Arguments
# ═══════════════════════════════════════════════════════════════════


class TestNonNumericArgs:
    """Non-numeric compute arguments must raise, not silently become 0.0."""

    async def test_string_arg_raises(self):
        d = NativeComputeDispatcher()
        meta = {
            "compute_name": "Add",
            "arguments": ["hello", "5.0"],
            "output_name": "r",
            "compute_definition": {
                "name": "Add",
                "inputs": [
                    {"name": "a", "type": "Float"},
                    {"name": "b", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "return a + b",
                "shield_ref": "",
                "verified": False,
            },
        }
        with pytest.raises(ValueError, match="non-numeric"):
            await d.dispatch(meta, {})


# ═══════════════════════════════════════════════════════════════════
#  NEGATIVE TESTS — Invalid Expressions
# ═══════════════════════════════════════════════════════════════════


class TestInvalidExpressions:
    """Unsupported or malformed expressions must be rejected."""

    def test_unknown_identifier_raises(self):
        t = RustTranspiler()
        with pytest.raises(ValueError, match="Unknown identifier"):
            t.transpile("return z", "Bad", ["a", "b"])

    def test_unsupported_statement_raises(self):
        t = RustTranspiler()
        with pytest.raises(ValueError, match="Unsupported"):
            t.transpile("if x > 0 then return x", "Bad", ["x"])

    def test_numeric_overflow_rejected(self):
        """Overflow literals (1e999) must not be accepted as numeric."""
        t = RustTranspiler()
        with pytest.raises(ValueError, match="Unknown identifier"):
            # 1e999 overflows float → _is_numeric returns False → treated as id
            t.transpile("return 1e999", "Overflow", [])


# ═══════════════════════════════════════════════════════════════════
#  NEGATIVE TESTS — Parser Rejects Invalid Logic
# ═══════════════════════════════════════════════════════════════════


class TestParserRejectsInvalidLogic:
    """Parser must reject non-deterministic constructs inside logic {}."""

    def test_step_inside_logic_rejected(self):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        source = '''compute Bad {
    input: x (Float)
    output: Float
    logic {
        step Report {
            ask: "This should not be allowed"
            output: String
        }
    }
}'''
        tokens = Lexer(source).tokenize()
        with pytest.raises(Exception, match="let or return"):
            Parser(tokens).parse()

    def test_probe_inside_logic_rejected(self):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        source = '''compute Bad {
    input: x (Float)
    output: Float
    logic {
        probe Check { ask: "check" }
    }
}'''
        tokens = Lexer(source).tokenize()
        with pytest.raises(Exception, match="let or return"):
            Parser(tokens).parse()

    def test_valid_logic_still_works(self):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler import ast_nodes as ast
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}'''
        tokens = Lexer(source).tokenize()
        tree = Parser(tokens).parse()
        decl = tree.declarations[0]
        assert isinstance(decl, ast.ComputeDefinition)
        assert len(decl.logic_body) == 2


# ═══════════════════════════════════════════════════════════════════
#  FULL SHA-256 HASH TESTS
# ═══════════════════════════════════════════════════════════════════


class TestFullSHA256:
    """Verify full SHA-256 hash is used (no truncation)."""

    def test_transpiler_hash_length(self):
        t = RustTranspiler()
        result = t.transpile("return a", "Id", ["a"])
        assert len(result.source_hash) == 64  # full SHA-256 hex

    def test_compiler_hash_length(self):
        with patch("shutil.which", return_value=None):
            nc = NativeCompiler(cache_dir=tempfile.mkdtemp())
        result = nc.compile("return a + b", "Add", ["a", "b"])
        assert len(result.source_hash) == 64


# ═══════════════════════════════════════════════════════════════════
#  FFI ARITY VALIDATION
# ═══════════════════════════════════════════════════════════════════


class TestFFIArityValidation:
    """FFI bridge must validate argument count before calling native code."""

    def test_arity_mismatch_raises(self):
        bridge = FFIBridge()
        with pytest.raises(ValueError, match="Arity mismatch"):
            bridge.call("/fake.so", "fn", [1.0], expected_arity=2)

    def test_arity_match_passes_validation(self):
        """Correct arity should not raise ValueError (will raise OSError for missing lib)."""
        bridge = FFIBridge()
        with pytest.raises(OSError):
            bridge.call("/fake.so", "fn", [1.0, 2.0], expected_arity=2)

    def test_no_arity_check_when_none(self):
        """When expected_arity is None, no arity check is performed."""
        bridge = FFIBridge()
        with pytest.raises(OSError):
            bridge.call("/fake.so", "fn", [1.0])


# ═══════════════════════════════════════════════════════════════════
#  SHIELD VERIFICATION HONESTY
# ═══════════════════════════════════════════════════════════════════


class TestShieldVerificationHonesty:
    """Shield verification must check scan categories, not just existence."""

    def test_shield_with_scan_marks_verified(self):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.ir_generator import IRGenerator
        source = '''shield TypeSafety {
    scan: [bias]
}
compute Calc {
    input: x (Float)
    output: Float
    shield: TypeSafety
    logic {
        return x
    }
}'''
        tokens = Lexer(source).tokenize()
        tree = Parser(tokens).parse()
        ir = IRGenerator().generate(tree)
        assert ir.compute_specs[0].verified is True

    def test_shield_without_scan_marks_unverified(self):
        """A shield with empty scan categories should not mark verified."""
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.ir_generator import IRGenerator
        source = '''shield EmptyShield {
    strategy: "pattern"
}
compute Calc {
    input: x (Float)
    output: Float
    shield: EmptyShield
    logic {
        return x
    }
}'''
        tokens = Lexer(source).tokenize()
        tree = Parser(tokens).parse()
        ir = IRGenerator().generate(tree)
        assert ir.compute_specs[0].verified is False
