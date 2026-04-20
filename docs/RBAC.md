# RBAC (Role-Based Access Control)

## Overview

Role-Based Access Control in Axon Enterprise enables fine-grained permissions management.

## Built-in Roles

- **Admin**: Full system access
- **Developer**: Can deploy and execute flows, read metrics
- **Viewer**: Read-only access to flows and logs

## Concepts

### Role
A collection of permissions granted to users. Example: "developer"

### Permission
A specific action on a resource. Format: `resource:action`

Examples:
- `flow:deploy` — Deploy a flow
- `flow:execute` — Execute a flow
- `metrics:read` — View metrics
- `audit:view` — View audit logs
- `config:change` — Modify configuration

### Role Hierarchy
Roles can inherit permissions from parent roles.

```
admin
  └── developer
      └── viewer
```

## Usage

```python
from axon_enterprise.rbac import RBACService, Role, Permission

rbac = RBACService()

# Create a role
developer = rbac.get_role_by_name("developer")

# Create a permission
perm = rbac.create_permission("flow", "deploy", "Permission to deploy flows")

# Grant permission
rbac.grant_permission(developer.id, perm.id)

# Check permission
has_perm = rbac.check_permission(developer.id, perm.id)
```

## Integration with Server

In HTTP handlers, check permissions:

```python
@app.post("/flows/deploy")
async def deploy_flow(request):
    user_id = request.user.id
    role = rbac.get_role(user_id)
    
    if not rbac.check_permission(role.id, permission_flow_deploy_id):
        raise PermissionDenied()
    
    # Deploy flow...
```

## Best Practices

- Use hierarchical roles to minimize duplication
- Create fine-grained permissions for audit visibility
- Review permissions quarterly
- Audit role changes in all environments
