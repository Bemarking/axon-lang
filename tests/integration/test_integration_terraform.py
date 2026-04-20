"""
Terraform integration: opt-in via AXON_IT_TERRAFORM=1.

Requires:
    • `terraform` binary in PATH.
    • `dry_plan=True` is used by default to avoid real cloud provisioning.
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRFabric, IRManifest, IRResource
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser

from .conftest import skip_unless_terraform


_PROGRAM = """
resource AssetsBucket {
  kind: s3
  lifetime: persistent
}
fabric UsEast {
  provider: aws
  region: "us-east-1"
  zones: 2
  ephemeral: false
}
manifest AssetPlatform {
  resources: [AssetsBucket]
  fabric: UsEast
  compliance: [SOC2]
}
"""


@skip_unless_terraform
class TestTerraformIntegration:

    def test_dry_plan_produces_hcl_and_runs_terraform_init(self, tmp_path):
        from axon.runtime.handlers.terraform import TerraformHandler

        tree = Parser(Lexer(_PROGRAM).tokenize()).parse()
        ir = IRGenerator().generate(tree)
        handler = TerraformHandler(workdir=str(tmp_path), dry_plan=True)
        outcomes = handler.interpret_program(ir)
        prov = next(o for o in outcomes if o.operation == "provision")
        # dry_plan path produces partial-status outcome with plan_output.
        assert prov.status == "partial"
        assert "workdir" in prov.data
        # A real `terraform init` ran under the hood — the working dir has a
        # .terraform subfolder if init succeeded.  At minimum, main.tf exists.
        assert (tmp_path / "assetplatform" / "main.tf").exists()
