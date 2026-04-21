# RBAC — Operator Guide

Tenant-scoped, persistent Role-Based Access Control with recursive
role hierarchy enforced in Postgres. Introduced in Fase 10.c
(v1.1.0); replaces the in-memory scaffolding from v1.0.0.

## Data model

```
                        ┌───────────────────────────┐
                        │   axon_control.permissions│
                        │   (global catalog, RLS-off)
                        └─────────────┬─────────────┘
                                      │
                                      │ permission_id
                                      ▼
 ┌──────────────────┐       ┌────────────────────────────┐
 │ axon_control.    │──────▶│ axon_control.              │
 │   roles          │       │   role_permissions         │
 │  (tenant-scoped) │       │ (tenant-scoped, M2M)       │
 │  parent_role_id  │       └────────────────────────────┘
 └───────┬──────────┘
         │ role_id
         ▼
 ┌────────────────────────┐           ┌──────────────────┐
 │ axon_control.          │           │ axon_control.    │
 │   user_roles           │◀──────────│   users          │
 │ (user ↔ role ↔ tenant) │  user_id  │ (global)         │
 └────────────────────────┘           └──────────────────┘
```

All tenant-scoped tables (`roles`, `role_permissions`, `user_roles`)
enforce RLS via the shared `axon.current_tenant` GUC. The
`permissions` catalog is deliberately global: it is a closed set of
`(resource, action)` pairs that every tenant references, and no
tenant should be able to invent permission strings that cannot be
enforced.

## Permission catalog

Thirty-two entries grouped by resource:

| Resource | Actions |
|---|---|
| `tenant` | `read`, `update`, `delete`, `suspend` |
| `user` | `invite`, `read`, `update`, `deactivate`, `impersonate` |
| `role` | `create`, `read`, `update`, `delete`, `assign` |
| `flow` | `create`, `read`, `update`, `delete`, `execute`, `deploy` |
| `secret` | `list`, `read`, `write`, `delete`, `rotate` |
| `audit` | `read`, `export` |
| `metering` | `read`, `export_invoice` |
| `observability` | `read_metrics`, `read_logs`, `read_traces` |

The catalog lives in `axon_enterprise.rbac.permissions.SYSTEM_PERMISSIONS`
and is seeded by migration 003 via `INSERT ... ON CONFLICT DO NOTHING`.

## Built-in roles (per tenant)

Seeded by `RbacService.seed_builtin_roles(tenant_id, owner_user_id?)`
during tenant provisioning (Fase 10.j Admin API). Every tenant
receives these four with deterministic names:

| Role | Permissions |
|---|---|
| `owner` | **all** catalog entries — cannot be stripped from the original owner user |
| `admin` | all except `tenant:delete`, `tenant:suspend`, `user:impersonate` |
| `developer` | `flow:*`, `secret:read`, `secret:list`, `audit:read`, `metering:read`, `observability:*`, `role:read`, `user:read`, `tenant:read` |
| `viewer` | every `*:read*` permission — strictly read-only |

All four are flagged `is_built_in = true`; `RbacService.delete_role`
refuses to remove them. Their permission sets are backfilled when
the catalog grows (idempotent seeder).

## Role hierarchy

Roles can carry a `parent_role_id` pointing to another role in the
same tenant. Effective permissions for a user are computed by
walking the DAG upward and taking the UNION of every reachable
role's direct grants:

```sql
WITH RECURSIVE role_tree AS (
    SELECT r.role_id, r.parent_role_id
    FROM axon_control.roles r
    JOIN axon_control.user_roles ur USING (role_id)
    WHERE ur.user_id = :user_id AND ur.tenant_id = :tenant_id
    UNION
    SELECT r.role_id, r.parent_role_id
    FROM axon_control.roles r
    JOIN role_tree rt ON r.role_id = rt.parent_role_id
)
SELECT DISTINCT p.resource, p.action
FROM role_tree rt
JOIN axon_control.role_permissions rp ON rp.role_id = rt.role_id
JOIN axon_control.permissions p ON p.permission_id = rp.permission_id;
```

`UNION` (not `UNION ALL`) deduplicates, so a smuggled cycle
terminates. Cycle prevention at write time sits in
`RbacService._assert_no_cycle`, invoked by both `create_role` and
`set_parent`.

## Enforcement

Handlers use a decorator that extracts the principal from the
`CURRENT_PRINCIPAL` ContextVar (populated by auth middleware) and
the DB session from the function's first `AsyncSession`-typed
parameter:

```python
from axon_enterprise.rbac import require_permission

@require_permission("secret:write")
async def create_secret(db: AsyncSession, request: Request) -> Response:
    # Reached only if the principal holds secret:write in the active tenant.
    ...
```

The permission string is parsed **at decoration time** so typos fail
at import, not at request time.

Imperative helpers:

```python
from axon_enterprise.rbac import check_permission, require_permission_active

# Boolean — no exception
allowed = await check_permission(db, "flow:deploy")

# Raises PermissionDenied on deny
await require_permission_active(db, "flow:deploy")
```

`PermissionDenied` carries `.permission` so handlers can render
precise 403 responses. The permission identifier is considered safe
to reveal — action names are already implicit in request paths.

## Performance

Permission resolution is a single recursive-CTE query. On a seeded
built-in role tree the plan is bounded by:

- One index lookup per role in the user's direct assignment set (the
  CTE seed)
- O(depth) index lookups walking `parent_role_id`
- One join across `role_permissions` + `permissions`

For a typical tenant (4 built-in roles + a handful of custom ones)
the resolution latency is sub-millisecond. If a request checks the
same user+tenant repeatedly, cache the effective set on the
`PrincipalContext` for the lifetime of the request — or plug a
distributed cache in Fase 10.i when metrics demand it.

## Guard rails

- `RbacService.assign_role` rejects cross-tenant assignments
  (assigning tenant A's role with `tenant_id='B'`) to prevent
  isolation bypass.
- Built-in roles cannot be deleted (`BuiltInRoleProtected`).
- Cycles in the hierarchy raise `RoleCycleError` at write time.
- `InvalidPermissionString` is raised for strings not present in the
  catalog — adding new permissions requires a migration, not code.

## Service API at a glance

```python
rbac = RbacService()

# Catalog (global)
perms = await rbac.list_permissions(db)

# Roles (tenant-scoped)
role = await rbac.create_role(db, tenant_id="acme", name="data-scientist")
await rbac.grant_permission(db, role_id=role.role_id, resource="flow", action="execute")

# Bulk grant (used by the seeder)
await rbac.grant_permissions(
    db, role_id=role.role_id, permission_keys=["flow:read", "flow:execute"]
)

# User ↔ Role
await rbac.assign_role(db, user_id=alice_id, role_id=role.role_id, tenant_id="acme")

# Resolution
effective = await rbac.effective_permissions(db, user_id=alice_id, tenant_id="acme")
ok = await rbac.check(db, user_id=alice_id, tenant_id="acme", permission="flow:execute")
```

## What comes next

- Fase 10.d (SSO) wires identity federation; the JWT carries
  `roles[]` so handlers get a denormalised view without a DB hit
  for every coarse check.
- Fase 10.g (Audit) emits `rbac:role_create`, `rbac:permission_grant`,
  `rbac:permission_revoke`, and `rbac:role_assign` into the
  hash-chained audit log.
- Fase 10.j (Admin API) wires the REST endpoints that call into
  this service — `POST /tenants/{id}/roles`, `PUT /users/{uid}/roles`,
  etc.
