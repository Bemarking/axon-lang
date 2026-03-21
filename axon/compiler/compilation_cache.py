"""
AXON Compiler — Epistemic Module System: Compilation Cache
=============================================================
Content-addressed compilation cache with early cutoff.

Design lineage:
  - Nix:    Content-addressed derivations — hash inputs → deterministic output
  - Bazel:  Action cache + Content-Addressable Storage (CAS)
  - GHC:    ABI hash in .hi files — recompile only if interface changes

Key insight (Nix):
  Cache key = SHA-256(source_content + imported_interface_hashes)
  If ANY dependency's interface changes, we recompile.
  If a source changes but its .axi interface is identical → early cutoff.

Pipeline position:
  ModuleResolver → InterfaceGenerator → IRGenerator → **CompilationCache**
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  CACHE ENTRY — metadata for a cached compilation unit
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    """
    A single cached compilation result.

    Stores the content hash at compilation time, the interface hash
    (for early cutoff), and the serialized IR program.
    """
    source_hash: str = ""          # SHA-256 of source file
    interface_hash: str = ""       # SHA-256 of .axi interface (for cutoff)
    dependency_hash: str = ""      # Combined hash of all dependency interfaces
    timestamp: float = 0.0        # Unix timestamp of cache creation
    ir_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "interface_hash": self.interface_hash,
            "dependency_hash": self.dependency_hash,
            "timestamp": self.timestamp,
            "ir_data": self.ir_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        return cls(
            source_hash=data.get("source_hash", ""),
            interface_hash=data.get("interface_hash", ""),
            dependency_hash=data.get("dependency_hash", ""),
            timestamp=data.get("timestamp", 0.0),
            ir_data=data.get("ir_data", {}),
        )


# ═══════════════════════════════════════════════════════════════════
#  COMPILATION CACHE
# ═══════════════════════════════════════════════════════════════════

class CompilationCache:
    """
    Content-addressed compilation cache for incremental builds.

    Cache hierarchy:
      .axon_cache/
        ├── interfaces/          # .axi interface files (Phase 1)
        │   └── axon.security.axi
        ├── ir/                  # Serialized IR programs (Phase 3)
        │   └── <content_hash>.json
        └── manifest.json        # Cache manifest with entry metadata

    Cache invalidation rules (Nix-style):
      1. Source hash changed → full recompile
      2. Dependency interface hash changed → full recompile
      3. Source hash same AND dep hashes same → cache hit
      4. Source changed BUT interface hash same → early cutoff
         (downstream dependents don't recompile)
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path(".axon_cache")
        self._manifest: dict[str, CacheEntry] = {}
        self._load_manifest()

    # ── Public API ────────────────────────────────────────────

    def lookup(
        self,
        module_key: str,
        source_hash: str,
        dependency_hash: str,
    ) -> CacheEntry | None:
        """
        Look up a cached compilation result.

        Args:
            module_key:      Dotted module path (e.g. "axon.security")
            source_hash:     SHA-256 of the current source file
            dependency_hash: Combined hash of all dependency interfaces

        Returns:
            CacheEntry if cache hit, None if cache miss.
        """
        entry = self._manifest.get(module_key)
        if entry is None:
            return None

        # Both source AND dependency hashes must match
        if (entry.source_hash == source_hash
                and entry.dependency_hash == dependency_hash):
            return entry

        return None  # Cache miss — invalidated

    def store(
        self,
        module_key: str,
        source_hash: str,
        interface_hash: str,
        dependency_hash: str,
        ir_data: dict[str, Any],
    ) -> CacheEntry:
        """
        Store a compiled IR result in the cache.

        Args:
            module_key:      Dotted module path
            source_hash:     SHA-256 of source file
            interface_hash:  SHA-256 of generated .axi interface
            dependency_hash: Combined hash of dependency interfaces
            ir_data:         Serialized IRProgram dict

        Returns:
            The created CacheEntry.
        """
        entry = CacheEntry(
            source_hash=source_hash,
            interface_hash=interface_hash,
            dependency_hash=dependency_hash,
            timestamp=time.time(),
            ir_data=ir_data,
        )
        self._manifest[module_key] = entry

        # Write IR data to content-addressed file
        ir_dir = self.cache_dir / "ir"
        ir_dir.mkdir(parents=True, exist_ok=True)
        ir_file = ir_dir / f"{source_hash[:16]}.json"
        ir_file.write_text(
            json.dumps(ir_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        self._save_manifest()
        return entry

    def check_early_cutoff(
        self,
        module_key: str,
        new_interface_hash: str,
    ) -> bool:
        """
        GHC/Bazel early cutoff check.

        If a source file changed but its interface hash is identical
        to the cached version, downstream dependents DON'T need
        recompilation.

        Args:
            module_key:          Dotted module path
            new_interface_hash:  Interface hash of the recompiled module

        Returns:
            True if early cutoff applies (interface unchanged).
        """
        entry = self._manifest.get(module_key)
        if entry is None:
            return False
        return entry.interface_hash == new_interface_hash

    def invalidate(self, module_key: str) -> None:
        """Remove a module from the cache."""
        if module_key in self._manifest:
            del self._manifest[module_key]
            self._save_manifest()

    def clear(self) -> None:
        """Clear the entire cache."""
        self._manifest.clear()
        if self.cache_dir.exists():
            import shutil
            shutil.rmtree(self.cache_dir)

    @property
    def size(self) -> int:
        """Number of cached modules."""
        return len(self._manifest)

    # ── Dependency Hash Computation ───────────────────────────

    @staticmethod
    def compute_dependency_hash(
        interface_hashes: list[str],
    ) -> str:
        """
        Compute a combined dependency hash from interface hashes.

        Nix insight: the cache key includes ALL transitive dependency
        interfaces, so any change anywhere in the dependency tree
        invalidates downstream caches.
        """
        combined = "|".join(sorted(interface_hashes))
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    # ── Manifest I/O ──────────────────────────────────────────

    def _load_manifest(self) -> None:
        """Load cache manifest from disk."""
        manifest_path = self.cache_dir / "manifest.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._manifest = {
                    k: CacheEntry.from_dict(v)
                    for k, v in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self._manifest = {}

    def _save_manifest(self) -> None:
        """Persist cache manifest to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.cache_dir / "manifest.json"
        data = {k: v.to_dict() for k, v in self._manifest.items()}
        manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
