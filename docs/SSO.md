# SSO (Single Sign-On)

## Supported Providers

- **SAML 2.0**: Enterprise standard (Okta, Azure AD, Ping, etc.)
- **OAuth 2.0**: Generic provider support
- **OpenID Connect**: Modern standard (Google, Microsoft, Auth0)

## SAML 2.0 Configuration

```python
from axon_enterprise.sso.saml import SAMLProvider, SAMLConfig

config = SAMLConfig(
    idp_url="https://idp.example.com/sso",
    entity_id="https://axon.example.com",
    certificate="-----BEGIN CERTIFICATE-----\n...",
    private_key="-----BEGIN PRIVATE KEY-----\n...",
)

saml = SAMLProvider(config)
```

## OAuth 2.0 Configuration

```python
from axon_enterprise.sso.oauth import OAuthProvider, OAuthConfig

config = OAuthConfig(
    client_id="your-client-id",
    client_secret="your-client-secret",
    authorize_url="https://auth.example.com/authorize",
    token_url="https://auth.example.com/token",
    userinfo_url="https://auth.example.com/userinfo",
)

oauth = OAuthProvider(config)
```

## OpenID Connect Configuration

```python
from axon_enterprise.sso.oidc import OIDCProvider, OIDCConfig

config = OIDCConfig(
    issuer_url="https://accounts.google.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
)

oidc = OIDCProvider(config)
```

## Integration with Server

```python
@app.post("/auth/login")
async def login_sso(provider: str):
    if provider == "saml":
        url = await saml.initiate_sso()
    elif provider == "oauth":
        url = oauth.get_authorization_url(state)
    
    return RedirectResponse(url)

@app.post("/auth/callback")
async def sso_callback(request):
    saml_response = request.form.get("SAMLResponse")
    user_data = await saml.handle_assertion(saml_response)
    
    # Create session...
    return {"token": session_token}
```

## Best Practices

- Store certificates in secure environment variables
- Validate all SAML responses before processing
- Use PKCE flow for OAuth 2.0 public clients
- Implement certificate rotation before expiry
- Log all SSO authentication attempts in audit log
