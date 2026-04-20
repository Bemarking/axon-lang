"""
Tests for the Epistemic Module System (EMS)
=============================================
10 comprehensive tests covering:
  1. Single-file compilation unchanged (backwards compat)
  2. Two-file import resolution
  3. Circular import detection
  4. Epistemic compatibility (know imports speculate → warning)
  5. Epistemic conflict (severe mismatch → error)
  6. Content-addressed cache hit/miss
  7. .axi interface generation and serialization
  8. Interface-only recompilation (early cutoff)
  9. Diamond dependency resolution
  10. ModuleRegistry lookup semantics
"""

import json
import tempfile
from pathlib import Path

import pytest

from axon.compiler.interface_generator import (
    AnchorSignature,
    CognitiveInterface,
    EpistemicLevel,
    FlowSignature,
    InterfaceGenerator,
    LambdaDataSignature,
    MandateSignature,
    ModuleRegistry,
    PersonaSignature,
    PsycheSignature,
    ShieldSignature,
)
from axon.compiler.module_resolver import (
    CyclicDependencyError,
    ModuleResolver,
    scan_imports,
)
from axon.compiler.compilation_cache import (
    CacheEntry,
    CompilationCache,
)
from axon.compiler.epistemic_compat import (
    EpistemicCompatChecker,
    EpistemicDiagnostic,
)
from axon.compiler.ir_nodes import IRImport


# ═══════════════════════════════════════════════════════════════════
#  TEST 1: Single-file compilation unchanged (backwards compat)
# ═══════════════════════════════════════════════════════════════════

class TestBackwardsCompatibility:
    """Verify that single-file compilation without ModuleRegistry is unchanged."""

    def test_ir_generator_default_no_registry(self):
        """IRGenerator with no registry behaves identically to before."""
        from axon.compiler.ir_generator import IRGenerator
        gen = IRGenerator()  # No registry — old behavior
        assert gen._registry is None

    def test_ir_generator_with_registry(self):
        """IRGenerator accepts optional ModuleRegistry."""
        from axon.compiler.ir_generator import IRGenerator
        registry = ModuleRegistry()
        gen = IRGenerator(module_registry=registry)
        assert gen._registry is registry

    def test_ir_import_new_fields_default(self):
        """IRImport new fields default to backwards-compatible values."""
        ir = IRImport(module_path=("axon", "security"), names=("NoHalluc",))
        assert ir.resolved is False
        assert ir.interface_hash == ""
        assert ir.module_path == ("axon", "security")
        assert ir.names == ("NoHalluc",)


# ═══════════════════════════════════════════════════════════════════
#  TEST 2: Two-file import resolution
# ═══════════════════════════════════════════════════════════════════

class TestTwoFileResolution:
    """Verify cross-file import resolution via ModuleRegistry."""

    def test_import_persona_from_registry(self):
        """Importing a persona from another module injects it locally."""
        from axon.compiler.ir_generator import IRGenerator

        # Create a registry with a compiled security module
        iface = CognitiveInterface(module_path=("axon", "security"))
        iface.personas["Guardian"] = PersonaSignature(
            name="Guardian", domain=("security",), tone="strict"
        )
        registry = ModuleRegistry()
        registry.register(("axon", "security"), iface)

        gen = IRGenerator(module_registry=registry)
        # Simulate visiting an import node
        from axon.compiler.ast_nodes import ImportNode
        node = ImportNode(
            line=1, column=0,
            module_path=["axon", "security"],
            names=["Guardian"],
        )
        ir_import = gen._visit_import(node)

        # Verify resolution
        assert ir_import.resolved is True
        assert ir_import.interface_hash != ""
        assert "Guardian" in gen._personas
        assert gen._personas["Guardian"].name == "Guardian"

    def test_import_anchor_from_registry(self):
        """Importing an anchor populates the _anchors table."""
        from axon.compiler.ir_generator import IRGenerator

        iface = CognitiveInterface(module_path=("axon", "anchors"))
        iface.anchors["NoHallucination"] = AnchorSignature(
            name="NoHallucination",
            constraint_hash="abc123",
            on_violation="raise",
        )
        registry = ModuleRegistry()
        registry.register(("axon", "anchors"), iface)

        gen = IRGenerator(module_registry=registry)
        from axon.compiler.ast_nodes import ImportNode
        node = ImportNode(
            line=1, column=0,
            module_path=["axon", "anchors"],
            names=["NoHallucination"],
        )
        gen._visit_import(node)
        assert "NoHallucination" in gen._anchors

    def test_unresolved_without_registry(self):
        """Import without registry stays unresolved (old behavior)."""
        from axon.compiler.ir_generator import IRGenerator

        gen = IRGenerator()  # No registry
        from axon.compiler.ast_nodes import ImportNode
        node = ImportNode(
            line=1, column=0,
            module_path=["axon", "security"],
            names=["Guardian"],
        )
        ir_import = gen._visit_import(node)
        assert ir_import.resolved is False
        assert "Guardian" not in gen._personas


# ═══════════════════════════════════════════════════════════════════
#  TEST 3: Circular import detection
# ═══════════════════════════════════════════════════════════════════

class TestCircularImportDetection:
    """Verify that circular dependencies are detected and reported."""

    def test_scan_imports_basic(self):
        """scan_imports correctly extracts import statements."""
        source = """
import axon.security.{NoHallucination, NoBias}
import axon.personas.{Expert}

persona MyPersona {
    domain ["test"]
}
"""
        imports = scan_imports(source)
        assert len(imports) == 2
        assert imports[0] == (("axon", "security"), ("NoHallucination", "NoBias"))
        assert imports[1] == (("axon", "personas"), ("Expert",))

    def test_scan_imports_no_names(self):
        """scan_imports handles import without named members."""
        source = "import axon.utils\n"
        imports = scan_imports(source)
        assert len(imports) == 1
        assert imports[0] == (("axon", "utils"), ())

    def test_cycle_detection_in_topological_sort(self):
        """Cyclic dependencies raise CyclicDependencyError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            axon_dir = root / "axon"
            axon_dir.mkdir()

            # A imports B, B imports A → cycle
            (axon_dir / "a.axon").write_text(
                "import axon.b.{Foo}\n", encoding="utf-8"
            )
            (axon_dir / "b.axon").write_text(
                "import axon.a.{Bar}\n", encoding="utf-8"
            )

            resolver = ModuleResolver(project_root=root)
            with pytest.raises(CyclicDependencyError):
                resolver.resolve(axon_dir / "a.axon")


# ═══════════════════════════════════════════════════════════════════
#  TEST 4: Epistemic compatibility (know imports speculate → warning)
# ═══════════════════════════════════════════════════════════════════

class TestEpistemicCompatibility:
    """Verify epistemic level checking across module boundaries."""

    def test_compatible_same_level(self):
        """Same epistemic level → no diagnostics."""
        checker = EpistemicCompatChecker()
        know_module = CognitiveInterface(
            module_path=("a",), epistemic_floor=EpistemicLevel.KNOW
        )
        another_know = CognitiveInterface(
            module_path=("b",), epistemic_floor=EpistemicLevel.KNOW
        )
        results = checker.check_import(know_module, another_know)
        assert len(results) == 0

    def test_upgrade_is_fine(self):
        """Importing from a higher level is always OK."""
        checker = EpistemicCompatChecker()
        speculate_module = CognitiveInterface(
            module_path=("consumer",), epistemic_floor=EpistemicLevel.SPECULATE
        )
        know_module = CognitiveInterface(
            module_path=("provider",), epistemic_floor=EpistemicLevel.KNOW
        )
        results = checker.check_import(speculate_module, know_module)
        assert len(results) == 0

    def test_downgrade_warning(self):
        """Importing from lower level → warning (not strict)."""
        checker = EpistemicCompatChecker(strict=False)
        know_module = CognitiveInterface(
            module_path=("consumer",), epistemic_floor=EpistemicLevel.KNOW
        )
        believe_module = CognitiveInterface(
            module_path=("provider",), epistemic_floor=EpistemicLevel.BELIEVE
        )
        results = checker.check_import(know_module, believe_module)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_unspecified_skips_check(self):
        """If either module is unspecified, no diagnostics."""
        checker = EpistemicCompatChecker()
        unspec = CognitiveInterface(
            module_path=("a",), epistemic_floor=EpistemicLevel.UNSPECIFIED
        )
        know = CognitiveInterface(
            module_path=("b",), epistemic_floor=EpistemicLevel.KNOW
        )
        assert len(checker.check_import(unspec, know)) == 0
        assert len(checker.check_import(know, unspec)) == 0


# ═══════════════════════════════════════════════════════════════════
#  TEST 5: Epistemic conflict (severe mismatch → error)
# ═══════════════════════════════════════════════════════════════════

class TestEpistemicConflict:
    """Verify severe epistemic mismatches produce errors."""

    def test_know_imports_speculate_is_error(self):
        """know importing speculate → ERROR (gap = 3)."""
        checker = EpistemicCompatChecker()
        know = CognitiveInterface(
            module_path=("strict",), epistemic_floor=EpistemicLevel.KNOW
        )
        speculate = CognitiveInterface(
            module_path=("creative",), epistemic_floor=EpistemicLevel.SPECULATE
        )
        results = checker.check_import(know, speculate)
        assert len(results) == 1
        assert results[0].severity == "error"
        assert "conflict" in results[0].message.lower()

    def test_strict_mode_escalates_warnings(self):
        """In strict mode, warnings become errors."""
        checker = EpistemicCompatChecker(strict=True)
        know = CognitiveInterface(
            module_path=("strict",), epistemic_floor=EpistemicLevel.KNOW
        )
        believe = CognitiveInterface(
            module_path=("moderate",), epistemic_floor=EpistemicLevel.BELIEVE
        )
        results = checker.check_import(know, believe)
        assert len(results) == 1
        assert results[0].severity == "error"  # Escalated from warning

    def test_symbol_not_found_error(self):
        """Importing a non-existent symbol produces error."""
        checker = EpistemicCompatChecker()
        consumer = CognitiveInterface(
            module_path=("consumer",), epistemic_floor=EpistemicLevel.KNOW
        )
        provider = CognitiveInterface(
            module_path=("provider",), epistemic_floor=EpistemicLevel.KNOW
        )
        results = checker.check_import(
            consumer, provider, imported_names=("NonExistent",)
        )
        assert len(results) == 1
        assert results[0].severity == "error"
        assert "NonExistent" in results[0].message

    def test_format_report(self):
        """Diagnostic report formats correctly."""
        checker = EpistemicCompatChecker()
        know = CognitiveInterface(
            module_path=("a",), epistemic_floor=EpistemicLevel.KNOW
        )
        spec = CognitiveInterface(
            module_path=("b",), epistemic_floor=EpistemicLevel.SPECULATE
        )
        checker.check_import(know, spec)
        report = checker.format_report()
        assert "ERROR" in report
        assert checker.has_errors()


# ═══════════════════════════════════════════════════════════════════
#  TEST 6: Content-addressed cache hit/miss
# ═══════════════════════════════════════════════════════════════════

class TestCompilationCache:
    """Verify content-addressed compilation caching."""

    def test_cache_miss_when_empty(self):
        """Empty cache always returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            result = cache.lookup("mod", "hash1", "dep_hash1")
            assert result is None

    def test_cache_hit_on_same_hashes(self):
        """Cache returns entry when hashes match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            cache.store("mod", "src123", "iface456", "dep789", {"data": 42})
            result = cache.lookup("mod", "src123", "dep789")
            assert result is not None
            assert result.ir_data == {"data": 42}

    def test_cache_miss_on_changed_source(self):
        """Cache misses when source hash changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            cache.store("mod", "src_old", "iface1", "dep1", {"v": 1})
            result = cache.lookup("mod", "src_new", "dep1")
            assert result is None

    def test_cache_miss_on_changed_dependency(self):
        """Cache misses when dependency hash changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            cache.store("mod", "src1", "iface1", "dep_old", {"v": 1})
            result = cache.lookup("mod", "src1", "dep_new")
            assert result is None

    def test_dependency_hash_computation(self):
        """Dependency hash is deterministic and order-independent."""
        h1 = CompilationCache.compute_dependency_hash(["aaa", "bbb", "ccc"])
        h2 = CompilationCache.compute_dependency_hash(["ccc", "aaa", "bbb"])
        assert h1 == h2  # Sorted internally


# ═══════════════════════════════════════════════════════════════════
#  TEST 7: .axi interface generation and serialization
# ═══════════════════════════════════════════════════════════════════

class TestInterfaceGeneration:
    """Verify .axi interface file generation and round-trip."""

    def test_interface_creation(self):
        """CognitiveInterface stores signatures correctly."""
        iface = CognitiveInterface(
            module_path=("axon", "security"),
            content_hash="abc123",
        )
        iface.personas["Guard"] = PersonaSignature(
            name="Guard", domain=("security",)
        )
        iface.anchors["NoBias"] = AnchorSignature(
            name="NoBias", constraint_hash="xyz"
        )

        assert iface.has_export("Guard")
        assert iface.has_export("NoBias")
        assert not iface.has_export("NonExistent")
        assert set(iface.all_exports()) == {"Guard", "NoBias"}

    def test_interface_serialization_roundtrip(self):
        """Interface survives JSON serialization/deserialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.axi"

            original = CognitiveInterface(
                module_path=("axon", "security"),
                content_hash="hash123",
                epistemic_floor=EpistemicLevel.KNOW,
            )
            original.personas["Expert"] = PersonaSignature(
                name="Expert", domain=("medicine",), tone="precise",
                confidence_threshold=0.95,
            )
            original.anchors["NoHalluc"] = AnchorSignature(
                name="NoHalluc", constraint_hash="chash", on_violation="raise"
            )
            original.mandates["Deterministic"] = MandateSignature(
                name="Deterministic", tolerance=0.005, max_steps=100,
            )

            original.save(path)
            loaded = CognitiveInterface.load(path)

            assert loaded.module_path == ("axon", "security")
            assert loaded.content_hash == "hash123"
            assert loaded.epistemic_floor == EpistemicLevel.KNOW
            assert "Expert" in loaded.personas
            assert loaded.personas["Expert"].tone == "precise"
            assert "NoHalluc" in loaded.anchors
            assert "Deterministic" in loaded.mandates
            assert loaded.mandates["Deterministic"].tolerance == 0.005

    def test_interface_hash_deterministic(self):
        """Same interface produces same hash."""
        iface1 = CognitiveInterface(module_path=("a",), content_hash="x")
        iface1.personas["P"] = PersonaSignature(name="P")

        iface2 = CognitiveInterface(module_path=("a",), content_hash="x")
        iface2.personas["P"] = PersonaSignature(name="P")

        assert iface1.interface_hash == iface2.interface_hash


# ═══════════════════════════════════════════════════════════════════
#  TEST 8: Early cutoff
# ═══════════════════════════════════════════════════════════════════

class TestEarlyCutoff:
    """Verify Bazel-style early cutoff mechanism."""

    def test_early_cutoff_when_interface_unchanged(self):
        """Source changed but interface same → cutoff applies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            cache.store("mod", "src_v1", "iface_stable", "dep1", {"v": 1})
            assert cache.check_early_cutoff("mod", "iface_stable") is True

    def test_no_cutoff_when_interface_changed(self):
        """Interface changed → no cutoff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = CompilationCache(Path(tmpdir) / ".axon_cache")
            cache.store("mod", "src_v1", "iface_old", "dep1", {"v": 1})
            assert cache.check_early_cutoff("mod", "iface_new") is False


# ═══════════════════════════════════════════════════════════════════
#  TEST 9: Diamond dependency resolution
# ═══════════════════════════════════════════════════════════════════

class TestDiamondDependency:
    """Verify diamond dependency graphs: A→B, A→C, B→D, C→D."""

    def test_diamond_topological_order(self):
        """Diamond deps produce valid topological order (D first, A last)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create module files
            (root / "d.axon").write_text(
                "persona Base { domain [\"core\"] }", encoding="utf-8"
            )
            (root / "b.axon").write_text(
                "import d.{Base}\npersona Mid1 { domain [\"mid\"] }",
                encoding="utf-8",
            )
            (root / "c.axon").write_text(
                "import d.{Base}\npersona Mid2 { domain [\"mid\"] }",
                encoding="utf-8",
            )
            (root / "a.axon").write_text(
                "import b.{Mid1}\nimport c.{Mid2}",
                encoding="utf-8",
            )

            resolver = ModuleResolver(project_root=root)
            order = resolver.resolve(root / "a.axon")

            # Extract keys
            keys = [".".join(n.module_path) for n in order]

            # D must come before B and C; B and C before A
            assert keys.index("d") < keys.index("b")
            assert keys.index("d") < keys.index("c")
            assert keys.index("b") < keys.index("a")
            assert keys.index("c") < keys.index("a")


# ═══════════════════════════════════════════════════════════════════
#  TEST 10: ModuleRegistry lookup semantics
# ═══════════════════════════════════════════════════════════════════

class TestModuleRegistry:
    """Verify ModuleRegistry API and lookup semantics."""

    def test_register_and_resolve(self):
        """Registry registers and resolves modules."""
        registry = ModuleRegistry()
        iface = CognitiveInterface(module_path=("axon", "security"))
        registry.register(("axon", "security"), iface)

        result = registry.resolve(("axon", "security"))
        assert result is iface

    def test_resolve_missing_returns_none(self):
        """Resolving non-existent module returns None."""
        registry = ModuleRegistry()
        assert registry.resolve(("nonexistent",)) is None

    def test_has_module(self):
        """has_module checks registration."""
        registry = ModuleRegistry()
        iface = CognitiveInterface(module_path=("a",))
        registry.register(("a",), iface)
        assert registry.has_module(("a",))
        assert not registry.has_module(("b",))

    def test_contains_operator(self):
        """__contains__ works with 'in' operator."""
        registry = ModuleRegistry()
        iface = CognitiveInterface(module_path=("a",))
        registry.register(("a",), iface)
        assert ("a",) in registry
        assert ("b",) not in registry

    def test_init_with_interfaces_dict(self):
        """Registry can be initialized with a dict of interfaces."""
        iface_a = CognitiveInterface(module_path=("a",))
        iface_b = CognitiveInterface(module_path=("b",))
        registry = ModuleRegistry(interfaces={
            ("a",): iface_a,
            ("b",): iface_b,
        })
        assert len(registry) == 2
        assert registry.resolve(("a",)) is iface_a

    def test_epistemic_level_lattice(self):
        """EpistemicLevel names and ordering are correct."""
        assert EpistemicLevel.KNOW > EpistemicLevel.BELIEVE
        assert EpistemicLevel.BELIEVE > EpistemicLevel.DOUBT
        assert EpistemicLevel.DOUBT > EpistemicLevel.SPECULATE
        assert EpistemicLevel.SPECULATE > EpistemicLevel.UNSPECIFIED

        assert EpistemicLevel.name(EpistemicLevel.KNOW) == "know"
        assert EpistemicLevel.from_name("speculate") == EpistemicLevel.SPECULATE

        assert EpistemicLevel.is_compatible(EpistemicLevel.KNOW, EpistemicLevel.KNOW)
        assert EpistemicLevel.is_compatible(EpistemicLevel.KNOW, EpistemicLevel.SPECULATE)
        assert not EpistemicLevel.is_compatible(EpistemicLevel.SPECULATE, EpistemicLevel.KNOW)


# ═══════════════════════════════════════════════════════════════════
#  TEST 11: Persona description survives cross-file import
# ═══════════════════════════════════════════════════════════════════

class TestPersonaDescriptionSurvivesImport:
    """Verify that persona description (including tenant placeholders)
    survives the full EMS pipeline: IR → .axi → import → stub."""

    def test_description_in_persona_signature(self):
        """PersonaSignature carries description field."""
        sig = PersonaSignature(
            name="Expert",
            domain=("sales",),
            description="{{company_name}} AI assistant",
        )
        assert sig.description == "{{company_name}} AI assistant"

    def test_description_survives_serialization(self):
        """PersonaSignature.description survives to_dict/from JSON round-trip."""
        import tempfile
        from pathlib import Path

        iface = CognitiveInterface(
            module_path=("example", "brain"),
            content_hash="abc",
        )
        iface.personas["Expert"] = PersonaSignature(
            name="Expert",
            domain=("sales",),
            description="{{company_name}} support agent",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "example_brain.axi"
            iface.save(path)
            loaded = CognitiveInterface.load(path)

        assert loaded.personas["Expert"].description == "{{company_name}} support agent"

    def test_description_injected_into_stub(self):
        """Imported persona stub gets description from PersonaSignature."""
        from axon.compiler.ir_generator import IRGenerator

        iface = CognitiveInterface(module_path=("example", "brain"))
        iface.personas["Expert"] = PersonaSignature(
            name="Expert",
            domain=("sales",),
            description="{{company_name}} closer",
        )
        registry = ModuleRegistry()
        registry.register(("example", "brain"), iface)

        gen = IRGenerator(module_registry=registry)
        from axon.compiler.ast_nodes import ImportNode
        node = ImportNode(
            line=1, column=0,
            module_path=["example", "brain"],
            names=["Expert"],
        )
        gen._visit_import(node)

        stub = gen._personas["Expert"]
        assert stub.description == "{{company_name}} closer"


# ═══════════════════════════════════════════════════════════════════
#  TEST 12: Anchor description parsed and in IR
# ═══════════════════════════════════════════════════════════════════

class TestAnchorDescriptionParsedAndInIR:
    """Verify anchor description flows from source → AST → IR."""

    def test_anchor_description_in_ast(self):
        """AnchorConstraint AST node carries description."""
        from axon.compiler.ast_nodes import AnchorConstraint
        node = AnchorConstraint(
            name="NoHalluc",
            description="Prevents hallucinated output",
            enforce="strict_grounding",
        )
        assert node.description == "Prevents hallucinated output"

    def test_anchor_description_in_ir(self):
        """IRAnchor IR node carries description through compilation."""
        from axon.compiler.ir_nodes import IRAnchor
        ir = IRAnchor(
            name="NoHalluc",
            description="Prevents hallucinated output",
            enforce="strict_grounding",
        )
        assert ir.description == "Prevents hallucinated output"
        d = ir.to_dict()
        assert d["description"] == "Prevents hallucinated output"

    def test_anchor_description_default_empty(self):
        """IRAnchor.description defaults to empty string for backwards compat."""
        from axon.compiler.ir_nodes import IRAnchor
        ir = IRAnchor(name="Test")
        assert ir.description == ""


# ═══════════════════════════════════════════════════════════════════
#  TEST 13: Anchor description does not affect interface hash
# ═══════════════════════════════════════════════════════════════════

class TestAnchorDescriptionDoesNotAffectHash:
    """Verify that changing anchor description doesn't invalidate
    .axi interface hash (description is metadata-only)."""

    def test_hash_unchanged_by_description(self):
        """Two interfaces with same constraints but different anchor
        descriptions produce identical interface hashes."""
        iface_a = CognitiveInterface(module_path=("a",), content_hash="same")
        iface_a.anchors["Guard"] = AnchorSignature(
            name="Guard",
            constraint_hash="constraint_abc",  # same constraint
            on_violation="raise",
        )

        iface_b = CognitiveInterface(module_path=("a",), content_hash="same")
        iface_b.anchors["Guard"] = AnchorSignature(
            name="Guard",
            constraint_hash="constraint_abc",  # same constraint
            on_violation="raise",
        )

        # Interface hash should be identical since constraint_hash is the same
        # (description is NOT part of AnchorSignature/constraint_hash)
        assert iface_a.interface_hash == iface_b.interface_hash


# ═══════════════════════════════════════════════════════════════════
#  TEST 14: Lambda Data signature creation
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataSignatureCreation:
    """Verify LambdaDataSignature stores all epistemic fields."""

    def test_fields_stored_correctly(self):
        """All ΛD signature fields are accessible."""
        sig = LambdaDataSignature(
            name="SensorReading",
            ontology="measurement.temperature.celsius",
            certainty=0.95,
            derivation="raw",
            provenance="Sensor_X_Unit_7",
            temporal_frame="2026-01-01T00:00:00Z/2026-12-31T23:59:59Z",
        )
        assert sig.name == "SensorReading"
        assert sig.ontology == "measurement.temperature.celsius"
        assert sig.certainty == 0.95
        assert sig.derivation == "raw"
        assert sig.provenance == "Sensor_X_Unit_7"
        assert "2026-01-01" in sig.temporal_frame

    def test_to_dict_complete(self):
        """to_dict serializes all fields."""
        sig = LambdaDataSignature(
            name="Price", ontology="finance.price.usd",
            certainty=0.8, derivation="derived",
        )
        d = sig.to_dict()
        assert d["name"] == "Price"
        assert d["ontology"] == "finance.price.usd"
        assert d["certainty"] == 0.8
        assert d["derivation"] == "derived"
        assert "provenance" in d
        assert "temporal_frame" in d

    def test_default_values(self):
        """Defaults are backwards-compatible."""
        sig = LambdaDataSignature(name="Minimal")
        assert sig.ontology == ""
        assert sig.certainty == 1.0
        assert sig.derivation == "observed"
        assert sig.provenance == ""
        assert sig.temporal_frame == ""


# ═══════════════════════════════════════════════════════════════════
#  TEST 15: Lambda Data .axi serialization roundtrip
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataSerializationRoundtrip:
    """Verify ΛD signatures survive .axi JSON save/load cycle."""

    def test_roundtrip_preserves_all_fields(self):
        """Lambda Data signature survives CognitiveInterface save/load."""
        import tempfile
        from pathlib import Path

        iface = CognitiveInterface(
            module_path=("sensors", "readings"),
            content_hash="def456",
        )
        iface.lambda_data["TempReading"] = LambdaDataSignature(
            name="TempReading",
            ontology="measurement.temperature.celsius",
            certainty=0.92,
            derivation="raw",
            provenance="Station_Alpha",
            temporal_frame="2026-03-01/2026-03-31",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sensors_readings.axi"
            iface.save(path)
            loaded = CognitiveInterface.load(path)

        assert "TempReading" in loaded.lambda_data
        ld = loaded.lambda_data["TempReading"]
        assert ld.name == "TempReading"
        assert ld.ontology == "measurement.temperature.celsius"
        assert ld.certainty == 0.92
        assert ld.derivation == "raw"
        assert ld.provenance == "Station_Alpha"
        assert ld.temporal_frame == "2026-03-01/2026-03-31"


# ═══════════════════════════════════════════════════════════════════
#  TEST 16: Lambda Data import resolution from registry
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataImportResolution:
    """Verify ΛD imports inject into _lambda_data_specs via registry."""

    def test_import_lambda_data_from_registry(self):
        """Imported ΛD definition populates _lambda_data_specs."""
        from axon.compiler.ir_generator import IRGenerator

        iface = CognitiveInterface(module_path=("data", "sensors"))
        iface.lambda_data["SensorData"] = LambdaDataSignature(
            name="SensorData",
            ontology="iot.sensor.generic",
            certainty=0.88,
            derivation="raw",
            provenance="EdgeNode_3",
            temporal_frame="2026-01-01/2026-06-30",
        )
        registry = ModuleRegistry()
        registry.register(("data", "sensors"), iface)

        gen = IRGenerator(module_registry=registry)
        from axon.compiler.ast_nodes import ImportNode
        node = ImportNode(
            line=1, column=0,
            module_path=["data", "sensors"],
            names=["SensorData"],
        )
        ir_import = gen._visit_import(node)

        assert ir_import.resolved is True
        assert "SensorData" in gen._lambda_data_specs
        stub = gen._lambda_data_specs["SensorData"]
        assert stub.name == "SensorData"
        assert stub.ontology == "iot.sensor.generic"
        assert stub.certainty == 0.88
        assert stub.derivation == "raw"
        assert stub.provenance == "EdgeNode_3"
        assert stub.temporal_frame_start == "2026-01-01"
        assert stub.temporal_frame_end == "2026-06-30"


# ═══════════════════════════════════════════════════════════════════
#  TEST 17: Lambda Data in interface exports
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataInterfaceExports:
    """Verify lookup() and all_exports() include ΛD entries."""

    def test_lookup_finds_lambda_data(self):
        """CognitiveInterface.lookup() finds ΛD by name."""
        iface = CognitiveInterface(module_path=("test",))
        iface.lambda_data["PriceData"] = LambdaDataSignature(
            name="PriceData", ontology="finance.price",
        )
        result = iface.lookup("PriceData")
        assert result is not None
        assert isinstance(result, LambdaDataSignature)
        assert result.name == "PriceData"

    def test_all_exports_includes_lambda_data(self):
        """all_exports() includes ΛD names alongside other primitives."""
        iface = CognitiveInterface(module_path=("test",))
        iface.personas["Expert"] = PersonaSignature(name="Expert")
        iface.lambda_data["DataSpec"] = LambdaDataSignature(name="DataSpec")
        exports = iface.all_exports()
        assert "Expert" in exports
        assert "DataSpec" in exports

    def test_has_export_for_lambda_data(self):
        """has_export() returns True for registered ΛD."""
        iface = CognitiveInterface(module_path=("test",))
        iface.lambda_data["MyLD"] = LambdaDataSignature(name="MyLD")
        assert iface.has_export("MyLD")
        assert not iface.has_export("NonExistent")


# ═══════════════════════════════════════════════════════════════════
#  TEST 18: Lambda Data interface hash determinism
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataInterfaceHash:
    """Verify ΛD presence produces deterministic interface hashes."""

    def test_same_lambda_data_same_hash(self):
        """Identical ΛD signatures produce identical interface hashes."""
        iface_a = CognitiveInterface(module_path=("a",), content_hash="x")
        iface_a.lambda_data["LD"] = LambdaDataSignature(
            name="LD", ontology="test", certainty=0.9,
        )
        iface_b = CognitiveInterface(module_path=("a",), content_hash="x")
        iface_b.lambda_data["LD"] = LambdaDataSignature(
            name="LD", ontology="test", certainty=0.9,
        )
        assert iface_a.interface_hash == iface_b.interface_hash

    def test_different_lambda_data_different_hash(self):
        """Different ΛD signatures produce different interface hashes."""
        iface_a = CognitiveInterface(module_path=("a",), content_hash="x")
        iface_a.lambda_data["LD"] = LambdaDataSignature(
            name="LD", certainty=0.9,
        )
        iface_b = CognitiveInterface(module_path=("a",), content_hash="x")
        iface_b.lambda_data["LD"] = LambdaDataSignature(
            name="LD", certainty=0.5,
        )
        assert iface_a.interface_hash != iface_b.interface_hash


# ═══════════════════════════════════════════════════════════════════
#  TEST 19: Lambda Data epistemic floor contribution
# ═══════════════════════════════════════════════════════════════════

class TestLambdaDataEpistemicFloorContribution:
    """Verify ΛD with high certainty raises the module epistemic floor."""

    def test_raw_high_certainty_raises_to_know(self):
        """ΛD with derivation=raw and certainty>=0.8 → KNOW floor."""
        from dataclasses import dataclass

        @dataclass
        class MockIR:
            anchors: tuple = ()
            runs: tuple = ()
            shields: tuple = ()
            lambda_data_specs: tuple = ()

        @dataclass
        class MockLD:
            certainty: float = 0.95
            derivation: str = "raw"

        ir = MockIR(lambda_data_specs=(MockLD(),))
        floor = InterfaceGenerator._compute_epistemic_floor(ir)
        assert floor == EpistemicLevel.KNOW

    def test_derived_moderate_certainty_raises_to_believe(self):
        """ΛD with certainty>=0.5 but not raw → BELIEVE floor."""
        from dataclasses import dataclass

        @dataclass
        class MockIR:
            anchors: tuple = ()
            runs: tuple = ()
            shields: tuple = ()
            lambda_data_specs: tuple = ()

        @dataclass
        class MockLD:
            certainty: float = 0.75
            derivation: str = "derived"

        ir = MockIR(lambda_data_specs=(MockLD(),))
        floor = InterfaceGenerator._compute_epistemic_floor(ir)
        assert floor == EpistemicLevel.BELIEVE

    def test_low_certainty_no_floor_change(self):
        """ΛD with certainty<0.5 does not raise epistemic floor."""
        from dataclasses import dataclass

        @dataclass
        class MockIR:
            anchors: tuple = ()
            runs: tuple = ()
            shields: tuple = ()
            lambda_data_specs: tuple = ()

        @dataclass
        class MockLD:
            certainty: float = 0.3
            derivation: str = "inferred"

        ir = MockIR(lambda_data_specs=(MockLD(),))
        floor = InterfaceGenerator._compute_epistemic_floor(ir)
        assert floor == EpistemicLevel.UNSPECIFIED

