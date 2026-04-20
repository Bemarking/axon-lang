"""
AXON — Phase 7.x Extensions tests
===================================
Covers the four "asterisk" extensions that closed the gap between
I/O Cognitivo (Fases 1-6) and full production I/O:

  Asterisk 3.b — in-toto Statement emission (SLSA Provenance v1)
  Asterisk 3.a — SecretProvider (Vault / AWS KMS / Azure Key Vault)
  Asterisk 4.a — MessageQueueHandler (Kafka / RabbitMQ)
  Asterisk 4.b — GrpcHandler (AxonProvisioner remote service)
  Asterisk 4.c — FileHandle + FileResourceKernel + FileHandler

All external SDKs are mocked via `sys.modules` injection so these tests
run in CI without real brokers, vaults, or gRPC servers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRFabric, IRManifest, IRResource, IRObserve
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.esk import (
    InTotoStatement,
    Secret,
    generate_in_toto_statement,
    secret_from_provider,
)
from axon.runtime.file_resource import (
    FileHandle,
    FileHandler,
    FileResourceKernel,
)
from axon.runtime.handlers.base import (
    CallerBlameError,
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
    identity_continuation,
)


# ═══════════════════════════════════════════════════════════════════
#  Asterisk 3.b — in-toto Statement
# ═══════════════════════════════════════════════════════════════════


_SBOM_PROGRAM = """
resource Db { kind: postgres lifetime: linear }
fabric Vpc { provider: aws region: "us-east-1" zones: 2 }
manifest M { resources: [Db] fabric: Vpc }
"""


class TestInTotoStatement:

    def _ir(self):
        return IRGenerator().generate(Parser(Lexer(_SBOM_PROGRAM).tokenize()).parse())

    def test_emits_valid_statement_schema(self):
        stmt = generate_in_toto_statement(self._ir())
        d = stmt.to_dict()
        assert d["_type"] == "https://in-toto.io/Statement/v1"
        assert d["predicateType"] == "https://slsa.dev/provenance/v1"
        assert len(d["subject"]) == 1
        assert "sha256" in d["subject"][0]["digest"]
        assert len(d["subject"][0]["digest"]["sha256"]) == 64

    def test_statement_is_deterministic(self):
        a = generate_in_toto_statement(self._ir()).to_dict()
        b = generate_in_toto_statement(self._ir()).to_dict()
        assert a == b
        # Byte-identical JSON when canonical-encoded.
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_program_change_changes_digest(self):
        a = generate_in_toto_statement(self._ir())
        ir_b = IRGenerator().generate(
            Parser(Lexer(_SBOM_PROGRAM + "\ntype Extra { x: String }").tokenize()).parse()
        )
        b = generate_in_toto_statement(ir_b)
        assert a.subject_digest_sha256 != b.subject_digest_sha256

    def test_predicate_has_slsa_provenance_structure(self):
        pred = generate_in_toto_statement(self._ir()).predicate
        assert "buildDefinition" in pred
        assert "runDetails" in pred
        assert pred["buildDefinition"]["buildType"].startswith("https://axon-lang.io/")
        assert pred["runDetails"]["builder"]["id"].startswith("https://axon-lang.io/")


# ═══════════════════════════════════════════════════════════════════
#  Asterisk 3.a — Secret Providers
# ═══════════════════════════════════════════════════════════════════


class TestVaultProviderLazyImport:

    def test_missing_hvac_raises_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "hvac", None)
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        with pytest.raises(HandlerUnavailableError, match="hvac"):
            mod.VaultProvider(url="http://vault", token="tok")
        monkeypatch.delitem(sys.modules, "hvac", raising=False)
        importlib.reload(mod)


def _install_fake_hvac(monkeypatch, fetch_return=None, fetch_exc=None):
    fake = MagicMock()

    class _Client:
        def __init__(self, **kw):
            self.kw = kw
            self.secrets = MagicMock()
            kv_v2 = MagicMock()
            if fetch_exc:
                kv_v2.read_secret_version.side_effect = fetch_exc
            else:
                kv_v2.read_secret_version.return_value = fetch_return or {
                    "data": {"data": {"key": "secret_value_abc"}}
                }
            self.secrets.kv.v2 = kv_v2

    fake.Client = _Client
    monkeypatch.setitem(sys.modules, "hvac", fake)
    return fake


class TestVaultProvider:

    def test_fetch_returns_secret_data(self, monkeypatch):
        _install_fake_hvac(monkeypatch)
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        provider = mod.VaultProvider(url="http://vault:8200", token="root")
        data = provider.fetch("secret/path")
        assert data == {"key": "secret_value_abc"}

    def test_secret_from_provider_wraps_payload(self, monkeypatch):
        _install_fake_hvac(monkeypatch)
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        provider = mod.VaultProvider(url="http://vault:8200", token="root")
        s = mod.secret_from_provider(provider, "secret/app")
        assert isinstance(s, Secret)
        assert "secret_value_abc" not in repr(s)
        # The label reflects provenance.
        assert s.label == "vault:secret/app"
        # reveal inside audit
        payload = s.reveal(accessor="test", purpose="verify_fetch")
        assert payload == {"key": "secret_value_abc"}

    def test_network_error_reclassified_as_ct3(self, monkeypatch):
        _install_fake_hvac(monkeypatch, fetch_exc=ConnectionRefusedError("timeout to vault"))
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        provider = mod.VaultProvider(url="http://vault", token="tok")
        with pytest.raises(NetworkPartitionError):
            provider.fetch("any")


def _install_fake_boto(monkeypatch, response=None, client_error=None):
    boto3 = MagicMock()
    botocore = MagicMock()

    class _EndpointConnectionError(Exception):
        pass

    class _NoCredentialsError(Exception):
        pass

    class _ClientError(Exception):
        def __init__(self, response=None):
            super().__init__(response)
            self.response = response or {"Error": {"Code": "X", "Message": "x"}}

    exc_module = MagicMock()
    exc_module.EndpointConnectionError = _EndpointConnectionError
    exc_module.NoCredentialsError = _NoCredentialsError
    exc_module.ClientError = _ClientError
    botocore.exceptions = exc_module

    session = MagicMock()
    client = MagicMock()
    if client_error:
        client.get_secret_value.side_effect = client_error
    else:
        client.get_secret_value.return_value = response or {"SecretString": "aws_secret_value"}
    session.client = MagicMock(return_value=client)
    boto3.Session = MagicMock(return_value=session)

    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exc_module)
    return exc_module


class TestAwsKmsProvider:

    def test_fetch_secret_string(self, monkeypatch):
        _install_fake_boto(monkeypatch)
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        provider = mod.AwsKmsProvider(region="us-east-1")
        assert provider.fetch("arn:aws:secretsmanager:...:secret:foo") == "aws_secret_value"

    def test_endpoint_connection_error_is_ct3(self, monkeypatch):
        # Install fake boto FIRST, then instantiate the provider so it
        # captures the same exception classes we'll raise.
        excs = _install_fake_boto(monkeypatch)
        import importlib
        import axon.runtime.esk.providers as mod
        importlib.reload(mod)
        provider = mod.AwsKmsProvider()
        # Now inject the error on the mocked client using the same
        # exception class the provider captured.
        provider._client.get_secret_value.side_effect = excs.EndpointConnectionError("down")
        with pytest.raises(NetworkPartitionError):
            provider.fetch("secret-id")


# ═══════════════════════════════════════════════════════════════════
#  Asterisk 4.a — MessageQueueHandler
# ═══════════════════════════════════════════════════════════════════


class TestMessageQueueHandler:

    def _manifest(self, resource_kind: str):
        r = IRResource(name="OrderEvents", kind=resource_kind, lifetime="affine", capacity=5)
        m = IRManifest(name="MQ", resources=("OrderEvents",))
        return r, m

    def test_unknown_kind_reported_as_skipped(self):
        from axon.runtime.handlers.mq import MessageQueueHandler

        h = MessageQueueHandler(kafka_bootstrap="kafka:9092")
        r, m = self._manifest("unknown_queue_type")
        outcome = h.provision(m, {"OrderEvents": r}, {}, identity_continuation)
        assert outcome.status == "ok"
        assert outcome.data["resources"][0]["status"] == "skipped"

    def test_kafka_without_bootstrap_raises_ct3(self):
        from axon.runtime.handlers.mq import MessageQueueHandler

        h = MessageQueueHandler()  # no bootstrap supplied
        r, m = self._manifest("kafka_topic")
        with pytest.raises(InfrastructureBlameError, match="kafka_bootstrap"):
            h.provision(m, {"OrderEvents": r}, {}, identity_continuation)

    def test_missing_aiokafka_raises_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aiokafka", None)
        import importlib
        import axon.runtime.handlers.mq as mod
        importlib.reload(mod)
        h = mod.MessageQueueHandler(kafka_bootstrap="kafka:9092")
        r, m = self._manifest("kafka_topic")
        with pytest.raises(HandlerUnavailableError, match="aiokafka"):
            h.provision(m, {"OrderEvents": r}, {}, identity_continuation)

    def test_observe_produces_outcome(self):
        from axon.runtime.handlers.mq import MessageQueueHandler

        h = MessageQueueHandler(kafka_bootstrap="kafka:9092")
        r, m = self._manifest("kafka_topic")
        obs = IRObserve(name="Tail", target="MQ", sources=("broker",))
        outcome = h.observe(obs, m, identity_continuation)
        assert outcome.operation == "observe"
        assert outcome.target == "Tail"
        assert outcome.status == "ok"


# ═══════════════════════════════════════════════════════════════════
#  Asterisk 4.b — GrpcHandler
# ═══════════════════════════════════════════════════════════════════


def _install_fake_grpc(monkeypatch, response_payload: bytes | None = None,
                       raise_rpc_error: bool = False,
                       code_name: str = "UNAVAILABLE"):
    fake = MagicMock()

    class _RpcError(Exception):
        def __init__(self, code_name):
            self._code_name = code_name
        def code(self):
            class _C:
                name = self._code_name
            return _C()

    class _StatusCode:
        UNAVAILABLE = "UNAVAILABLE"
        DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"

    fake.RpcError = _RpcError
    fake.StatusCode = _StatusCode
    fake.ssl_channel_credentials = MagicMock(return_value=object())

    class _Channel:
        def __init__(self, address):
            self.address = address
        def close(self):
            pass
        def unary_unary(self, method, request_serializer=None, response_deserializer=None):
            def _invoke(request_bytes, timeout=None):
                if raise_rpc_error:
                    # Create an _RpcError with explicit code_name binding
                    err = _RpcError(code_name)
                    raise err
                return response_payload or json.dumps({"status": "ok", "remote": True}).encode()
            return _invoke

    fake.insecure_channel = lambda addr: _Channel(addr)
    fake.secure_channel = lambda addr, creds: _Channel(addr)
    monkeypatch.setitem(sys.modules, "grpc", fake)
    return fake


class TestGrpcHandler:

    def _load(self, monkeypatch, **kwargs):
        _install_fake_grpc(monkeypatch, **kwargs)
        import importlib
        import axon.runtime.handlers.grpc as mod
        importlib.reload(mod)
        return mod

    def test_missing_grpcio_raises_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "grpc", None)
        import importlib
        import axon.runtime.handlers.grpc as mod
        importlib.reload(mod)
        with pytest.raises(HandlerUnavailableError, match="grpcio"):
            mod.GrpcHandler(endpoint=mod.GrpcEndpoint(address="host:50051"))

    def test_provision_roundtrip(self, monkeypatch):
        mod = self._load(monkeypatch)
        endpoint = mod.GrpcEndpoint(address="host:50051")
        h = mod.GrpcHandler(endpoint=endpoint)
        manifest = IRManifest(name="M", resources=("X",))
        outcome = h.provision(manifest, {}, {}, identity_continuation)
        assert outcome.status == "ok"
        assert outcome.data["remote_response"]["remote"] is True

    def test_unavailable_is_ct3(self, monkeypatch):
        mod = self._load(monkeypatch, raise_rpc_error=True, code_name="UNAVAILABLE")
        h = mod.GrpcHandler(endpoint=mod.GrpcEndpoint(address="host:50051"))
        manifest = IRManifest(name="M", resources=("X",))
        with pytest.raises(NetworkPartitionError):
            h.provision(manifest, {}, {}, identity_continuation)

    def test_tls_secure_channel_used_when_requested(self, monkeypatch):
        mod = self._load(monkeypatch)
        endpoint = mod.GrpcEndpoint(
            address="host:443", use_tls=True,
            root_certs=b"root", private_key=b"pk", cert_chain=b"cc",
        )
        h = mod.GrpcHandler(endpoint=endpoint)
        # Construction does not raise; observe roundtrip succeeds.
        m = IRManifest(name="M", resources=())
        obs = IRObserve(name="O", target="M", sources=("x",))
        outcome = h.observe(obs, m, identity_continuation)
        assert outcome.target == "O"


# ═══════════════════════════════════════════════════════════════════
#  Asterisk 4.c — FileHandle + FileResourceKernel + FileHandler
# ═══════════════════════════════════════════════════════════════════


class TestFileResourceKernel:

    def _resource(self, tmp_path: Path, *, name="LogFile", lifetime="linear"):
        return IRResource(
            name=name, kind="file",
            endpoint=str(tmp_path / "app.log"),
            lifetime=lifetime,
        )

    def test_acquire_and_read_write_roundtrip(self, tmp_path):
        kernel = FileResourceKernel()
        r = self._resource(tmp_path)
        # Ensure file exists for 'rb' mode.
        Path(r.endpoint).write_bytes(b"hello axon")
        handle = kernel.acquire(r, mode="rb")
        with handle as stream:
            assert stream.read() == b"hello axon"
        assert handle._released

    def test_linear_handle_rejects_second_open(self, tmp_path):
        kernel = FileResourceKernel()
        r = self._resource(tmp_path, lifetime="linear")
        Path(r.endpoint).write_bytes(b"x")
        handle = kernel.acquire(r, mode="rb")
        handle.open()
        with pytest.raises(CallerBlameError, match="one stream"):
            handle.open()

    def test_use_after_release_raises_anchor_breach(self, tmp_path):
        kernel = FileResourceKernel()
        r = self._resource(tmp_path)
        Path(r.endpoint).write_bytes(b"x")
        handle = kernel.acquire(r)
        handle.release()
        with pytest.raises(CallerBlameError, match="already released"):
            handle.open()

    def test_wrong_kind_rejected(self):
        kernel = FileResourceKernel()
        bad = IRResource(name="Db", kind="postgres", lifetime="linear")
        with pytest.raises(CallerBlameError, match="kind='file'"):
            kernel.acquire(bad)

    def test_envelope_decays_on_release(self, tmp_path):
        kernel = FileResourceKernel()
        r = self._resource(tmp_path)
        Path(r.endpoint).write_bytes(b"x")
        handle = kernel.acquire(r)
        assert handle.envelope().c == 1.0
        handle.release()
        assert handle.envelope().c == 0.0

    def test_kernel_close_all_releases_every_handle(self, tmp_path):
        kernel = FileResourceKernel()
        r1 = self._resource(tmp_path, name="A")
        r2 = self._resource(tmp_path, name="B")
        Path(r1.endpoint).write_bytes(b"x")
        h1 = kernel.acquire(r1)
        h2 = kernel.acquire(r2, mode="wb")
        kernel.close_all()
        assert h1._released and h2._released
        assert kernel.active() == []


class TestFileHandler:

    def test_provision_creates_parent_and_touches(self, tmp_path):
        handler = FileHandler(touch_on_provision=True)
        target = tmp_path / "subdir" / "app.log"
        r = IRResource(name="Log", kind="file", endpoint=str(target), lifetime="affine")
        m = IRManifest(name="M", resources=("Log",))
        outcome = handler.provision(m, {"Log": r}, {}, identity_continuation)
        assert outcome.status == "ok"
        assert target.exists()
        rec = outcome.data["files"][0]
        assert rec["status"] == "ready"
        assert rec["exists"] is True

    def test_non_file_resources_are_ignored(self, tmp_path):
        handler = FileHandler()
        r = IRResource(name="Db", kind="postgres", lifetime="linear")
        m = IRManifest(name="M", resources=("Db",))
        outcome = handler.provision(m, {"Db": r}, {}, identity_continuation)
        assert outcome.data["files"] == []

    def test_observe_lists_scanned_resources(self, tmp_path):
        handler = FileHandler()
        m = IRManifest(name="M", resources=("A", "B"))
        obs = IRObserve(name="O", target="M", sources=("fs",))
        outcome = handler.observe(obs, m, identity_continuation)
        assert len(outcome.data["files"]) == 2
        assert all(f["scanned"] for f in outcome.data["files"])

    def test_handler_close_closes_kernel(self, tmp_path):
        handler = FileHandler()
        r = IRResource(
            name="L", kind="file",
            endpoint=str(tmp_path / "x.log"),
            lifetime="affine",
        )
        Path(r.endpoint).write_bytes(b"x")
        handler.kernel.acquire(r)
        assert len(handler.kernel.active()) == 1
        handler.close()
        assert handler.kernel.active() == []
