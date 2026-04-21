"""Invitation error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class InvitationError(IdentityError):
    code = "invite.error"


class InvitationNotFound(InvitationError):
    code = "invite.not_found"
    reveal_to_client = True


class InvitationExpired(InvitationError):
    code = "invite.expired"
    reveal_to_client = True


class InvitationAlreadyAccepted(InvitationError):
    code = "invite.already_accepted"
    reveal_to_client = True
