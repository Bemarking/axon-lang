"""
AXON Runtime — TerraformHandler
=================================
Interprets the Intention Tree against a Terraform backend.

The handler generates HCL from an `IRManifest`, materializes it in a
workspace directory, drives `terraform init`, `terraform apply -auto-approve`,
and parses `terraform show -json` to produce `HandlerOutcome`s.

This is one of the two reference handlers required by the Fase 2 acceptance
criterion:

    Un programa Axon aprovisiona una VPC real vía Terraform handler sin
    acoplarse a Terraform (mismo programa corre con handler AWS-SDK).

The handler supports two provider back-ends out of the box — `aws` and
`kubernetes` — because those are the two providers Axon's initial target
markets (banca, gobierno, medicina) already rely on.  Additional providers
are a Fase 2.x extension, not a redesign, because the HCL generator is a
pure function of `IRResource.kind`.

Design anchors:
  • D1 — Handler is a β-reduction site.  The HCL text it emits is a
         concrete proof term of the Intention Tree.
  • D4 — Terraform network or backend errors are re-raised as CT-3
         (`NetworkPartitionError` when the failure mode is connectivity;
         `InfrastructureBlameError` for credential / quota failures).
  • D5 — The emitted HCL is the evaluated form of λ-L-E; validation at
         `terraform plan` time is an external proof checker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
    CalleeBlameError,
    CallerBlameError,
    Continuation,
    Handler,
    HandlerOutcome,
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
)


DEFAULT_TERRAFORM_BIN = "terraform"


# ═══════════════════════════════════════════════════════════════════
#  HCL GENERATION — pure functions from IR to Terraform source
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HclDocument:
    """Concrete Terraform source text + the expected output identifiers."""
    text: str
    output_keys: tuple[str, ...]


_AWS_KIND_MAP: dict[str, str] = {
    "postgres": "aws_db_instance",
    "redis":    "aws_elasticache_cluster",
    "s3":       "aws_s3_bucket",
    "vpc":      "aws_vpc",
    "compute":  "aws_instance",
    "custom":   "null_resource",
}

_K8S_KIND_MAP: dict[str, str] = {
    "postgres": "kubernetes_deployment",
    "redis":    "kubernetes_deployment",
    "compute":  "kubernetes_deployment",
    "custom":   "kubernetes_deployment",
}


def _ident(name: str) -> str:
    """Sanitize an Axon identifier to a Terraform-safe resource name."""
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name).lower()


def _provider_block(fabric: IRFabric | None) -> str:
    if fabric is None or fabric.provider == "":
        return ""
    if fabric.provider == "aws":
        region = fabric.region or "us-east-1"
        return f'provider "aws" {{\n  region = "{region}"\n}}\n'
    if fabric.provider == "kubernetes":
        return 'provider "kubernetes" {}\n'
    # Unknown provider — no provider block.  Terraform will fall back to
    # environment defaults.  This is intentional: Axon does not presume the
    # operator's Terraform configuration.
    return ""


def _resource_block_aws(resource: IRResource) -> tuple[str, str]:
    """Emit an AWS resource block. Returns (hcl_text, output_key)."""
    tf_type = _AWS_KIND_MAP.get(resource.kind, "null_resource")
    tf_name = _ident(resource.name)

    if tf_type == "aws_vpc":
        hcl = (
            f'resource "aws_vpc" "{tf_name}" {{\n'
            f'  cidr_block = "10.0.0.0/16"\n'
            f'  tags = {{ Name = "{resource.name}", ManagedBy = "axon" }}\n'
            f'}}\n'
        )
        return hcl, f"aws_vpc.{tf_name}.id"

    if tf_type == "aws_s3_bucket":
        safe_bucket = f"axon-{tf_name}"[:63]
        hcl = (
            f'resource "aws_s3_bucket" "{tf_name}" {{\n'
            f'  bucket = "{safe_bucket}"\n'
            f'  tags = {{ ManagedBy = "axon" }}\n'
            f'}}\n'
        )
        return hcl, f"aws_s3_bucket.{tf_name}.id"

    if tf_type == "aws_db_instance":
        hcl = (
            f'resource "aws_db_instance" "{tf_name}" {{\n'
            f'  identifier          = "{tf_name}"\n'
            f'  engine              = "postgres"\n'
            f'  instance_class      = "db.t3.micro"\n'
            f'  allocated_storage   = 20\n'
            f'  skip_final_snapshot = true\n'
            f'  username            = "axon_admin"\n'
            f'  password            = "CHANGE_ME_BEFORE_USE"\n'
            f'  tags = {{ ManagedBy = "axon" }}\n'
            f'}}\n'
        )
        return hcl, f"aws_db_instance.{tf_name}.id"

    if tf_type == "aws_elasticache_cluster":
        hcl = (
            f'resource "aws_elasticache_cluster" "{tf_name}" {{\n'
            f'  cluster_id      = "{tf_name}"\n'
            f'  engine          = "redis"\n'
            f'  node_type       = "cache.t3.micro"\n'
            f'  num_cache_nodes = 1\n'
            f'}}\n'
        )
        return hcl, f"aws_elasticache_cluster.{tf_name}.id"

    if tf_type == "aws_instance":
        hcl = (
            f'resource "aws_instance" "{tf_name}" {{\n'
            f'  ami           = "ami-0c02fb55956c7d316"\n'  # Amazon Linux 2 (us-east-1 example)
            f'  instance_type = "t3.micro"\n'
            f'  tags = {{ Name = "{resource.name}", ManagedBy = "axon" }}\n'
            f'}}\n'
        )
        return hcl, f"aws_instance.{tf_name}.id"

    # Fallback: null_resource for unknown kinds.
    hcl = (
        f'resource "null_resource" "{tf_name}" {{\n'
        f'  triggers = {{ axon_kind = "{resource.kind}" }}\n'
        f'}}\n'
    )
    return hcl, f"null_resource.{tf_name}.id"


def _resource_block_k8s(resource: IRResource) -> tuple[str, str]:
    """Emit a Kubernetes resource block."""
    tf_name = _ident(resource.name)
    image = {
        "postgres": "postgres:16",
        "redis":    "redis:7",
        "compute":  "alpine:3.20",
    }.get(resource.kind, "alpine:3.20")
    replicas = 1 if resource.capacity is None else max(1, min(resource.capacity, 10))
    hcl = (
        f'resource "kubernetes_deployment" "{tf_name}" {{\n'
        f'  metadata {{\n'
        f'    name   = "{tf_name}"\n'
        f'    labels = {{ app = "{tf_name}" }}\n'
        f'  }}\n'
        f'  spec {{\n'
        f'    replicas = {replicas}\n'
        f'    selector {{ match_labels = {{ app = "{tf_name}" }} }}\n'
        f'    template {{\n'
        f'      metadata {{ labels = {{ app = "{tf_name}" }} }}\n'
        f'      spec {{\n'
        f'        container {{\n'
        f'          name  = "{tf_name}"\n'
        f'          image = "{image}"\n'
        f'        }}\n'
        f'      }}\n'
        f'    }}\n'
        f'  }}\n'
        f'}}\n'
    )
    return hcl, f"kubernetes_deployment.{tf_name}.id"


def _resource_block_for_provider(
    resource: IRResource, provider: str
) -> tuple[str, str]:
    if provider == "aws":
        return _resource_block_aws(resource)
    if provider == "kubernetes":
        return _resource_block_k8s(resource)
    # Unknown provider — default to null_resource stand-in.
    tf_name = _ident(resource.name)
    hcl = (
        f'resource "null_resource" "{tf_name}" {{\n'
        f'  triggers = {{ axon_kind = "{resource.kind}" }}\n'
        f'}}\n'
    )
    return hcl, f"null_resource.{tf_name}.id"


def generate_hcl(
    manifest: IRManifest,
    resources: dict[str, IRResource],
    fabrics: dict[str, IRFabric],
) -> HclDocument:
    """
    Pure function: (manifest, resources, fabrics) → Terraform HCL source.

    The output is deterministic so that golden-text tests remain stable
    across runs.  Resources unknown to the manifest are skipped (the type
    checker already rejected such programs; this is defense in depth).
    """
    fabric = fabrics.get(manifest.fabric_ref) if manifest.fabric_ref else None
    provider = fabric.provider if fabric else "aws"

    output_keys: list[str] = []
    blocks: list[str] = []

    provider_block = _provider_block(fabric)
    if provider_block:
        blocks.append(provider_block)

    for res_name in manifest.resources:
        resource = resources.get(res_name)
        if resource is None:
            continue
        hcl, out = _resource_block_for_provider(resource, provider)
        blocks.append(hcl)
        output_keys.append(out)

    # Emit outputs so `terraform show -json` surfaces our resource IDs.
    for key in output_keys:
        safe = key.replace(".", "_")
        blocks.append(
            f'output "{safe}" {{\n'
            f'  value = {key}\n'
            f'}}\n'
        )

    return HclDocument(text="\n".join(blocks), output_keys=tuple(output_keys))


# ═══════════════════════════════════════════════════════════════════
#  TERRAFORM HANDLER
# ═══════════════════════════════════════════════════════════════════

class TerraformHandler(Handler):
    """
    Provisions Axon manifests through a local `terraform` binary.

    Parameters
    ----------
    workdir : str | Path | None
        Directory where generated HCL and state files live.  If None,
        a per-instance `tempfile.mkdtemp()` is used; the directory is
        retained so the operator can inspect the state after a run.
    terraform_bin : str
        Path or name of the terraform executable.  Defaults to whatever
        `terraform` resolves to in $PATH.
    dry_plan : bool
        If True, the handler stops after `terraform plan` and records the
        plan output instead of calling `apply`.  This enables CI validation
        without real provisioning.
    """

    name: str = "terraform"

    def __init__(
        self,
        *,
        workdir: str | Path | None = None,
        terraform_bin: str = DEFAULT_TERRAFORM_BIN,
        dry_plan: bool = False,
    ) -> None:
        resolved = shutil.which(terraform_bin)
        if resolved is None:
            raise HandlerUnavailableError(
                f"terraform binary '{terraform_bin}' not found on PATH. "
                f"Install from https://developer.hashicorp.com/terraform/install "
                f"or pass terraform_bin=... to the handler."
            )
        self.terraform_bin = resolved
        self._own_workdir = workdir is None
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="axon-tf-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.dry_plan = dry_plan
        self._initialized_dirs: set[Path] = set()

    # ── Handler protocol ──────────────────────────────────────────

    def supports(self, node: IRNode) -> bool:
        return isinstance(node, (IRManifest, IRObserve))

    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        manifest_dir = self._manifest_dir(manifest.name)
        hcl = generate_hcl(manifest, resources, fabrics)
        (manifest_dir / "main.tf").write_text(hcl.text, encoding="utf-8")

        self._run(["init", "-input=false", "-no-color"], manifest_dir)
        if self.dry_plan:
            plan = self._run(["plan", "-input=false", "-no-color"], manifest_dir)
            outcome = HandlerOutcome(
                operation="provision",
                target=manifest.name,
                status="partial",
                envelope=make_envelope(c=0.95, rho=self.name, delta="inferred"),
                data={
                    "workdir": str(manifest_dir),
                    "plan_output": plan,
                    "output_keys": list(hcl.output_keys),
                },
                handler=self.name,
            )
            return continuation(outcome)

        self._run(["apply", "-auto-approve", "-input=false", "-no-color"], manifest_dir)
        state = self._show(manifest_dir)

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=0.97, rho=self.name, delta="observed"),
            data={
                "workdir": str(manifest_dir),
                "state": state,
                "output_keys": list(hcl.output_keys),
            },
            handler=self.name,
        )
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        manifest_dir = self._manifest_dir(manifest.name)
        if not (manifest_dir / "terraform.tfstate").exists():
            # Nothing to observe — manifest was never provisioned through
            # this workspace.  This is a caller-side problem (CT-2).
            raise CallerBlameError(
                f"observe '{obs.name}' has no terraform state for manifest "
                f"'{manifest.name}' at {manifest_dir}"
            )
        state = self._show(manifest_dir)
        resources_summary = [
            {
                "address": r.get("address", ""),
                "type":    r.get("type", ""),
                "mode":    r.get("mode", ""),
            }
            for r in state.get("values", {}).get("root_module", {}).get("resources", [])
        ]
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "workdir": str(manifest_dir),
                "sources": list(obs.sources),
                "resources": resources_summary,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        # We deliberately do NOT delete the workdir on close because the
        # tfstate is a long-lived artifact the operator needs to preserve.
        # The operator owns the lifecycle.
        self._initialized_dirs.clear()

    # ── Internals ─────────────────────────────────────────────────

    def _manifest_dir(self, manifest_name: str) -> Path:
        path = self.workdir / _ident(manifest_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _run(self, args: list[str], cwd: Path) -> str:
        cmd = [self.terraform_bin, *args]
        env = os.environ.copy()
        env["TF_IN_AUTOMATION"] = "1"
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise HandlerUnavailableError(
                f"terraform binary disappeared: {exc}"
            ) from exc
        except OSError as exc:
            raise InfrastructureBlameError(
                f"OS error running terraform {args}: {exc}"
            ) from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            # Heuristic: network-like failures get promoted to CT-3 partitions
            # so the caller can distinguish reachability from other failures.
            lowered = stderr.lower()
            if any(
                marker in lowered
                for marker in (
                    "dial tcp", "no route to host", "network is unreachable",
                    "timeout", "connection refused",
                )
            ):
                raise NetworkPartitionError(
                    f"terraform {args} failed with network-class error: {stderr}"
                )
            # Credential / quota problems are still CT-3 (infrastructure) but
            # not partitions — they are structural inability to proceed.
            if any(
                marker in lowered
                for marker in (
                    "no valid credential", "access denied",
                    "unauthorized", "forbidden", "quota",
                )
            ):
                raise InfrastructureBlameError(
                    f"terraform {args} failed with credentials/quota error: {stderr}"
                )
            # Otherwise blame the handler — our HCL generator likely produced
            # something terraform rejected.  That is CT-1, not the user's fault.
            raise CalleeBlameError(
                f"terraform {args} failed: {stderr or '(no stderr)'}"
            )
        return result.stdout

    def _show(self, cwd: Path) -> dict[str, Any]:
        raw = self._run(["show", "-json", "-no-color"], cwd)
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise CalleeBlameError(
                f"terraform show emitted non-JSON output: {exc}"
            ) from exc


__all__ = [
    "DEFAULT_TERRAFORM_BIN",
    "HclDocument",
    "TerraformHandler",
    "generate_hcl",
]
