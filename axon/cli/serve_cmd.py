"""
axon serve — Start the AxonServer process.

Boots the reactive event loop, supervisor tree, and HTTP/WS API.

Usage:
    axon serve [--host HOST] [--port PORT] [--channel BACKEND]
               [--auth-token TOKEN] [--log-level LEVEL]
               [--strict-type-driven-transport]
"""

from __future__ import annotations

import os
import sys
from argparse import Namespace


# §Fase 31.f (D7) — Cross-stack truthy alphabet contract.
# The Python parser MUST match the Rust `parse_truthy_env` byte-
# identically (same value set, same case-insensitivity, same
# whitespace handling). Drift would break the D7 contract.
_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def _parse_truthy_env(name: str) -> bool:
    """Parse a truthy env var per the D7 cross-stack contract.

    Truthy values (case-insensitive, whitespace-trimmed):
        "1", "true", "yes", "on"
    Empty / unset / any other value → False.

    Mirror of `axon::axon_server::parse_truthy_env` (Rust). The
    truthy alphabet is intentionally small + opinionated so adopters
    get consistent behavior across both stacks.
    """
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUTHY_VALUES


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

    # §Fase 31.f — Resolution order (highest precedence first):
    #   1. CLI flag --strict-type-driven-transport
    #   2. Env var AXON_STRICT_TYPE_DRIVEN_TRANSPORT
    #   3. D6 default False (v1.22.x backwards-compat)
    cli_strict = bool(getattr(args, "strict_type_driven_transport", False))
    strict_mode = cli_strict or _parse_truthy_env(
        "AXON_STRICT_TYPE_DRIVEN_TRANSPORT"
    )

    config = AxonServerConfig(
        host=args.host,
        port=args.port,
        channel_backend=args.channel,
        auth_token=getattr(args, "auth_token", ""),
        log_level=getattr(args, "log_level", "INFO"),
        strict_type_driven_transport=strict_mode,
    )

    server = AxonServer(config)
    app = create_app(server)

    print(f"⚡ AxonServer starting on {config.host}:{config.port}")
    print(f"  channel: {config.channel_backend}")
    print(f"  state:   {config.state_backend}")
    print(f"  auth:    {'enabled' if config.auth_token else 'disabled'}")
    # §Fase 31.f — Surface the strict flag at startup so operators
    # can confirm it's set in the runtime context (matches the Rust
    # binary's startup banner pattern).
    print(
        f"  strict transport: "
        f"{'ENABLED (D1 inference rules wire)' if config.strict_type_driven_transport else 'disabled (Fase 30 D4+D5 semantics)'}"
    )

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )

    return 0
