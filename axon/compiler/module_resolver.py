"""
AXON Compiler — Epistemic Module System: Dependency Resolver
==============================================================
Phase 0 of the EMS compilation pipeline.

Builds a Directed Acyclic Graph (DAG) of .axon file dependencies
by scanning import statements, then returns a topological order
for incremental, cache-friendly compilation.

Design lineage:
  - Zig:     Lazy discovery — only scan imports, not full parse
  - Nix:     Content-addressed nodes for deterministic caching
  - Bazel:   DAG-based execution with early cutoff
  - Backpack: Wiring diagram before type-checking

Pipeline position:
  **ModuleResolver** → InterfaceGenerator → IRGenerator → CompilationCache
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ═══════════════════════════════════════════════════════════════════
#  MODULE NODE — a single .axon file in the dependency graph
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ModuleNode:
    """
    A node in the dependency DAG representing a single .axon file.

    Attributes:
        module_path:  Dotted module path, e.g. ("axon", "security")
        file_path:    Absolute filesystem path to the .axon source
        content_hash: SHA-256 of the source file (Nix-style cache key)
        imports:      List of (module_path, named_imports) tuples
        dependents:   Modules that import THIS module
    """
    module_path: tuple[str, ...]
    file_path: Path
    content_hash: str = ""
    imports: list[tuple[tuple[str, ...], tuple[str, ...]]] = field(
        default_factory=list
    )
    dependents: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  CYCLE ERROR
# ═══════════════════════════════════════════════════════════════════

class CyclicDependencyError(Exception):
    """Raised when the dependency graph contains a cycle."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        path_str = " → ".join(cycle)
        super().__init__(
            f"Cyclic dependency detected in module graph: {path_str}"
        )


class ModuleNotFoundError(Exception):
    """Raised when an imported module cannot be located on disk."""

    def __init__(self, module_path: str, importing_file: str):
        self.module_path = module_path
        self.importing_file = importing_file
        super().__init__(
            f"Module '{module_path}' not found "
            f"(imported by '{importing_file}')"
        )


# ═══════════════════════════════════════════════════════════════════
#  IMPORT SCANNER — fast regex-based import extraction (no full parse)
# ═══════════════════════════════════════════════════════════════════

# Matches:  import axon.security.{NoHallucination, NoBias}
# Groups:   1 = module path (dotted), 2 = named imports (optional)
_IMPORT_RE = re.compile(
    r"^\s*import\s+"
    r"([\w]+(?:\.[\w]+)*)"       # group 1: dotted module path
    r"(?:\.\{([^}]+)\})?"        # group 2: optional {Name1, Name2}
    r"\s*$",
    re.MULTILINE,
)


def scan_imports(source: str) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """
    Fast-scan a .axon source for import statements without full parsing.

    This is the Zig-inspired approach: we only need import declarations
    to build the dependency DAG, so we skip the full lexer/parser.

    Returns:
        List of (module_path_parts, named_imports) tuples.
    """
    results: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for match in _IMPORT_RE.finditer(source):
        path_str = match.group(1)
        names_str = match.group(2)

        path_parts = tuple(path_str.split("."))
        names = tuple(
            n.strip() for n in names_str.split(",")
        ) if names_str else ()

        results.append((path_parts, names))

    return results


def _content_hash(source: str) -> str:
    """SHA-256 content hash of a source file (Nix-style cache key)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════
#  MODULE RESOLVER — build the dependency DAG
# ═══════════════════════════════════════════════════════════════════

class ModuleResolver:
    """
    Discovers .axon file dependencies and produces a topological
    compilation order.

    Usage:
        resolver = ModuleResolver(project_root=Path("./my_project"))
        order = resolver.resolve(Path("main.axon"))
        for module_node in order:
            compile(module_node)

    The resolver supports multiple search paths for locating modules:
      1. Project root directory (user code)
      2. Standard library path (axon.* built-ins)

    Module path → file path mapping:
      import axon.security.{NoHallucination}
      → searches: project_root/axon/security.axon
      →           stdlib_path/axon/security.axon
    """

    def __init__(
        self,
        project_root: Path,
        stdlib_path: Path | None = None,
    ):
        self.project_root = project_root
        self.stdlib_path = stdlib_path or project_root
        self._nodes: dict[str, ModuleNode] = {}
        self._adjacency: dict[str, list[str]] = {}

    def resolve(self, entry_file: Path) -> list[ModuleNode]:
        """
        Build the dependency DAG from an entry file and return
        a topological compilation order (leaves first).

        Args:
            entry_file: Path to the root .axon file.

        Returns:
            List of ModuleNodes in topological order (dependencies
            before dependents — compile in this order).

        Raises:
            CyclicDependencyError: If circular imports are detected.
            ModuleNotFoundError: If an imported module is not found.
        """
        self._nodes.clear()
        self._adjacency.clear()

        # Phase 1: Discover all reachable modules (BFS)
        self._discover(entry_file)

        # Phase 2: Topological sort with cycle detection
        return self._topological_sort()

    # ── Phase 1: BFS Discovery ─────────────────────────────────

    def _discover(self, entry_file: Path) -> None:
        """BFS through import statements to discover all reachable modules."""
        entry_key = self._file_to_key(entry_file)
        queue: list[tuple[str, Path]] = [(entry_key, entry_file)]
        visited: set[str] = set()

        while queue:
            key, file_path = queue.pop(0)
            if key in visited:
                continue
            visited.add(key)

            source = file_path.read_text(encoding="utf-8")
            imports = scan_imports(source)

            node = ModuleNode(
                module_path=tuple(key.split(".")),
                file_path=file_path,
                content_hash=_content_hash(source),
                imports=imports,
            )
            self._nodes[key] = node
            self._adjacency[key] = []

            for module_path, _names in imports:
                dep_key = ".".join(module_path)
                self._adjacency[key].append(dep_key)

                if dep_key not in visited:
                    dep_file = self._locate_module(module_path, file_path)
                    queue.append((dep_key, dep_file))

    # ── Phase 2: Topological Sort (Kahn's algorithm) ───────────

    def _topological_sort(self) -> list[ModuleNode]:
        """
        Kahn's algorithm for topological sorting with cycle detection.

        Returns modules in dependency-first order: if A imports B,
        B appears before A in the output.
        """
        # Compute in-degrees
        in_degree: dict[str, int] = {k: 0 for k in self._nodes}
        for key, deps in self._adjacency.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0)
                    # key depends on dep, so dep must come first
                    # in_degree counts how many point INTO a node
                    pass

        # Recompute correctly: edge (A → B) means A depends on B
        # For Kahn's, in_degree[X] = number of nodes that X depends on
        # Wait — standard topological sort: edges go from dependency to dependent
        # Our adjacency: A → [B, C] means A imports B and C
        # In topological order, B and C come before A
        # So reversed edges: B → A, C → A
        # In-degree for topological: count reversed incoming edges

        reverse_in: dict[str, int] = {k: 0 for k in self._nodes}
        for key, deps in self._adjacency.items():
            # key imports each dep → in topological order, key comes after deps
            # So key has in-degree += 1 for each dep
            reverse_in[key] = len(
                [d for d in deps if d in self._nodes]
            )

        # Start with nodes that have no dependencies
        queue: list[str] = [
            k for k, deg in reverse_in.items() if deg == 0
        ]
        result: list[ModuleNode] = []

        while queue:
            key = queue.pop(0)
            result.append(self._nodes[key])

            # Find all nodes that depend on 'key' and reduce their in-degree
            for other_key, deps in self._adjacency.items():
                if key in deps and other_key in reverse_in:
                    reverse_in[other_key] -= 1
                    if reverse_in[other_key] == 0:
                        queue.append(other_key)

        if len(result) != len(self._nodes):
            # Cycle detected — find it for error reporting
            remaining = set(self._nodes.keys()) - {
                ".".join(n.module_path) for n in result
            }
            raise CyclicDependencyError(sorted(remaining))

        return result

    # ── Utility ────────────────────────────────────────────────

    def _locate_module(
        self, module_path: tuple[str, ...], importing_file: Path
    ) -> Path:
        """
        Resolve a dotted module path to a filesystem path.

        Search order:
          1. Relative to project root
          2. Relative to stdlib path
        """
        relative = Path(*module_path[:-1]) / f"{module_path[-1]}.axon"

        # Search project root first
        candidate = self.project_root / relative
        if candidate.exists():
            return candidate

        # Then stdlib
        candidate = self.stdlib_path / relative
        if candidate.exists():
            return candidate

        raise ModuleNotFoundError(
            ".".join(module_path),
            str(importing_file),
        )

    @staticmethod
    def _file_to_key(file_path: Path) -> str:
        """Convert a file path to a dotted module key."""
        return file_path.stem

    def get_node(self, module_key: str) -> ModuleNode | None:
        """Retrieve a module node by its dotted key."""
        return self._nodes.get(module_key)

    def get_dependents(self, module_key: str) -> list[str]:
        """Get all modules that depend on the given module."""
        dependents = []
        for key, deps in self._adjacency.items():
            if module_key in deps:
                dependents.append(key)
        return dependents

    def __iter__(self) -> Iterator[ModuleNode]:
        """Iterate over all discovered modules."""
        return iter(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)
