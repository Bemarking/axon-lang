"""
axon deploy — Deploy an .axon file to a running AxonServer.

Sends the source to the server's /v1/deploy endpoint.

Usage:
    axon deploy <file.axon> [--server URL] [--backend BACKEND]
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path


def cmd_deploy(args: Namespace) -> int:
    """Execute the ``axon deploy`` subcommand."""
    try:
        import httpx
    except ImportError:
        print(
            "✗ httpx is required for 'axon deploy'. "
            "Install it with: pip install axon-lang[server]",
            file=sys.stderr,
        )
        return 2

    path = Path(args.file)
    if not path.exists():
        print(f"✗ File not found: {path}", file=sys.stderr)
        return 2

    source = path.read_text(encoding="utf-8")
    server_url = args.server.rstrip("/")

    payload = {
        "source": source,
        "backend": args.backend,
    }

    headers = {"Content-Type": "application/json"}
    if hasattr(args, "auth_token") and args.auth_token:
        headers["Authorization"] = f"Bearer {args.auth_token}"

    try:
        resp = httpx.post(
            f"{server_url}/v1/deploy",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
    except httpx.ConnectError:
        print(f"✗ Cannot connect to AxonServer at {server_url}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"✗ Deploy failed: {exc}", file=sys.stderr)
        return 1

    data = resp.json()

    if data.get("success"):
        print(f"✓ Deployed to {server_url}")
        print(f"  deployment_id: {data['deployment_id']}")
        print(f"  flows compiled: {data['flows_compiled']}")
        daemons = data.get("daemons_registered", [])
        if daemons:
            print(f"  daemons: {', '.join(daemons)}")
        return 0
    else:
        print(f"✗ Deploy failed: {data.get('error', 'unknown')}", file=sys.stderr)
        return 1
