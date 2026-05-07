"""Interactive API documentation renderers — ``/docs`` (Swagger UI) and
``/redoc`` (ReDoc).

Both are static HTML pages that load assets from public CDNs and point
their renderer at ``/openapi.json``. No server-side rendering.

Security note: assets are served from unpkg / jsdelivr without subresource
integrity (SRI) hashes — same default as FastAPI, accepted for most use
cases. High-security adopters should reverse-proxy these pages with their
own CSP headers, or self-host the Swagger UI / ReDoc bundles. Pin major
versions to avoid surprise UI breakage.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

# Pinned to known-good major versions. Bump deliberately, not transitively.
_SWAGGER_UI_VERSION = "5.17.14"
_REDOC_VERSION = "2.1.5"

_SWAGGER_UI_CSS = (
    f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui.css"
)
_SWAGGER_UI_JS = (
    f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
)
_REDOC_JS = (
    f"https://cdn.jsdelivr.net/npm/redoc@{_REDOC_VERSION}/bundles/redoc.standalone.js"
)

_OPENAPI_URL = "/openapi.json"
_TITLE = "axon-enterprise Portal API"


def _swagger_ui_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <link rel="stylesheet" href="{_SWAGGER_UI_CSS}" />
    <title>{_TITLE} — Swagger UI</title>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="{_SWAGGER_UI_JS}"></script>
    <script>
      window.ui = SwaggerUIBundle({{
        url: "{_OPENAPI_URL}",
        dom_id: "#swagger-ui",
        deepLinking: true,
        layout: "BaseLayout",
        showExtensions: true,
        showCommonExtensions: true,
      }});
    </script>
  </body>
</html>
"""


def _redoc_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <link rel="shortcut icon" href="data:," />
    <title>{_TITLE} — ReDoc</title>
    <style>body {{ margin: 0; padding: 0; }}</style>
  </head>
  <body>
    <redoc spec-url="{_OPENAPI_URL}"></redoc>
    <script src="{_REDOC_JS}"></script>
  </body>
</html>
"""


async def swagger_ui_endpoint(request: Request) -> Response:
    return HTMLResponse(_swagger_ui_html())


async def redoc_endpoint(request: Request) -> Response:
    return HTMLResponse(_redoc_html())
