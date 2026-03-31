"""
AXON Server Package
=====================
The AxonServer — reactive daemon execution platform.

Usage:
    from axon.server import AxonServer, AxonServerConfig

    server = AxonServer(AxonServerConfig(port=8420))
    await server.start()
    result = await server.deploy(source_code)
    await server.stop()

CLI:
    axon serve --port 8420 --channel memory
"""

from axon.server.config import AxonServerConfig
from axon.server.server import AxonServer, DaemonInfo, DeployResult

__all__ = [
    "AxonServer",
    "AxonServerConfig",
    "DeployResult",
    "DaemonInfo",
]
