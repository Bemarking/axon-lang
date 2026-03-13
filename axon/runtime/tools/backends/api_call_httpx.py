"""
AXON Runtime — APICall Backend (v0.11.0, httpx)
=================================================
Real HTTP client tool replacing ``APICallStub``.

Uses ``httpx.AsyncClient`` for non-blocking HTTP requests
with configurable method, headers, body, and timeout.

Addresses weakness **W9** (APICall was stub-only).

Dependencies:
    pip install httpx   # or: pip install axon-lang[tools]
"""

from __future__ import annotations

from typing import Any, ClassVar

from axon.runtime.tools.base_tool import BaseTool, ToolResult
from axon.runtime.tools.tool_schema import ToolParameter, ToolSchema


class APICallHTTPX(BaseTool):
    """Real HTTP API caller via httpx.

    TOOL_NAME matches ``APICallStub.TOOL_NAME`` so the registry
    can transparently replace the stub.

    Config:
        base_url (str, optional): Prefix for relative URLs.
        default_headers (dict, optional): Default headers for all requests.
        timeout (int, optional): Request timeout in seconds (default 30).
    """

    TOOL_NAME: ClassVar[str] = "APICall"
    IS_STUB: ClassVar[bool] = False
    DEFAULT_TIMEOUT: ClassVar[float] = 30.0

    SCHEMA: ClassVar[ToolSchema] = ToolSchema(
        name="APICall",
        description="Make an HTTP request to an external API",
        input_params=(
            ToolParameter("query", "str", required=True,
                          description="The URL to call"),
            ToolParameter("method", "str", required=False,
                          default="GET", description="HTTP method"),
            ToolParameter("headers", "dict", required=False,
                          default=None, description="Request headers"),
            ToolParameter("body", "Any", required=False,
                          default=None, description="Request body (JSON)"),
        ),
        output_type="dict",
        timeout_default=30.0,
    )

    def validate_config(self) -> None:
        """No required config — base_url and headers are optional."""

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Execute an HTTP request.

        Args:
            query:   The URL to call.
            method:  HTTP method (GET, POST, PUT, DELETE). Default: GET.
            headers: Optional dict of HTTP headers.
            body:    Optional JSON body for POST/PUT.

        Returns:
            ToolResult with status_code, headers, and body.
        """
        try:
            import httpx
        except ImportError:
            return ToolResult(
                success=False,
                data=None,
                error=(
                    "httpx is required for APICallHTTPX. "
                    "Install with: pip install httpx"
                ),
            )

        method: str = kwargs.get("method", "GET").upper()
        headers: dict[str, str] = kwargs.get("headers") or {}
        body: Any = kwargs.get("body")
        timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)

        # Apply default headers from config
        default_headers = self.config.get("default_headers", {})
        merged_headers = {**default_headers, **headers}

        # Apply base_url prefix
        url = query
        base_url = self.config.get("base_url", "")
        if base_url and not url.startswith(("http://", "https://")):
            url = f"{base_url.rstrip('/')}/{url.lstrip('/')}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method in ("POST", "PUT", "PATCH"):
                    response = await client.request(
                        method, url,
                        headers=merged_headers,
                        json=body,
                    )
                else:
                    response = await client.request(
                        method, url,
                        headers=merged_headers,
                    )

                response.raise_for_status()

                # Try JSON parse, fall back to text
                try:
                    resp_body = response.json()
                except Exception:
                    resp_body = response.text

                return ToolResult(
                    success=True,
                    data={
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": resp_body,
                        "method": method,
                        "url": str(response.url),
                    },
                    metadata={
                        "is_stub": False,
                        "provider": "httpx",
                    },
                )

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            return ToolResult(
                success=False,
                data={
                    "status_code": status,
                    "body": exc.response.text[:500],
                },
                error=f"HTTP {status} error for {method} {url}",
                metadata={"is_stub": False, "provider": "httpx"},
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                data=None,
                error=f"Request to {url} timed out after {timeout}s",
                metadata={"is_stub": False, "provider": "httpx"},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                data=None,
                error=f"APICall failed: {exc}",
                metadata={"is_stub": False, "provider": "httpx"},
            )
