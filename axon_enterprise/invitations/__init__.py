"""Magic-link invitations — Fase 10.k.

Sits on top of ``tenant_memberships`` from 10.b (no new table).
Flow:

    1. Admin POSTs ``/api/v1/tenant/users/invite`` with an email.
    2. ``InvitationService.invite`` upserts a membership row with
       status='invited', a 32-byte random token (SHA-256 hashed +
       stored in ``invitation_token_hash``), and an expiry.
    3. A magic-link URL carrying the raw token is emailed to the
       invitee (mailer is wired in 10.l — here we just return the
       URL to the caller for now).
    4. Invitee opens the URL → frontend POSTs
       ``/api/v1/auth/invite/accept`` with the token + a new
       password (or SSO flow continuation).
    5. ``InvitationService.accept`` verifies + one-time-consumes,
       flips status='active', creates the User row when it's a
       password-based registration, issues a Session.

Hash-and-forget: only the SHA-256 of the token lives in the DB.
Lose the DB, lose nothing. Token replay is blocked by the
``invitation_token_hash`` column being cleared on accept.
"""

from axon_enterprise.invitations.errors import (
    InvitationAlreadyAccepted,
    InvitationError,
    InvitationExpired,
    InvitationNotFound,
)
from axon_enterprise.invitations.service import (
    InvitationIssued,
    InvitationService,
)

__all__ = [
    "InvitationAlreadyAccepted",
    "InvitationError",
    "InvitationExpired",
    "InvitationIssued",
    "InvitationNotFound",
    "InvitationService",
]
