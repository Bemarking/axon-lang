# JWT Issuer — Operator Guide

Signs and rotates access tokens that the Rust runtime
(`axon-lang`) verifies against a published JWKS document. Introduced
in Fase 10.e (v1.1.0); closes the gap in `axon-rs/src/tenant.rs`
where JWTs were read without signature verification.

## Architecture

```
Python (axon-enterprise)                Rust (axon-lang)
┌──────────────────────┐                ┌────────────────────┐
│ JwtIssuer.mint()     │                │ tenant_extractor   │
│  ↓ KMS:Sign (private │                │  ↓ fetch JWKS      │
│    key in HSM)       │───────JWT─────▶│  ↓ verify sig      │
│                      │                │  ↓ iss/aud/exp     │
│ JwksDocumentBuilder  │                │  ↓ TenantContext   │
│  ↓ /.well-known/     │                │                    │
│    jwks.json        ◀│────── GET ─────│ JwksClient cache   │
└──────────────────────┘                └────────────────────┘
```

## Token shape

```
Header: {"alg":"RS256","typ":"JWT","kid":"<active-kid>"}
Claims: {
  "iss":       "https://auth.bemarking.com",
  "sub":       "user:<uuid>",
  "aud":       "axon-api",
  "tenant_id": "<tenant-slug>",
  "plan":      "enterprise",
  "roles":     ["admin","developer"],
  "iat":       <unix>,
  "nbf":       <unix>,
  "exp":       <unix>,
  "jti":       "<uuid>"
}
```

Claims serialised with `sort_keys=True` + `separators=(",",":")` so
identical inputs produce identical bytes before signing (useful for
test fixtures).

## Signing backends

| Backend | When | Where private key lives |
|---|---|---|
| `local` | Dev / test / starter self-host | In-process (loaded from `AXON_JWT_LOCAL_PRIVATE_KEY_PEM`). Rejected in `env=production` by settings validator. |
| `kms` | Production | AWS KMS HSM. Only `kms:Sign` + `kms:GetPublicKey` IAM actions are needed — private key material never leaves the HSM. |

Both conform to the `Signer` protocol and emit RS256/RS384/RS512
(configurable). HS256 / `none` are explicitly disallowed by both the
signer interface and the issuer claim checker.

## Key lifecycle

1. **Register** a new key via `KeyManagementService.register_kms_key`
   (or `register_local_key` for dev). Demotes any existing `active`
   row to `grace`.
2. **Rotate** with `rotate()` — new `active`, old → `grace` with
   `grace_until = now + 7 days` (configurable).
3. **Retire** grace keys past their `grace_until` via
   `retire_expired_grace_keys()` (cron).

At any moment: exactly one row in `status='active'`, zero or more
`grace` rows (retained so tokens minted just before rotation keep
working), arbitrary many `retired` rows (audit trail, never emitted
in JWKS).

The partial unique index `uq_jwt_signing_keys_one_active` enforces
the single-active invariant at the database level — bugs in
application code cannot accidentally dual-sign.

## Operator setup (one-time)

```bash
# 1. Provision KMS key (via AWS CLI or Terraform)
aws kms create-key \
  --description "Axon Enterprise JWT signing" \
  --key-usage SIGN_VERIFY \
  --customer-master-key-spec RSA_2048

# Capture the returned ARN, then:
aws kms create-alias \
  --alias-name alias/axon-enterprise-jwt-primary \
  --target-key-id <returned-KeyId>

# 2. Register in the control plane (via Admin CLI from Fase 10.j)
axon-enterprise keys register-kms \
  --kms-arn arn:aws:kms:us-east-1:<acct>:alias/axon-enterprise-jwt-primary

# 3. Export env vars to the auth service container
export AXON_JWT_SIGNER_BACKEND=kms
export AXON_JWT_KMS_REGION=us-east-1
export AXON_JWT_ISSUER=https://auth.bemarking.com
export AXON_JWT_AUDIENCE=axon-api
```

For the Rust runtime (axon-rs):

```
AXON_JWT_JWKS_URL=https://auth.bemarking.com/.well-known/jwks.json
AXON_JWT_ISSUER=https://auth.bemarking.com
AXON_JWT_AUDIENCE=axon-api
AXON_ENFORCE_JWT_VERIFICATION=true
```

## Rotation procedure (every 90 days)

```bash
# 1. Provision a new KMS key
aws kms create-key ...  # returns new ARN

# 2. Rotate via the Admin CLI
axon-enterprise keys rotate --kms-arn <new-arn>
# → previous active → grace (grace_until = now + 7d)
# → new key → active

# 3. (Optional) Update the alias to the new key
aws kms update-alias \
  --alias-name alias/axon-enterprise-jwt-primary \
  --target-key-id <new-KeyId>

# 4. Wait 7 days; grace keys retire automatically via cron.
```

Existing tokens minted with the old key keep verifying during the
grace window; new tokens are signed with the new key. Rust's JWKS
client refreshes its cache on kid miss so the transition is
transparent to callers.

## Revocation

`JtiRevocationService.revoke(jti, expires_at)` writes to:

- **Postgres** (`jwt_revoked_jtis`): always, for durability
- **Redis** (`axon:jwt:revoked:<jti>`): when configured, for fast reads

The verifier side queries Redis first (expected path), falls through
to Postgres on Redis unavailability — **fail-closed**. A revoked
token must never slip through because infra is sick.

Rows are purged via `purge_expired()` once their `expires_at` is in
the past (tokens past their `exp` fail signature-level checks
already, so the blacklist entry is redundant).

## Security notes

- **Algorithm pinning**: The issuer signs only with RS256/384/512.
  The verifier side (Rust) hard-codes the expected `alg` list; an
  attacker cannot substitute `alg=none` or `HS256` because our
  public key would produce nonsense under symmetric HMAC.
- **`kid` is opaque**: SHA-256 of the DER SPKI bytes, truncated to
  16 hex chars. Does not reveal rotation cadence or creation time,
  so observers of the JWKS document cannot infer when the next
  rotation is due.
- **Single signing path**: `JwtIssuer` refuses to sign when
  `status='active'` has no row (`NoActiveSigningKey`). Operators
  must register a key before the service can issue any tokens —
  this is the intended fail-closed default.
- **Header is part of signed input**: `kid` in the header is
  authenticated by the signature (the header bytes are part of the
  signing input). An attacker cannot substitute a different kid
  without the signature becoming invalid.

## What comes next

- Fase 10.g (Audit) emits `jwt.key_registered`, `jwt.key_rotated`,
  `jwt.key_retired`, `jwt.token_revoked` into the hash-chained
  audit log.
- Fase 10.i adds Prometheus counters for sign / rotate / revoke
  throughput and latency.
- Fase 10.j exposes the `axon-enterprise keys` CLI subcommand group.
