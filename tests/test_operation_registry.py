import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.client.subscriptions import ResourceUpdated
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from pydantic import ValidationError

from src.servers.lib_server.operation_models import (
    OperationErrorResult,
    OperationSnapshot,
    StartOperationResult,
)
from src.servers.lib_server.operation_registry import (
    InvalidOperationTransitionError,
    OperationNotFoundError,
    OperationRegistry,
)
from src.servers.devices.yarp_mcpServer_INavigation2D.Yarp_mcpServer_INavigation2D import (
    Yarp_mcpServer_INavigation2D,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_update_commits_before_publishing() -> None:
    published_snapshots = []
    registry = None

    async def publish(uri: str) -> None:
        operation_id = uri.rsplit("/", 1)[-1]
        published_snapshots.append(await registry.get(operation_id))

    registry = OperationRegistry("battery", publish)
    created = await registry.create("battery_charge")
    updated = await registry.update(
        created.operation_id,
        status_message="Charging",
        progress=0.25,
        details={"charge": 25.0},
    )

    assert updated.revision == 1
    assert published_snapshots == [updated]
    assert published_snapshots[0].details == {"charge": 25.0}


@pytest.mark.anyio
async def test_terminal_state_is_final_and_validated() -> None:
    registry = OperationRegistry("navigation", lambda _uri: asyncio.sleep(0))
    operation = await registry.create("navigation")

    with pytest.raises(ValidationError):
        await registry.update(operation.operation_id, progress=1.5)

    finished = await registry.update(operation.operation_id, status="completed", result={"ok": True})
    repeated = await registry.update(operation.operation_id, status="completed")
    assert repeated == finished

    with pytest.raises(InvalidOperationTransitionError):
        await registry.update(operation.operation_id, status="failed")


@pytest.mark.anyio
async def test_cancel_and_expire_operation() -> None:
    registry = OperationRegistry(
        "battery", lambda _uri: asyncio.sleep(0), terminal_retention=timedelta(0),
    )
    operation = await registry.create("battery_charge")
    worker = asyncio.create_task(asyncio.Event().wait())
    await registry.attach_task(operation.operation_id, worker)

    cancelled = await registry.cancel(operation.operation_id)
    await asyncio.gather(worker, return_exceptions=True)
    assert cancelled.status == "cancelled"
    assert await registry.remove_expired() == 1
    with pytest.raises(OperationNotFoundError):
        await registry.get(operation.operation_id)


@pytest.mark.anyio
async def test_sdk_tool_resource_and_subscription_round_trip() -> None:
    bus = InMemorySubscriptionBus()
    server = MCPServer(name="operation-test", subscriptions=bus)

    async def publish(uri: str) -> None:
        await bus.publish(ResourceUpdated(uri))

    registry = OperationRegistry("test", publish)

    @server.tool(structured_output=True)
    async def start_test_operation(accept: bool = True) -> StartOperationResult | OperationErrorResult:
        if not accept:
            return OperationErrorResult(error="Rejected")
        operation = await registry.create("test", poll_interval_ms=100)
        return StartOperationResult(
            operation_id=operation.operation_id,
            operation_type=operation.operation_type,
            status_uri=operation.status_uri,
            poll_interval_ms=operation.poll_interval_ms,
            message="Accepted",
        )

    @server.resource("yarp-operation://test/{operation_id}", mime_type="application/json")
    async def operation_status(operation_id: str) -> OperationSnapshot:
        return await registry.get(operation_id)

    async with Client(
        server, mode="2026-07-28", cache=None, read_timeout_seconds=1,
    ) as client:
        rejected = await client.call_tool("start_test_operation", {"accept": False})
        assert rejected.structured_content["result"] == {
            "success": False,
            "error": "Rejected",
        }

        started = await client.call_tool("start_test_operation", {})
        assert started.is_error is False
        structured = started.structured_content
        if "result" in structured:
            structured = structured["result"]
        operation_id = structured["operation_id"]
        status_uri = structured["status_uri"]
        initial_resource = await client.read_resource(status_uri)
        assert json.loads(initial_resource.contents[0].text)["status"] == "working"

        async with client.listen(resource_subscriptions=[status_uri]) as events:
            await registry.update(operation_id, status="completed", result={"answer": 42})
            event = await asyncio.wait_for(anext(events), timeout=1)
            assert isinstance(event, ResourceUpdated)
            assert str(event.uri) == status_uri

        resource = await client.read_resource(status_uri)
        snapshot = json.loads(resource.contents[0].text)
        assert snapshot["status"] == "completed"
        assert snapshot["result"] == {"answer": 42}


@pytest.mark.anyio
async def test_navigation_cancellation_stops_robot_before_monitor() -> None:
    registry = OperationRegistry("navigation", lambda _uri: asyncio.sleep(0))
    operation = await registry.create("navigation_relative")

    class NavigationInterface:
        stop_calls = 0

        def stopNavigation(self):
            self.stop_calls += 1
            return True

    server = object.__new__(Yarp_mcpServer_INavigation2D)
    server.operation_registry = registry
    async def call_yarp(function, *args):
        return function(*args)
    server._call_yarp = call_yarp
    server.navigation_interface = NavigationInterface()
    server.is_initialized = True
    server.info_port = None
    server.device_driver = None
    server.yarp_network = None

    cancelled = await server._cancel_operation(operation.operation_id)
    assert cancelled.status == "cancelled"
    assert server.navigation_interface.stop_calls == 1


@pytest.mark.anyio
async def test_navigation_active_to_idle_completes_operation() -> None:
    registry = OperationRegistry("navigation", lambda _uri: asyncio.sleep(0))
    operation = await registry.create("navigation_relative")

    class NavigationInterface:
        statuses = iter([1, 0])

        def getNavigationStatus(self):
            return next(self.statuses)

    server = object.__new__(Yarp_mcpServer_INavigation2D)
    server.operation_registry = registry
    server.navigation_interface = NavigationInterface()
    async def call_yarp(function, *args):
        return function(*args)
    server._call_yarp = call_yarp
    server.is_initialized = True
    server.info_port = None
    server.device_driver = None
    server.yarp_network = None
    server.fancyLog = SimpleNamespace(INFO=lambda *_args: None, ERROR=lambda *_args: None)
    original_status_name = server._navigation_status_name
    server._navigation_status_name = lambda status: {1: "moving", 0: "idle"}[int(status)]

    await server._navigation_monitor_loop(
        operation.operation_id,
        "goto_target_by_relative_location",
        {"relative_x": 1.0, "relative_y": 0.0},
        poll_interval=0.001,
        timeout=1.0,
    )

    completed = await registry.get(operation.operation_id)
    assert completed.status == "completed"
    assert completed.status_message == "Navigation completed and returned to idle"
    server._navigation_status_name = original_status_name
