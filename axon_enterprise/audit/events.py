"""Audit event types and models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4


class EventType(str, Enum):
    """Types of audit events."""

    # Authentication events
    LOGIN = "auth:login"
    LOGOUT = "auth:logout"
    LOGIN_FAILED = "auth:login_failed"
    SSO_LOGIN = "auth:sso_login"

    # Flow management
    FLOW_CREATE = "flow:create"
    FLOW_UPDATE = "flow:update"
    FLOW_DELETE = "flow:delete"
    FLOW_DEPLOY = "flow:deploy"
    FLOW_EXECUTE = "flow:execute"

    # User and RBAC
    ROLE_CREATE = "rbac:role_create"
    ROLE_UPDATE = "rbac:role_update"
    ROLE_DELETE = "rbac:role_delete"
    PERMISSION_GRANT = "rbac:permission_grant"
    PERMISSION_REVOKE = "rbac:permission_revoke"

    # Configuration changes
    CONFIG_CHANGE = "config:change"
    SECRET_ACCESS = "config:secret_access"

    # Data access
    DATA_EXPORT = "data:export"
    DATA_DELETE = "data:delete"


@dataclass
class AuditEvent:
    """A single audit event."""

    id: UUID = field(default_factory=uuid4)
    event_type: EventType = EventType.LOGIN
    user_id: Optional[UUID] = None
    user_email: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resource_type: str = ""  # e.g., "flow", "user", "config"
    resource_id: Optional[UUID] = None
    action: str = ""  # e.g., "create", "update", "delete"
    status: str = "success"  # "success" or "failure"
    details: dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""

    def to_dict(self) -> dict:
        """Convert event to dictionary."""
        return {
            "id": str(self.id),
            "event_type": self.event_type.value,
            "user_id": str(self.user_id) if self.user_id else None,
            "user_email": self.user_email,
            "timestamp": self.timestamp.isoformat(),
            "resource_type": self.resource_type,
            "resource_id": str(self.resource_id) if self.resource_id else None,
            "action": self.action,
            "status": self.status,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }
