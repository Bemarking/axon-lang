"""
axon serve — Start the AxonServer process.

Boots the reactive event loop, supervisor tree, and HTTP/WS API.

Usage:
    axon serve [--host HOST] [--port PORT] [--channel BACKEND]
               [--auth-token TOKEN] [--log-level LEVEL]
"""

from __future__ import annotations

import sys
from argparse import Namespace


def cmd_serve(args: Namespace) -> int:
    """Execute the ``axon serve`` subcommand."""
    try:
        import uvicorn
    except ImportError:
        print(
            "✗ uvicorn is required for 'axon serve'. "
            "Install it with: pip install axon-lang[server]",
            file=sys.stderr,
        )
        return 2

    from axon.server.config import AxonServerConfig
    from axon.server.server import AxonServer
    from axon.server.http_app import create_app

    config = AxonServerConfig(
        host=args.host,
        port=args.port,
        channel_backend=args.channel,
        auth_token=getattr(args, "auth_token", ""),
        log_level=getattr(args, "log_level", "INFO"),
    )

    server = AxonServer(config)
    app = create_app(server)

    print(f"⚡ AxonServer starting on {config.host}:{config.port}")
    print(f"  channel: {config.channel_backend}")
    print(f"  state:   {config.state_backend}")
    print(f"  auth:    {'enabled' if config.auth_token else 'disabled'}")

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )

    return 0
