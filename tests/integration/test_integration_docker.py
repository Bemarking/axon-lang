"""
Docker integration: opt-in via AXON_IT_DOCKER=1.

Requires:
    • `docker` Python SDK: pip install axon-lang[docker]
    • A running Docker daemon reachable by the default socket
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRFabric, IRManifest, IRResource
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser

from .conftest import skip_unless_docker


_PROGRAM = """
resource PrimaryCache {
  kind: redis
  capacity: 1
  lifetime: affine
}
fabric LocalLab {
  provider: bare_metal
  region: "localhost"
  zones: 1
  ephemeral: true
}
manifest LocalCluster {
  resources: [PrimaryCache]
  fabric: LocalLab
}
observe LocalHealth from LocalCluster {
  sources: [healthcheck]
  quorum: 1
  timeout: 5s
  on_partition: fail
}
"""


@skip_unless_docker
class TestDockerIntegration:

    def test_provision_runs_real_container(self):
        from axon.runtime.handlers.docker import DockerHandler

        tree = Parser(Lexer(_PROGRAM).tokenize()).parse()
        ir = IRGenerator().generate(tree)
        handler = DockerHandler()
        try:
            outcomes = handler.interpret_program(ir)
        finally:
            handler.close()
        assert any(o.operation == "provision" for o in outcomes)
        # At least one container was created in the provision step.
        prov = next(o for o in outcomes if o.operation == "provision")
        assert prov.data["containers"]
