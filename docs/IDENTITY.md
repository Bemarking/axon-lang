# Identity Core — Operator Guide

Authentication primitives that the Admin API (Fase 10.j) and the
Tenant Self-Service Portal (Fase 10.k) call into. This document
covers how the moving parts fit together and what operators must
configure before the first user is registered.

## Schema overview

| Table | Scope | RLS |
|---|---|---|
| `axon_control.users` | Global (one row per natural person) | `admin_bypass` only — reads/writes must go through an admin session after an upstream tenant membership check |
| `axon_control.tenant_memberships` | Tenant-scoped | `tenant_isolation` + `admin_bypass` |
| `axon_control.sessions` | Tenant-scoped | `tenant_isolation` + `admin_bypass` |

The `users` table deliberately spans tenants so one natural person
keeps a single set of credentials even when they work across multiple
tenant workspaces. Access is gated by the service layer: handlers
query `tenant_memberships` under a `tenant_session(ctx)` to establish
"this user is in my tenant", then open an `admin_session()` for the
actual `users` row.

## Password hashing

Argon2id via `argon2-cffi` with OWASP 2024 upper-middle parameters:

- `time_cost = 3`
- `memory_cost = 64 MiB` (override to 128 MiB via `AXON_IDENTITY_ARGON2_MEMORY_COST_KIB` on beefy hardware)
- `parallelism = 4`
- `hash_len = 32`, `salt_len = 16`

`PasswordHasher` exposes `needs_rehash()` so on successful login the
`AuthService` transparently rotates the stored hash when parameters
are bumped in a later deploy. Timing parity between existing vs
non-existing users is maintained by `burn_equivalent_time()` which
runs a full Argon2 verify against a dummy hash whenever the email
does not resolve to a user.

## Password policy

Three validations run on registration, rotation, and password reset:

1. **Length** ≥ 12 chars (`password_min_length`)
2. **zxcvbn score** ≥ 3/4 (`password_zxcvbn_min_score`) with
   `user_inputs=[email, display_name]` so passwords that echo the
   user's identity are penalised
3. **HIBP k-anonymity** — only the SHA-1 prefix (5 hex chars) is sent
   to `api.pwnedpasswords.com`; the full hash never leaves the
   process. Fails **open** on network errors so HIBP outages do not
   block legitimate registrations

## TOTP 2FA

`pyotp` with 160-bit secrets. Each secret is envelope-encrypted
before persistence — the AAD includes the `user_id` and a constant
`purpose="identity.totp"` so ciphertexts cannot be swapped between
users or between TOTP and other field-level secrets.

Envelope backend is configured per-environment:

- **`local`** (dev/test) — Fernet-derived, master key loaded from
  `AXON_ENVELOPE__LOCAL_KEY`. Rejected in production by settings
  validator.
- **`kms`** (production) — `GenerateDataKey` + `Decrypt` with the
  AAD passed as EncryptionContext. Wrapped DEK is embedded in the
  ciphertext; plaintext never reaches the DB.

## Progressive lockout

Default ladder, tuned in `IdentitySettings`:

| Consecutive failures | Action |
|---|---|
| 1–4 | No lock |
| 5 | 15 min soft lock |
| 10 | 1 h hard lock |
| 20 | Permanent lock (`users.status = 'locked'`) — admin must reactivate |

Successful login resets `failed_logins = 0` and clears
`locked_until`. The failure count uses the **new** value
post-increment so the ladder is off-by-one-free.

## Session lifecycle

- Refresh tokens: 64 random bytes, base64url. Only the SHA-256 hash
  is stored; the raw token is returned to the client exactly once
  in the response body.
- TTLs: `inactivity = 24 h`, `absolute = 30 days`. Both are enforced
  in `verify_and_rotate`.
- Rotation: every successful refresh mints a new token and marks the
  predecessor `revoked_at = NOW()`, `revoked_reason = 'rotated'`,
  `rotated_to_session_id = new_id`.
- Replay detection: presenting an already-revoked token revokes
  every live session for the same `(user_id, tenant_id)` pair so
  both the attacker and the legitimate client are forced to
  re-authenticate.

## Service composition

```python
from axon_enterprise.db.session import admin_session
from axon_enterprise.identity import AuthService

auth = AuthService.default()

async with admin_session() as db:
    user = await auth.register(
        db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        display_name="Alice",
    )

    result = await auth.authenticate(
        db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        tenant_id="acme",
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
    )
    # result.session.raw_refresh_token is returned to the client once.
```

## Required environment

```
AXON_IDENTITY_ARGON2_MEMORY_COST_KIB=65536    # 64 MiB; bump for prod
AXON_IDENTITY_PASSWORD_CHECK_HIBP=true
AXON_IDENTITY_TOTP_ISSUER="Acme Enterprise"
AXON_IDENTITY_SESSION_INACTIVITY_TTL_HOURS=24
AXON_IDENTITY_SESSION_ABSOLUTE_TTL_DAYS=30
```

Plus, in production:

```
AXON_ENVELOPE__BACKEND=kms
AXON_ENVELOPE__KMS_KEY_ID=arn:aws:kms:us-east-1:...:key/...
AXON_ENVELOPE__KMS_REGION=us-east-1
```

## Next sub-fase

10.c (RBAC Production-Grade) adds role + permission tables and ties
`tenant_memberships` to roles via `user_roles`. 10.d (SSO) wires an
alternative registration path that bypasses the password field.
10.e (JWT Issuer) replaces the unverified JWT extraction in the
Rust runtime with JWKS-backed verification.
