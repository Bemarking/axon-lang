# Audit Logging & Compliance

## Overview

Audit logging captures all important operations for compliance and forensics.

## Event Types

### Authentication
- `auth:login` — User login
- `auth:logout` — User logout
- `auth:login_failed` — Failed login attempt
- `auth:sso_login` — SSO authentication

### Flow Management
- `flow:create` — Flow created
- `flow:update` — Flow modified
- `flow:delete` — Flow deleted
- `flow:deploy` — Flow deployed to production
- `flow:execute` — Flow executed

### RBAC
- `rbac:role_create` — Role created
- `rbac:role_update` — Role modified
- `rbac:role_delete` — Role deleted
- `rbac:permission_grant` — Permission granted to role
- `rbac:permission_revoke` — Permission revoked from role

### Configuration
- `config:change` — System configuration changed
- `config:secret_access` — Secret accessed

### Data
- `data:export` — Data exported by user
- `data:delete` — Data deleted

## Usage

```python
from axon_enterprise.audit import AuditLogger, EventType

audit = AuditLogger()

# Log an event
audit.log_event(
    event_type=EventType.FLOW_DEPLOY,
    user_id=user.id,
    user_email=user.email,
    resource_type="flow",
    resource_id=flow.id,
    action="deploy",
    status="success",
    ip_address=request.client.host,
    user_agent=request.headers.get("user-agent"),
)

# Query audit logs
events = audit.get_events(user_id=user.id, event_type=EventType.FLOW_DEPLOY)
```

## Compliance

### GDPR
- Audit logs retained for 2 years (configurable)
- User data deletion triggers audit event
- Right to access audit logs involving user

### SOC 2
- All authentication attempts logged
- All permission changes logged
- User activity tracking
- Immutable audit trail

### HIPAA
- Encryption in transit (TLS)
- Encryption at rest
- Access logging
- Configuration logging

## Best Practices

- Log all security-relevant operations
- Store audit logs in separate database
- Implement log retention policies
- Encrypt audit logs at rest
- Monitor for suspicious patterns
- Generate monthly audit reports
