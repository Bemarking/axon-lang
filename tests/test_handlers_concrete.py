"""
AXON Runtime — Concrete Handler Tests
======================================
Tests for TerraformHandler, DockerHandler, KubernetesHandler, AwsHandler.

Strategy
--------
• **TerraformHandler**: the HCL generator is a pure function — tested
  directly against golden strings.  End-to-end apply tests are gated
  behind the `AXON_TEST_TERRAFORM_BIN` env var (opt-in integration).
• **DockerHandler / KubernetesHandler / AwsHandler**: the handlers lazy-
  import their SDK at `__init__`.  When the SDK is not installed, the
  handler raises `HandlerUnavailableError`.  We verify the lazy-import
  contract and use `unittest.mock` to stub the SDK calls for logic tests.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from axon.compiler.ir_nodes import (
    IRFabric,
    IRManifest,
    IRObserve,
    IRResource,
)
from axon.runtime.handlers.base import (
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
    identity_continuation,
)


# ═══════════════════════════════════════════════════════════════════
#  TerraformHandler — pure HCL generation golden tests
# ═══════════════════════════════════════════════════════════════════


from axon.runtime.handlers.terraform import (
    HclDocument,
    generate_hcl,
)


def _resource(name: str, kind: str, **kw) -> IRResource:
    defaults = {"name": name, "kind": kind, "lifetime": "affine"}
    defaults.update(kw)
    return IRResource(**defaults)


def _fabric(name: str, provider: str = "aws", region: str = "us-east-1", **kw) -> IRFabric:
    defaults = {"name": name, "provider": provider, "region": region}
    defaults.update(kw)
    return IRFabric(**defaults)


def _manifest(name: str, resources: tuple[str, ...], fabric_ref: str = "", **kw) -> IRManifest:
    defaults = {"name": name, "resources": resources, "fabric_ref": fabric_ref}
    defaults.update(kw)
    return IRManifest(**defaults)


class TestTerraformHclGeneration:
    def test_aws_s3_hcl_contains_bucket_resource(self):
        hcl = generate_hcl(
            _manifest("M", ("Bucket",), "Vpc"),
            {"Bucket": _resource("Bucket", "s3")},
            {"Vpc": _fabric("Vpc")},
        )
        assert 'resource "aws_s3_bucket" "bucket"' in hcl.text
        assert "axon-bucket" in hcl.text  # sanitized bucket name
        assert 'provider "aws"' in hcl.text
        assert any("aws_s3_bucket.bucket.id" in key for key in hcl.output_keys)

    def test_aws_postgres_hcl_contains_db_instance(self):
        hcl = generate_hcl(
            _manifest("M", ("Db",), "Vpc"),
            {"Db": _resource("Db", "postgres")},
            {"Vpc": _fabric("Vpc")},
        )
        assert 'resource "aws_db_instance"' in hcl.text
        assert 'engine' in hcl.text
        assert 'postgres' in hcl.text

    def test_k8s_deployment_hcl(self):
        hcl = generate_hcl(
            _manifest("M", ("App",), "Cluster"),
            {"App": _resource("App", "compute", capacity=3)},
            {"Cluster": _fabric("Cluster", provider="kubernetes", region="")},
        )
        assert 'resource "kubernetes_deployment"' in hcl.text
        assert "replicas = 3" in hcl.text

    def test_unknown_kind_falls_back_to_null_resource(self):
        hcl = generate_hcl(
            _manifest("M", ("X",)),
            {"X": _resource("X", "quantum_widget")},
            {},
        )
        assert 'resource "null_resource"' in hcl.text

    def test_deterministic_output(self):
        """HCL generation must be a pure function — same input, same output."""
        inputs = dict(
            manifest=_manifest("M", ("Db", "Cache"), "Vpc"),
            resources={
                "Db":    _resource("Db", "postgres"),
                "Cache": _resource("Cache", "redis"),
            },
            fabrics={"Vpc": _fabric("Vpc")},
        )
        assert generate_hcl(**inputs).text == generate_hcl(**inputs).text

    def test_missing_resource_is_silently_skipped(self):
        """Defense in depth — the type-checker has already rejected this."""
        hcl = generate_hcl(
            _manifest("M", ("Ghost",), ""),
            {},
            {},
        )
        # No resource block emitted for the missing reference.
        assert "Ghost" not in hcl.text


class TestTerraformHandlerConstructor:
    def test_missing_binary_raises_unavailable(self):
        with pytest.raises(HandlerUnavailableError, match="terraform binary"):
            from axon.runtime.handlers.terraform import TerraformHandler
            TerraformHandler(terraform_bin="__absolutely_not_terraform__")


# ═══════════════════════════════════════════════════════════════════
#  DockerHandler — SDK lazy import + mocked control-flow tests
# ═══════════════════════════════════════════════════════════════════


def _install_fake_docker_module(monkeypatch: pytest.MonkeyPatch, client_factory=None):
    """Inject a minimal fake `docker` module into sys.modules."""
    fake = MagicMock()
    fake.errors = MagicMock()
    # Exception types must be real classes so that `except` clauses work.
    fake.errors.DockerException = type("DockerException", (Exception,), {})
    fake.errors.NotFound          = type("NotFound",          (fake.errors.DockerException,), {})
    fake.errors.APIError          = type("APIError",          (fake.errors.DockerException,), {})
    fake.errors.ImageNotFound     = type("ImageNotFound",     (fake.errors.DockerException,), {})

    if client_factory is None:
        client_factory = MagicMock
    client = client_factory()
    fake.DockerClient = MagicMock(return_value=client)
    fake.from_env = MagicMock(return_value=client)

    monkeypatch.setitem(sys.modules, "docker", fake)
    monkeypatch.setitem(sys.modules, "docker.errors", fake.errors)
    # The handler does `from docker import errors as docker_errors` — supported.
    return fake, client


class TestDockerHandler:
    def test_missing_sdk_raises_unavailable(self, monkeypatch):
        # Simulate docker not installed by removing it if present.
        monkeypatch.setitem(sys.modules, "docker", None)
        # Re-importing after the stub ensures ImportError on `import docker`.
        import importlib
        import axon.runtime.handlers.docker as docker_handler_mod
        importlib.reload(docker_handler_mod)
        with pytest.raises(HandlerUnavailableError, match="docker Python SDK"):
            docker_handler_mod.DockerHandler()
        # Restore for downstream tests.
        monkeypatch.delitem(sys.modules, "docker", raising=False)
        importlib.reload(docker_handler_mod)

    def test_unreachable_daemon_raises_ct3(self, monkeypatch):
        fake, client = _install_fake_docker_module(monkeypatch)
        client.ping.side_effect = fake.errors.DockerException("cannot connect")
        import importlib
        import axon.runtime.handlers.docker as docker_handler_mod
        importlib.reload(docker_handler_mod)
        with pytest.raises(NetworkPartitionError, match="Docker daemon"):
            docker_handler_mod.DockerHandler()

    def test_provision_runs_container(self, monkeypatch):
        fake, client = _install_fake_docker_module(monkeypatch)
        client.ping.return_value = True
        # Simulate: image present, no prior container, run succeeds.
        client.images.get.return_value = True
        client.containers.get.side_effect = fake.errors.NotFound("not found")
        run_result = MagicMock()
        run_result.id = "abc123defghi"
        client.containers.run.return_value = run_result

        import importlib
        import axon.runtime.handlers.docker as docker_handler_mod
        importlib.reload(docker_handler_mod)

        handler = docker_handler_mod.DockerHandler()
        manifest = _manifest("M", ("Db",))
        resources = {"Db": _resource("Db", "postgres")}
        outcome = handler.provision(manifest, resources, {}, identity_continuation)

        assert outcome.status == "ok"
        assert outcome.target == "M"
        assert outcome.data["containers"][0]["kind"] == "postgres"
        client.containers.run.assert_called_once()

    def test_observe_reports_missing_container(self, monkeypatch):
        fake, client = _install_fake_docker_module(monkeypatch)
        client.ping.return_value = True
        client.containers.get.side_effect = fake.errors.NotFound("missing")

        import importlib
        import axon.runtime.handlers.docker as docker_handler_mod
        importlib.reload(docker_handler_mod)

        handler = docker_handler_mod.DockerHandler()
        manifest = _manifest("M", ("Db",))
        obs = IRObserve(name="S", target="M", sources=("docker",), on_partition="fail")
        outcome = handler.observe(obs, manifest, identity_continuation)

        assert outcome.status == "ok"
        assert outcome.data["containers"][0]["status"] == "missing"
        # Missing container ⇒ low certainty (0 running / 1 expected)
        assert outcome.envelope.c < 0.2


# ═══════════════════════════════════════════════════════════════════
#  KubernetesHandler — SDK lazy import
# ═══════════════════════════════════════════════════════════════════


def _install_fake_kubernetes_module(monkeypatch: pytest.MonkeyPatch):
    fake = MagicMock()
    fake.client = MagicMock()
    fake.config = MagicMock()
    fake.config.load_kube_config = MagicMock()
    fake.config.load_incluster_config = MagicMock()

    apps_api = MagicMock()
    core_api = MagicMock()
    fake.client.AppsV1Api = MagicMock(return_value=apps_api)
    fake.client.CoreV1Api = MagicMock(return_value=core_api)

    monkeypatch.setitem(sys.modules, "kubernetes", fake)
    monkeypatch.setitem(sys.modules, "kubernetes.client", fake.client)
    monkeypatch.setitem(sys.modules, "kubernetes.config", fake.config)
    return fake, apps_api, core_api


class TestKubernetesHandler:
    def test_missing_client_raises_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "kubernetes", None)
        import importlib
        import axon.runtime.handlers.kubernetes as k8s_mod
        importlib.reload(k8s_mod)
        with pytest.raises(HandlerUnavailableError, match="kubernetes client"):
            k8s_mod.KubernetesHandler()
        monkeypatch.delitem(sys.modules, "kubernetes", raising=False)
        importlib.reload(k8s_mod)

    def test_plan_manifest_emits_deployment_and_service(self):
        from axon.runtime.handlers.kubernetes import plan_manifest
        plan = plan_manifest(
            _manifest("Prod", ("Db",), "Cluster"),
            {"Db": _resource("Db", "postgres", capacity=2)},
            {"Cluster": _fabric("Cluster", provider="kubernetes", region="prod-ns")},
        )
        assert plan.namespace == "prod-ns"
        assert len(plan.deployments) == 1
        assert len(plan.services) == 1
        dep = plan.deployments[0]
        assert dep["metadata"]["name"] == "db"
        assert dep["spec"]["replicas"] == 2
        assert dep["metadata"]["labels"]["axon.io/resource-kind"] == "postgres"
        assert plan.services[0]["spec"]["ports"][0]["port"] == 5432

    def test_plan_manifest_uses_compute_without_service(self):
        from axon.runtime.handlers.kubernetes import plan_manifest
        plan = plan_manifest(
            _manifest("M", ("App",)),
            {"App": _resource("App", "compute")},
            {},
        )
        assert len(plan.deployments) == 1
        assert len(plan.services) == 0


# ═══════════════════════════════════════════════════════════════════
#  AwsHandler — SDK lazy import + dispatch shape
# ═══════════════════════════════════════════════════════════════════


def _install_fake_boto_modules(monkeypatch: pytest.MonkeyPatch):
    boto3 = MagicMock()
    botocore = MagicMock()
    exceptions = MagicMock()
    # Real exception classes so try/except works as in production.
    exceptions.EndpointConnectionError = type("EndpointConnectionError", (Exception,), {})
    exceptions.ConnectionError         = type("ConnectionError",         (Exception,), {})
    exceptions.NoCredentialsError      = type("NoCredentialsError",      (Exception,), {})
    exceptions.ParamValidationError    = type("ParamValidationError",    (Exception,), {})

    class ClientError(Exception):
        def __init__(self, response=None, operation_name=""):
            super().__init__(response)
            self.response = response or {"Error": {"Code": "", "Message": ""}}
    exceptions.ClientError = ClientError
    botocore.exceptions = exceptions

    session = MagicMock()
    boto3.Session = MagicMock(return_value=session)

    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exceptions)
    return boto3, botocore, exceptions, session


class TestAwsHandler:
    def test_missing_sdk_raises_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "boto3", None)
        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)
        with pytest.raises(HandlerUnavailableError, match="boto3"):
            aws_mod.AwsHandler()
        monkeypatch.delitem(sys.modules, "boto3", raising=False)
        importlib.reload(aws_mod)

    def test_provision_dispatches_to_s3_client(self, monkeypatch):
        _boto3, _botocore, _excs, session = _install_fake_boto_modules(monkeypatch)
        s3_client = MagicMock()
        session.client.return_value = s3_client

        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)

        handler = aws_mod.AwsHandler(region="us-east-1")
        manifest = _manifest("M", ("Bucket",), region="us-east-1")
        resources = {"Bucket": _resource("Bucket", "s3")}
        outcome = handler.provision(manifest, resources, {}, identity_continuation)

        assert outcome.status == "ok"
        assert outcome.data["resources"][0]["kind"] == "s3"
        # Verify we actually called S3 create_bucket via the mocked session.
        session.client.assert_any_call("s3", region_name="us-east-1")
        s3_client.create_bucket.assert_called_once()

    def test_endpoint_unreachable_is_ct3(self, monkeypatch):
        _boto3, _botocore, excs, session = _install_fake_boto_modules(monkeypatch)
        s3_client = MagicMock()
        s3_client.create_bucket.side_effect = excs.EndpointConnectionError("partition")
        session.client.return_value = s3_client

        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)

        handler = aws_mod.AwsHandler(region="us-east-1")
        manifest = _manifest("M", ("Bucket",), region="us-east-1")
        resources = {"Bucket": _resource("Bucket", "s3")}
        with pytest.raises(NetworkPartitionError):
            handler.provision(manifest, resources, {}, identity_continuation)

    def test_credential_error_is_infrastructure_blame(self, monkeypatch):
        _boto3, _botocore, excs, session = _install_fake_boto_modules(monkeypatch)
        s3_client = MagicMock()
        s3_client.create_bucket.side_effect = excs.NoCredentialsError("no creds")
        session.client.return_value = s3_client

        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)

        handler = aws_mod.AwsHandler(region="us-east-1")
        manifest = _manifest("M", ("Bucket",), region="us-east-1")
        resources = {"Bucket": _resource("Bucket", "s3")}
        with pytest.raises(InfrastructureBlameError, match="no AWS credentials"):
            handler.provision(manifest, resources, {}, identity_continuation)


# ═══════════════════════════════════════════════════════════════════
#  FASE 2 ACCEPTANCE CRITERION
#
#  "Un programa Axon aprovisiona una VPC real vía Terraform handler sin
#   acoplarse a Terraform (mismo programa corre con handler AWS-SDK)."
#
#  The IRIntentionTree is handler-agnostic by construction.  The test
#  below parses a single .axon program once and interprets it under both
#  the Terraform HCL generator and the mocked AWS SDK — without touching
#  the source.  This satisfies D1 (Free Monads + Handlers): a single
#  `F_Σ(X)` admits multiple natural transformations `h : F_Σ(X) → X`.
# ═══════════════════════════════════════════════════════════════════


class TestFase2AcceptanceCriterion:
    _SOURCE = '''
resource ProductionVpc { kind: vpc lifetime: persistent }
resource AssetsBucket  { kind: s3  lifetime: persistent }
fabric UsEast { provider: aws region: "us-east-1" zones: 2 ephemeral: false }
manifest Platform {
  resources: [ProductionVpc, AssetsBucket]
  fabric: UsEast
  region: "us-east-1"
  compliance: [SOC2]
}
'''

    def _build_ir(self):
        from axon.compiler.ir_generator import IRGenerator
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        return IRGenerator().generate(Parser(Lexer(self._SOURCE).tokenize()).parse())

    def test_same_program_emits_terraform_hcl(self):
        ir = self._build_ir()
        from axon.runtime.handlers.terraform import generate_hcl

        manifest = ir.manifests[0]
        resources = {r.name: r for r in ir.resources}
        fabrics = {f.name: f for f in ir.fabrics}
        hcl = generate_hcl(manifest, resources, fabrics)

        assert 'resource "aws_vpc"' in hcl.text
        assert 'resource "aws_s3_bucket"' in hcl.text
        assert 'provider "aws"' in hcl.text

    def test_same_program_emits_aws_api_calls(self, monkeypatch):
        _boto3, _botocore, _excs, session = _install_fake_boto_modules(monkeypatch)
        client = MagicMock()
        client.create_vpc.return_value = {"Vpc": {"VpcId": "vpc-123"}}
        session.client.return_value = client

        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)

        ir = self._build_ir()
        handler = aws_mod.AwsHandler()
        outcomes = handler.interpret_program(ir)

        assert len(outcomes) == 1  # one provision for the single manifest
        outcome = outcomes[0]
        assert outcome.target == "Platform"
        assert outcome.handler == "aws"
        # Both a VPC and an S3 bucket were provisioned via boto3.
        client.create_vpc.assert_called_once()
        client.create_bucket.assert_called_once()

    def test_source_is_never_recompiled_between_handlers(self, monkeypatch):
        """Parse ONCE; interpret under two handlers with no source change."""
        ir = self._build_ir()

        # Handler 1: Terraform HCL generator (pure — no subprocess needed).
        from axon.runtime.handlers.terraform import generate_hcl
        m = ir.manifests[0]
        hcl_text = generate_hcl(
            m,
            {r.name: r for r in ir.resources},
            {f.name: f for f in ir.fabrics},
        ).text
        assert "aws_vpc" in hcl_text

        # Handler 2: Mocked AWS handler over the SAME ir object.
        _boto3, _botocore, _excs, session = _install_fake_boto_modules(monkeypatch)
        client = MagicMock()
        client.create_vpc.return_value = {"Vpc": {"VpcId": "vpc-xyz"}}
        session.client.return_value = client

        import importlib
        import axon.runtime.handlers.aws as aws_mod
        importlib.reload(aws_mod)

        outcomes = aws_mod.AwsHandler().interpret_program(ir)
        assert outcomes[0].handler == "aws"
        # No recompilation, no source mutation: the IR was consumed twice.
        assert ir.manifests[0].name == "Platform"
