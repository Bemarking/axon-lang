"""Audit logging service."""

from typing import Any, Optional
from uuid import UUID

from axon_enterprise.audit.events import AuditEvent, EventType


class AuditLogger:
    """Service for logging and retrieving audit events."""

    def __init__(self):
        """Initialize audit logger."""
        self.events: list[AuditEvent] = []

    def log_event(
        self,
        event_type: EventType,
        user_id: Optional[UUID] = None,
        user_email: str = "",
        resource_type: str = "",
        resource_id: Optional[UUID] = None,
        action: str = "",
        status: str = "success",
        details: dict[str, Any] = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> AuditEvent:
        """Log an audit event."""
        if details is None:
            details = {}

        event = AuditEvent(
            event_type=event_type,
            user_id=user_id,
            user_email=user_email,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status=status,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # TODO: Persist event to database
        self.events.append(event)
        return event

    def get_events(self, user_id: Optional[UUID] = None, event_type: Optional[EventType] = None, limit: int = 100) -> list[AuditEvent]:
        """Retrieve audit events with optional filtering."""
        result = self.events

        if user_id:
            result = [e for e in result if e.user_id == user_id]

        if event_type:
            result = [e for e in result if e.event_type == event_type]

        return result[-limit:]  # Return last N events

    def get_event(self, event_id: UUID) -> Optional[AuditEvent]:
        """Retrieve a specific audit event."""
        for event in self.events:
            if event.id == event_id:
                return event
        return None
