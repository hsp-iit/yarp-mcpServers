# Server architecture

## Discovery and transport

Each server exposes a YARP RPC info port at `/mcp_server/<name>/info:o`. It answers
`get_name`, `get_mcp_url`, and `get_system_prompt_addendum`. This is discovery
metadata only. Tools, resources, and subscription events travel over MCP
Streamable HTTP at the advertised `/mcp` URL.

`Yarp_mcpServer_Base` constructs the SDK `MCPServer`, installs an
`InMemorySubscriptionBus`, registers the subclass surface, and hands the ASGI app
to Uvicorn. Its MCP lifespan shuts down any operation registry before transport
termination.

## Long-running work

`Yarp_mcpServer_Operations` adds three common tools:

- `get_operation_status(operation_id)` reads one retained operation.
- `list_operations(active_only=True)` lists active or retained operations.
- `cancel_operation(operation_id)` requests cooperative cancellation.

It also registers the resource template
`yarp-operation://<server_name>/{operation_id}`. `OperationRegistry` is the
authoritative state owner. Device loops call `update()`, which validates and
commits a new snapshot under a lock and only then publishes `ResourceUpdated`.
The event is therefore a refetch hint, never the state payload.

The registry owns worker tasks, cancels them on shutdown, prevents mutation away
from terminal states, and can evict terminal records after a retention period.
The operations base exposes `_cancel_operation()` as a domain hook. Navigation
uses it to stop robot motion before committing a cancelled snapshot.

## Device path

`Yarp_mcpServer_DeviceBase` constructs a `yarp.PolyDriver` from configuration and
asks each concrete server for its interface view. Concrete tools translate typed
MCP inputs into calls on that view. A long-running tool must create its operation
only after YARP accepts the command, then attach its monitoring coroutine through
`_start_operation_task()`.

YARP Python bindings are synchronous. Async MCP tools invoke them through the
device base's locked `_call_yarp()` helper, which uses a worker thread. This keeps
the MCP event loop responsive to operation-resource reads and cancellation while
a network wrapper is waiting for a YARP reply, and prevents concurrent calls on
the same device interface.

## Adding a synchronous device server

1. Add a package under `src/servers/devices/`.
2. Subclass `Yarp_mcpServer_DeviceBase`.
3. Implement `_interfaceView`, `_register_internal_tools`, and the normal cleanup
   hooks used by existing device servers.
4. Register typed functions with `@self.mcp.tool()`.
5. Add launcher configuration and tests for argument translation and YARP errors.

## Adding a long-running tool

Follow [ASYNC_OPERATIONS.md](ASYNC_OPERATIONS.md). Do not add session registries,
raw JSON-RPC notification methods, tool-name correlation, or separate per-device
task dictionaries. Those duplicate responsibilities already owned by the SDK
subscription bus and `OperationRegistry`.
