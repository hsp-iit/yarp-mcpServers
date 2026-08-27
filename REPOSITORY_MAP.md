# Repository map

This repository hosts MCP servers that adapt YARP devices, RPC endpoints, and
resources. Each launched server publishes its MCP URL through a small YARP info
port; the client then uses MCP directly.

## Start here

| Path | Responsibility |
|---|---|
| `yarp_server_launcher.py` | Loads configuration and launches selected servers. |
| `src/modules/McpConfigParser.py` | Converts YARP configuration into server instances. |
| `src/servers/lib_server/YARP_mcpServer_Base.py` | MCP server, subscription bus, ASGI transport, YARP discovery port, and lifespan. |
| `src/servers/lib_server/YARP_mcpServer_Operations.py` | Standard operation tools/resource and resource-update publication. |
| `src/servers/lib_server/operation_models.py` | Typed public operation contract. |
| `src/servers/lib_server/operation_registry.py` | Locked state store, transitions, cancellation, retention, and task ownership. |
| `src/servers/lib_server/YARP_mcpServer_DeviceBase.py` | YARP `PolyDriver` setup shared by device servers. |
| `src/servers/devices/` | MCP adapters for YARP device interfaces. |
| `src/servers/rpc/` | MCP adapters for YARP RPC services. |
| `src/servers/resources/` | Resource-oriented servers, including JSON data. |
| `tests/` | Operation lifecycle unit tests. |
| `ASYNC_OPERATIONS.md` | Contract, extension recipe, and failure semantics. |
| `ARCHITECTURE.md` | Inheritance, lifecycle, and data-flow overview. |

## Server inheritance

```text
Yarp_mcpServer_Base
        |
Yarp_mcpServer_Operations
        |
Yarp_mcpServer_DeviceBase
        |
        +-- IBattery
        +-- INavigation2D
        +-- ISpeechSynthesizer
```

Battery and navigation create long-running operations. Speech synthesis inherits
the common operation management surface but currently exposes synchronous tools.
RPC servers may inherit the base directly when they do not need operation state.

## Commands

```bash
uv sync --group dev
uv run python yarp_server_launcher.py --from <configuration.xml>
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --group dev pytest -p anyio.pytest_plugin -q
```

The test command disables unrelated pytest plugins commonly installed with ROS.
