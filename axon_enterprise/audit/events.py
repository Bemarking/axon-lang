"""Enumeration of every event type the system can emit.

The enum is the canonical wire format — downstream consumers (SIEM,
compliance dashboards) match on these strings. Adding a new type
requires a migration bump so the catalogue stays in sync with
deployments.

``resource:action`` naming mirrors the RBAC permission catalog
(10.c) where applicable, but audit events are a superset — we emit
``auth:login`` which has no direct permission.
"""

from __future__ import annotations

from enum import StrEnum


class EventCategory(StrEnum):
    """Top-level grouping — useful for retention policies + filters."""

    AUTH = "auth"
    RBAC = "rbac"
    TENANT = "tenant"
    USER = "user"
    SECRET = "secret"
    FLOW = "flow"
    SSO = "sso"
    JWT = "jwt"
    CONFIG = "config"
    COMPLIANCE = "compliance"


class AuditEventType(StrEnum):
    """Every audit event type. Extend via migration, not hot-fix."""

    # ── Authentication ───────────────────────────────────────────────
    AUTH_LOGIN_SUCCESS = "auth:login_success"
    AUTH_LOGIN_FAILED = "auth:login_failed"
    AUTH_LOGIN_LOCKED = "auth:login_locked"
    AUTH_LOGOUT = "auth:logout"
    AUTH_TOTP_ENROLLED = "auth:totp_enrolled"
    AUTH_TOTP_VERIFIED = "auth:totp_verified"
    AUTH_PASSWORD_CHANGED = "auth:password_changed"
    AUTH_SESSION_REVOKED = "auth:session_revoked"
    AUTH_SESSION_ROTATED = "auth:session_rotated"

    # ── SSO ──────────────────────────────────────────────────────────
    SSO_CONFIG_CREATED = "sso:config_created"
    SSO_CONFIG_UPDATED = "sso:config_updated"
    SSO_CONFIG_DELETED = "sso:config_deleted"
    SSO_LOGIN_SUCCESS = "sso:login_success"
    SSO_LOGIN_FAILED = "sso:login_failed"
    SSO_USER_PROVISIONED = "sso:user_provisioned"
    SSO_ASSERTION_REPLAY = "sso:assertion_replay"

    # ── JWT ──────────────────────────────────────────────────────────
    JWT_KEY_REGISTERED = "jwt:key_registered"
    JWT_KEY_ROTATED = "jwt:key_rotated"
    JWT_KEY_RETIRED = "jwt:key_retired"
    JWT_TOKEN_REVOKED = "jwt:token_revoked"

    # ── RBAC ─────────────────────────────────────────────────────────
    RBAC_ROLE_CREATED = "rbac:role_created"
    RBAC_ROLE_UPDATED = "rbac:role_updated"
    RBAC_ROLE_DELETED = "rbac:role_deleted"
    RBAC_PERMISSION_GRANTED = "rbac:permission_granted"
    RBAC_PERMISSION_REVOKED = "rbac:permission_revoked"
    RBAC_ROLE_ASSIGNED = "rbac:role_assigned"
    RBAC_ROLE_UNASSIGNED = "rbac:role_unassigned"
    RBAC_PERMISSION_DENIED = "rbac:permission_denied"

    # ── Tenant lifecycle ─────────────────────────────────────────────
    TENANT_CREATED = "tenant:created"
    TENANT_UPDATED = "tenant:updated"
    TENANT_SUSPENDED = "tenant:suspended"
    TENANT_RESUMED = "tenant:resumed"
    TENANT_DELETE_SCHEDULED = "tenant:delete_scheduled"
    TENANT_PLAN_CHANGED = "tenant:plan_changed"

    # ── User management ──────────────────────────────────────────────
    USER_CREATED = "user:created"
    USER_UPDATED = "user:updated"
    USER_INVITED = "user:invited"
    USER_DEACTIVATED = "user:deactivated"
    USER_IMPERSONATED = "user:impersonated"

    # ── Secrets ──────────────────────────────────────────────────────
    SECRET_CREATED = "secret:created"
    SECRET_UPDATED = "secret:updated"
    SECRET_READ = "secret:read"
    SECRET_ROTATED = "secret:rotated"
    SECRET_DELETE_SCHEDULED = "secret:delete_scheduled"

    # ── Flow lifecycle ───────────────────────────────────────────────
    FLOW_CREATED = "flow:created"
    FLOW_UPDATED = "flow:updated"
    FLOW_DELETED = "flow:deleted"
    FLOW_EXECUTED = "flow:executed"
    FLOW_DEPLOYED = "flow:deployed"

    # ── Config + compliance ──────────────────────────────────────────
    CONFIG_CHANGED = "config:changed"
    COMPLIANCE_EXPORT_REQUESTED = "compliance:export_requested"
    COMPLIANCE_EXPORT_COMPLETED = "compliance:export_completed"
    COMPLIANCE_EXPORT_FAILED = "compliance:export_failed"
    COMPLIANCE_ERASURE_REQUESTED = "compliance:erasure_requested"
    COMPLIANCE_ERASURE_APPROVED = "compliance:erasure_approved"
    COMPLIANCE_ERASURE_COMPLETED = "compliance:erasure_completed"
    COMPLIANCE_ERASURE_FAILED = "compliance:erasure_failed"
    COMPLIANCE_LEGAL_HOLD_APPLIED = "compliance:legal_hold_applied"
    COMPLIANCE_LEGAL_HOLD_RELEASED = "compliance:legal_hold_released"
    COMPLIANCE_EVIDENCE_BUNDLE_GENERATED = "compliance:evidence_bundle_generated"
    COMPLIANCE_RESIDENCY_VIOLATION = "compliance:residency_violation"

    def category(self) -> EventCategory:
        """Return the parent ``EventCategory`` of this event type."""
        prefix = self.value.split(":", 1)[0]
        return EventCategory(prefix)
