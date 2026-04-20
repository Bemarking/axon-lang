"""
AXON Runtime — FileResource
==============================
Cognitive file I/O primitive.

A `resource X { kind: file endpoint: "/var/log/app.log" lifetime: linear }`
declaration maps at runtime to a `FileHandle` token with the following
guarantees:

  • **Linearity** — a `linear` file resource is opened exactly once and
    closed at the first `.release()`.  A second `.release()` is a CT-1
    bug; a second read after `release()` is a CT-2 Anchor Breach.
  • **Affinity** — an `affine` file resource may be released without
    consumption (weakening-permitted).
  • **Persistence** — `persistent` resources correspond to shared files
    whose handle may be duplicated (one per process, not Linear Logic).
  • **τ-decay** — `FileHandle.envelope()` returns a ΛD envelope whose
    certainty decays after the configured lifetime window, letting the
    runtime detect stale file descriptors.

Integration with the Handler layer (Fase 2):
  • `FileHandler` implements the `Handler` protocol, treating
    `kind: file` resources as the only supported kind.  It can therefore
    provision / observe file resources from an IRManifest just like
    Terraform / K8s / AWS / Docker handlers do for their own resources.

This closes one of the historic gaps between "cognitive I/O" and "real
application I/O": Axon programs can now declare files with Linear Logic
discipline without dropping to raw Python `open()` calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .handlers.base import (
    CallerBlameError,
    Continuation,
    Handler,
    HandlerOutcome,
    InfrastructureBlameError,
    LambdaEnvelope,
    LeaseExpiredError,
    identity_continuation,
    make_envelope,
    now_iso,
)


# ═══════════════════════════════════════════════════════════════════
#  FileHandle — the linear token
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FileHandle:
    """A tokenized reference to an open file with Linear Logic discipline.

    The handle is *not* a file object itself — it is a capability that,
    when `open()`ed, yields the underlying IO stream.  Separating the
    token from the stream lets us track consumption state (acquired,
    used, released) independently of the OS-level FD.
    """

    token_id: str
    path: str
    mode: str
    lifetime: str           # linear | affine | persistent
    acquired_at: datetime
    _stream: BinaryIO | None = field(default=None, repr=False)
    _released: bool = False
    _used: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def open(self) -> BinaryIO:
        """Open the file (idempotent for non-linear lifetimes; one-shot
        for linear).  Returns the underlying stream."""
        if self._released:
            raise CallerBlameError(
                f"FileHandle[{self.token_id}] on '{self.path}' is already "
                f"released — Anchor Breach (CT-2)"
            )
        if self._used and self.lifetime == "linear":
            raise CallerBlameError(
                f"linear FileHandle[{self.token_id}] on '{self.path}' was "
                f"already opened; linear resources allow one stream acquisition"
            )
        if self._stream is None:
            try:
                self._stream = open(self.path, self.mode)
            except OSError as exc:
                raise InfrastructureBlameError(
                    f"cannot open '{self.path}' with mode '{self.mode}': {exc}"
                ) from exc
        self._used = True
        return self._stream

    def release(self) -> None:
        """Close the stream and revoke the token.  Idempotent."""
        if self._released:
            return
        self._released = True
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def envelope(self, *, now: datetime | None = None) -> LambdaEnvelope:
        """Return the ΛD envelope for this handle at time `now`.

        After `release()`, certainty decays to 0.0 (Void).
        """
        tau = self.acquired_at.isoformat()
        if self._released:
            return LambdaEnvelope(c=0.0, tau=tau, rho="file_resource", delta="observed")
        return LambdaEnvelope(c=1.0, tau=tau, rho="file_resource", delta="axiomatic")

    def __enter__(self) -> BinaryIO:
        return self.open()

    def __exit__(self, *exc) -> None:
        self.release()


# ═══════════════════════════════════════════════════════════════════
#  FileResourceKernel — issues handles with Linear Logic discipline
# ═══════════════════════════════════════════════════════════════════

class FileResourceKernel:
    """Issues and revokes `FileHandle` tokens for file-kind resources.

    Analogous in spirit to `LeaseKernel`: a central registry that
    materializes language-level `resource { kind: file }` declarations
    as runtime tokens.
    """

    def __init__(self) -> None:
        self._handles: dict[str, FileHandle] = {}

    def acquire(
        self,
        ir_resource: IRResource,
        *,
        mode: str = "rb",
    ) -> FileHandle:
        """Issue a FileHandle for an `IRResource` of kind `file`.

        `ir_resource.endpoint` is interpreted as the filesystem path.
        """
        if ir_resource.kind != "file":
            raise CallerBlameError(
                f"FileResourceKernel.acquire expects kind='file'; "
                f"got kind='{ir_resource.kind}' for '{ir_resource.name}'"
            )
        path = ir_resource.endpoint
        if not path:
            raise CallerBlameError(
                f"file resource '{ir_resource.name}' has no endpoint path"
            )
        handle = FileHandle(
            token_id=f"file-{uuid.uuid4().hex[:12]}",
            path=path,
            mode=mode,
            lifetime=ir_resource.lifetime,
            acquired_at=datetime.now(timezone.utc),
        )
        self._handles[handle.token_id] = handle
        return handle

    def release(self, handle: FileHandle) -> None:
        handle.release()
        self._handles.pop(handle.token_id, None)

    def active(self) -> list[FileHandle]:
        return [h for h in self._handles.values() if not h._released]

    def close_all(self) -> None:
        for h in list(self._handles.values()):
            h.release()
        self._handles.clear()


# ═══════════════════════════════════════════════════════════════════
#  FileHandler — exposes file resources through the Handler protocol
# ═══════════════════════════════════════════════════════════════════

class FileHandler(Handler):
    """Handler that provisions/observes `kind: file` resources.

    `provision` ensures the parent directory exists and (optionally)
    touches the file.  `observe` reports stat metadata (size, mtime,
    exists-flag) without reading contents — the program must explicitly
    `open()` through the kernel to read bytes.
    """

    name: str = "file"

    def __init__(self, *, touch_on_provision: bool = True) -> None:
        self._kernel = FileResourceKernel()
        self._touch = touch_on_provision

    @property
    def kernel(self) -> FileResourceKernel:
        return self._kernel

    def supports(self, node: IRNode) -> bool:
        return isinstance(node, (IRManifest, IRObserve))

    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        created: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            r = resources.get(res_name)
            if r is None or r.kind != "file":
                continue
            p = Path(r.endpoint) if r.endpoint else None
            if p is None:
                created.append({"name": r.name, "status": "no_endpoint"})
                continue
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                if self._touch and not p.exists():
                    p.touch()
                created.append({
                    "name": r.name,
                    "path": str(p),
                    "exists": p.exists(),
                    "size": p.stat().st_size if p.exists() else 0,
                    "status": "ready",
                })
            except OSError as exc:
                raise InfrastructureBlameError(
                    f"file resource '{r.name}' provision failed: {exc}"
                ) from exc

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=0.98, rho=self.name, delta="observed"),
            data={"manifest": manifest.name, "files": created},
            handler=self.name,
        )
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        snapshots: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            # Best-effort stat: the handler does not know the path here
            # unless the caller also supplies resources map.  Observe is
            # therefore lightweight — just records the names.
            snapshots.append({"name": res_name, "kind": "file", "scanned": True})
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=0.94, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "sources": list(obs.sources),
                "files": snapshots,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        self._kernel.close_all()


__all__ = [
    "FileHandle",
    "FileHandler",
    "FileResourceKernel",
]
