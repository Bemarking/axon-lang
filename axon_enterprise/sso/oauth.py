"""OAuth 2.0 authentication provider."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class OAuthConfig:
    """Configuration for OAuth 2.0 provider."""

    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: list[str] = None
    redirect_uri: str = ""

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = ["openid", "email", "profile"]


class OAuthProvider:
    """OAuth 2.0 authentication provider implementation."""

    def __init__(self, config: OAuthConfig):
        """Initialize OAuth provider."""
        self.config = config

    def get_authorization_url(self, state: str) -> str:
        """Get OAuth authorization URL."""
        # TODO: Build authorization URL with state parameter
        return ""

    async def exchange_code_for_token(self, code: str) -> Optional[str]:
        """Exchange authorization code for access token."""
        # TODO: POST to token_url with code
        return None

    async def get_user_info(self, access_token: str) -> Optional[dict]:
        """Get user information using access token."""
        # TODO: GET userinfo_url with Bearer token
        return None
