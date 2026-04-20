"""
AXON Runtime — AwsHandler
===========================
Interprets the Intention Tree directly against the AWS SDK (boto3).

The handler is the native-SDK sibling of `TerraformHandler`.  Both consume
the same `IRIntentionTree` and produce the same `HandlerOutcome` shape —
the point of having two is that the Fase 2 acceptance criterion requires
the **same Axon program** to be provisionable through either path without
source-level change.

Resource mapping:
    IRResource.kind   →   AWS service
    ─────────────────────────────────
    postgres          →   RDS instance
    redis             →   ElastiCache cluster
    s3                →   S3 bucket
    vpc               →   VPC
    compute           →   EC2 instance
    custom            →   tag-only placeholder recorded in the outcome

Design anchors:
  • D1 — handler is the `h : F_Σ(X) → X` for the AWS algebra.
  • D4 — boto3 connection/timeout errors are classified as CT-3
         (`NetworkPartitionError`); credential/quota failures become
         `InfrastructureBlameError`; `ParamValidationError` is CT-2.
"""

from __future__ import annotations

from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
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


def _sanitize_name(name: str) -> str:
    """Produce an AWS-safe identifier (alphanumerics + dashes, lowercase)."""
    safe = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in name).strip("-").lower()
    return safe or "axon"


class AwsHandler(Handler):
    """
    Native AWS provisioner using boto3.

    The handler lazily imports boto3 so that users not installing the `aws`
    extra can still load the rest of the Axon runtime.

    Parameters
    ----------
    region : str
        AWS region for all operations.  Falls back to the manifest's
        `region` or the fabric's `region` if None.
    profile : str | None
        Optional boto3 profile name.
    """

    name: str = "aws"

    def __init__(self, *, region: str | None = None, profile: str | None = None) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
            import botocore  # type: ignore[import-not-found]
            from botocore import exceptions as botocore_exc  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "boto3 not installed. "
                "Install with `pip install boto3 botocore`."
            ) from exc
        self._boto3 = boto3
        self._botocore_exceptions = botocore_exc
        self._botocore = botocore
        self._default_region = region
        self._profile = profile
        self._session_cache: Any = None

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
        region = self._resolve_region(manifest, fabrics)
        created: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            resource = resources.get(res_name)
            if resource is None:
                continue
            record = self._provision_one(resource, region)
            created.append(record)

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
            data={
                "region": region,
                "manifest": manifest.name,
                "resources": created,
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
        region = self._resolve_region(manifest, None)
        snapshots: list[dict[str, Any]] = []
        healthy = 0
        for res_name in manifest.resources:
            snap = self._observe_one(res_name, region)
            snapshots.append(snap)
            if snap.get("status") == "available":
                healthy += 1

        total = len(snapshots) or 1
        certainty = min(1.0, healthy / total + 0.1)
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=certainty, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "region": region,
                "sources": list(obs.sources),
                "resources": snapshots,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        self._session_cache = None

    # ── Internals ─────────────────────────────────────────────────

    def _session(self) -> Any:
        if self._session_cache is None:
            kwargs: dict[str, Any] = {}
            if self._profile:
                kwargs["profile_name"] = self._profile
            self._session_cache = self._boto3.Session(**kwargs)
        return self._session_cache

    def _client(self, service: str, region: str) -> Any:
        return self._session().client(service, region_name=region)

    def _resolve_region(
        self, manifest: IRManifest, fabrics: dict[str, IRFabric] | None
    ) -> str:
        if self._default_region:
            return self._default_region
        if manifest.region:
            return manifest.region
        if fabrics and manifest.fabric_ref in fabrics:
            fab = fabrics[manifest.fabric_ref]
            if fab.region:
                return fab.region
        # Defer to boto3 default.  If that fails the SDK raises a clear error.
        return "us-east-1"

    def _provision_one(self, resource: IRResource, region: str) -> dict[str, Any]:
        kind = resource.kind
        safe = _sanitize_name(resource.name)
        tags = [
            {"Key": "ManagedBy", "Value": "axon"},
            {"Key": "Name",      "Value": resource.name},
            {"Key": "Lifetime",  "Value": resource.lifetime},
        ]
        try:
            if kind == "s3":
                return self._create_s3_bucket(safe, region, tags)
            if kind == "vpc":
                return self._create_vpc(safe, region, tags)
            if kind == "postgres":
                return self._create_rds_postgres(safe, region, tags)
            if kind == "redis":
                return self._create_elasticache_redis(safe, region)
            if kind == "compute":
                return self._create_ec2(safe, region, tags)
            # Unknown kind → record but do not call AWS.  Still a valid outcome.
            return {"name": resource.name, "kind": kind, "status": "unsupported_kind"}
        except self._botocore_exceptions.EndpointConnectionError as exc:
            raise NetworkPartitionError(
                f"AWS endpoint unreachable for {kind} '{resource.name}': {exc}"
            ) from exc
        except self._botocore_exceptions.ConnectionError as exc:
            raise NetworkPartitionError(
                f"AWS connection error for {kind} '{resource.name}': {exc}"
            ) from exc
        except self._botocore_exceptions.NoCredentialsError as exc:
            raise InfrastructureBlameError(
                f"no AWS credentials for {kind} '{resource.name}': {exc}"
            ) from exc
        except self._botocore_exceptions.ParamValidationError as exc:
            raise CallerBlameError(
                f"invalid parameters for {kind} '{resource.name}': {exc}"
            ) from exc
        except self._botocore_exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            message = exc.response.get("Error", {}).get("Message", str(exc))
            if code in ("UnauthorizedOperation", "AccessDenied", "AuthFailure"):
                raise InfrastructureBlameError(
                    f"AWS auth failure for {kind} '{resource.name}': {message}"
                ) from exc
            if code in ("LimitExceeded", "InstanceLimitExceeded", "DBInstanceQuotaExceeded"):
                raise InfrastructureBlameError(
                    f"AWS quota exceeded for {kind} '{resource.name}': {message}"
                ) from exc
            raise InfrastructureBlameError(
                f"AWS client error for {kind} '{resource.name}' ({code}): {message}"
            ) from exc

    def _observe_one(self, res_name: str, region: str) -> dict[str, Any]:
        safe = _sanitize_name(res_name)
        # We do not know the kind at observe time (the manifest only stores
        # names) so we probe in decreasing order of uniqueness and return
        # the first successful read.  Unknown resources return "unknown".
        for probe in (self._probe_s3, self._probe_rds, self._probe_elasticache):
            try:
                snap = probe(safe, region)
                if snap is not None:
                    return {"name": res_name, **snap}
            except self._botocore_exceptions.EndpointConnectionError as exc:
                raise NetworkPartitionError(
                    f"AWS endpoint unreachable observing '{res_name}': {exc}"
                ) from exc
            except self._botocore_exceptions.ClientError:
                # continue probing other services
                continue
        return {"name": res_name, "status": "unknown"}

    # ── Concrete provisioners ─────────────────────────────────────

    def _create_s3_bucket(
        self, name: str, region: str, tags: list[dict[str, str]]
    ) -> dict[str, Any]:
        client = self._client("s3", region)
        bucket_name = f"axon-{name}"[:63]
        kwargs: dict[str, Any] = {"Bucket": bucket_name}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        client.create_bucket(**kwargs)
        client.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": tags})
        return {"name": name, "kind": "s3", "bucket": bucket_name, "region": region, "status": "created"}

    def _create_vpc(
        self, name: str, region: str, tags: list[dict[str, str]]
    ) -> dict[str, Any]:
        client = self._client("ec2", region)
        result = client.create_vpc(
            CidrBlock="10.0.0.0/16",
            TagSpecifications=[{"ResourceType": "vpc", "Tags": tags}],
        )
        vpc_id = result["Vpc"]["VpcId"]
        return {"name": name, "kind": "vpc", "vpc_id": vpc_id, "region": region, "status": "created"}

    def _create_rds_postgres(
        self, name: str, region: str, tags: list[dict[str, str]]
    ) -> dict[str, Any]:
        client = self._client("rds", region)
        instance_id = name[:63]
        client.create_db_instance(
            DBInstanceIdentifier=instance_id,
            Engine="postgres",
            DBInstanceClass="db.t3.micro",
            AllocatedStorage=20,
            MasterUsername="axon_admin",
            MasterUserPassword="CHANGE_ME_BEFORE_USE",
            Tags=tags,
            PubliclyAccessible=False,
        )
        return {
            "name": name, "kind": "postgres", "db_instance_identifier": instance_id,
            "region": region, "status": "creating",
        }

    def _create_elasticache_redis(self, name: str, region: str) -> dict[str, Any]:
        client = self._client("elasticache", region)
        cluster_id = name[:40]
        client.create_cache_cluster(
            CacheClusterId=cluster_id,
            Engine="redis",
            CacheNodeType="cache.t3.micro",
            NumCacheNodes=1,
            Tags=[{"Key": "ManagedBy", "Value": "axon"}],
        )
        return {
            "name": name, "kind": "redis", "cache_cluster_id": cluster_id,
            "region": region, "status": "creating",
        }

    def _create_ec2(
        self, name: str, region: str, tags: list[dict[str, str]]
    ) -> dict[str, Any]:
        client = self._client("ec2", region)
        result = client.run_instances(
            ImageId="ami-0c02fb55956c7d316",  # Amazon Linux 2 (region-dependent)
            InstanceType="t3.micro",
            MinCount=1,
            MaxCount=1,
            TagSpecifications=[{"ResourceType": "instance", "Tags": tags}],
        )
        instance_ids = [i["InstanceId"] for i in result.get("Instances", [])]
        return {
            "name": name, "kind": "compute", "instance_ids": instance_ids,
            "region": region, "status": "creating",
        }

    # ── Concrete observers ────────────────────────────────────────

    def _probe_s3(self, name: str, region: str) -> dict[str, Any] | None:
        client = self._client("s3", region)
        bucket_name = f"axon-{name}"[:63]
        try:
            client.head_bucket(Bucket=bucket_name)
        except self._botocore_exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                return None
            raise
        return {"kind": "s3", "bucket": bucket_name, "status": "available"}

    def _probe_rds(self, name: str, region: str) -> dict[str, Any] | None:
        client = self._client("rds", region)
        instance_id = name[:63]
        try:
            response = client.describe_db_instances(DBInstanceIdentifier=instance_id)
        except self._botocore_exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("DBInstanceNotFound", "DBInstanceNotFoundFault"):
                return None
            raise
        instances = response.get("DBInstances", [])
        if not instances:
            return None
        inst = instances[0]
        return {
            "kind": "postgres",
            "db_instance_identifier": inst["DBInstanceIdentifier"],
            "status": inst.get("DBInstanceStatus", "unknown"),
        }

    def _probe_elasticache(self, name: str, region: str) -> dict[str, Any] | None:
        client = self._client("elasticache", region)
        cluster_id = name[:40]
        try:
            response = client.describe_cache_clusters(CacheClusterId=cluster_id)
        except self._botocore_exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("CacheClusterNotFound", "CacheClusterNotFoundFault"):
                return None
            raise
        clusters = response.get("CacheClusters", [])
        if not clusters:
            return None
        cluster = clusters[0]
        return {
            "kind": "redis",
            "cache_cluster_id": cluster["CacheClusterId"],
            "status": cluster.get("CacheClusterStatus", "unknown"),
        }


__all__ = ["AwsHandler"]
