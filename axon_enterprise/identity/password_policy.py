"""Password strength and compromise checks.

Three validations, configurable via ``IdentitySettings``:

1. **Length** — default ≥ 12 chars (OWASP ASVS v4 L3).
2. **zxcvbn score** — default ≥ 3 (out of 0..4). Blocks things like
   ``Summer2024!`` which pass length checks but remain low-entropy.
3. **HIBP k-anonymity lookup** — hashes the password with SHA-1,
   sends the first 5 hex chars to ``api.pwnedpasswords.com``, checks
   whether the remaining 35 chars appear in the response. The full
   password never leaves the process.

The policy is used on:

    - registration
    - password rotation
    - password reset completion

Failures surface as ``PasswordPolicyViolation`` with a list of
specific reasons so UI can render them inline.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx
import zxcvbn  # type: ignore[import-untyped]

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.identity.errors import PasswordPolicyViolation


@dataclass(frozen=True)
class PasswordPolicy:
    """Executes the configured validations against a proposed password."""

    settings: IdentitySettings

    @classmethod
    def default(cls) -> PasswordPolicy:
        return cls(settings=get_settings().identity)

    # ── Entry points ──────────────────────────────────────────────────

    async def validate(self, password: str, *, user_inputs: list[str] | None = None) -> None:
        """Run every check; raise ``PasswordPolicyViolation`` on failure.

        ``user_inputs`` lets callers pass contextual strings (email,
        display name) that zxcvbn penalises when they appear in the
        password — prevents obvious ``alice@acme.com:alice1234``-style
        leaks.
        """
        violations: list[str] = []

        if len(password) < self.settings.password_min_length:
            violations.append(
                f"must be at least {self.settings.password_min_length} characters"
            )

        zxcvbn_result = zxcvbn.zxcvbn(password, user_inputs=user_inputs or [])
        if zxcvbn_result["score"] < self.settings.password_zxcvbn_min_score:
            fb = zxcvbn_result.get("feedback") or {}
            warning = fb.get("warning") or "password is too weak"
            suggestions = fb.get("suggestions") or []
            hint = f"{warning}"
            if suggestions:
                hint = f"{warning}: {'; '.join(suggestions)}"
            violations.append(hint)

        if self.settings.password_check_hibp:
            breached = await self._check_hibp(password)
            if breached:
                violations.append(
                    "this password was found in public data breaches; choose another"
                )

        if violations:
            raise PasswordPolicyViolation(violations)

    # ── HIBP k-anonymity ─────────────────────────────────────────────

    async def _check_hibp(self, password: str) -> bool:
        """Return True when the password appears in HIBP.

        Uses the k-anonymity API:
            GET https://api.pwnedpasswords.com/range/{sha1_prefix}
        Returns lines of ``{sha1_suffix}:{count}``. We never transmit
        the full hash.

        Network failures are logged but do NOT fail the policy — we
        refuse to DoS legitimate registrations because a third-party
        API is down. Consider failing closed only if compliance mandates.
        """
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        url = f"{self.settings.hibp_api_url}/{prefix}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.hibp_timeout_seconds,
                headers={"Add-Padding": "true", "User-Agent": "axon-enterprise"},
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError:
            # Fail open — don't block registrations on an HIBP outage.
            return False
        if resp.status_code != 200:
            return False
        for line in resp.text.splitlines():
            entry, _, count = line.partition(":")
            if entry.strip().upper() == suffix:
                # The API sometimes pads with fake entries having count=0.
                return count.strip() != "0"
        return False
