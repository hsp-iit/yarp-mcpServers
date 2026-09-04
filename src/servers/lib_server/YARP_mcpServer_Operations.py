"""MCP v2 operation resources and management tools for YARP servers."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from mcp.server.subscriptions import ResourceUpdated

from .YARP_mcpServer_Base import Yarp_mcpServer_Base, globLogger, yarp
from .operation_models import OperationListResult, OperationSnapshot, StartOperationResult
from .operation_registry import OperationNotFoundError, OperationRegistry


class Yarp_mcpServer_Operations(Yarp_mcpServer_Base):
    """Base class for servers exposing durable, subscribable operation state."""

    def __init__(
        self,
        conf: yarp.ResourceFinder | None = None,
        logger: logging.Logger = globLogger,
        enableExplicitLogging: bool = True,
    ) -> None:
        super().__init__(conf, logger, enableExplicitLogging)
        self.operation_registry = OperationRegistry(
            self.server_name,
            self._publish_operation_update,
        )
        self._operation_cleanup_task: asyncio.Task[Any] | None = None
        self._operation_loop: asyncio.AbstractEventLoop | None = None

    async def _publish_operation_update(self, status_uri: str) -> None:
        await self.subscription_bus.publish(ResourceUpdated(status_uri))

    async def _start_operation_task(
        self,
        operation: OperationSnapshot,
        coroutine: Any,
    ) -> None:
        task = asyncio.create_task(coroutine, name=f"yarp-operation-{operation.operation_id}")
        await self.operation_registry.attach_task(operation.operation_id, task)

    async def _cleanup_operations(self) -> None:
        owner_loop = self._operation_loop
        current_loop = asyncio.get_running_loop()
        if owner_loop is not None and owner_loop is not current_loop and owner_loop.is_running():
            cleanup = asyncio.run_coroutine_threadsafe(
                self._cleanup_operations_on_owner_loop(), owner_loop
            )
            try:
                cleanup.result(timeout=5)
            except concurrent.futures.TimeoutError as exc:
                cleanup.cancel()
                raise TimeoutError("Timed out while stopping server operations") from exc
            return

        await self._cleanup_operations_on_owner_loop()

    async def _cleanup_operations_on_owner_loop(self) -> None:
        cleanup_task, self._operation_cleanup_task = self._operation_cleanup_task, None
        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        await self.operation_registry.shutdown()
        self._operation_loop = None

    async def _start_operation_maintenance(self) -> None:
        self._operation_loop = asyncio.get_running_loop()
        if self._operation_cleanup_task is None:
            self._operation_cleanup_task = asyncio.create_task(
                self._operation_maintenance_loop(),
                name=f"expire-yarp-operations-{self.server_name}",
            )

    async def _operation_maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            removed = await self.operation_registry.remove_expired()
            if removed:
                self.fancyLog.DEBUG(f"Expired {removed} retained operation(s)")

    async def _cancel_operation(self, operation_id: str) -> OperationSnapshot:
        """Cancellation hook for servers that must also stop domain-level work."""
        return await self.operation_registry.cancel(operation_id)

    def _register_common_tools(self) -> None:
        """Register standard tools and the authoritative operation resource."""

        @self.mcp.tool()
        async def get_operation_status(operation_id: str) -> OperationSnapshot:
            """Get the current state of a server-side YARP operation."""
            try:
                return await self.operation_registry.get(operation_id)
            except OperationNotFoundError as exc:
                raise ValueError(f"Unknown operation: {operation_id}") from exc

        @self.mcp.tool()
        async def list_operations(active_only: bool = True) -> OperationListResult:
            """List retained operations, optionally limiting the result to active work."""
            operations = await self.operation_registry.list(active_only=active_only)
            return OperationListResult(
                operations=operations,
                total=len(operations),
                active=sum(item.status == "working" for item in operations),
            )

        @self.mcp.tool()
        async def cancel_operation(operation_id: str) -> OperationSnapshot:
            """Request cooperative cancellation of a server-side operation."""
            try:
                return await self._cancel_operation(operation_id)
            except OperationNotFoundError as exc:
                raise ValueError(f"Unknown operation: {operation_id}") from exc

        @self.mcp.resource(
            f"yarp-operation://{self.server_name}/{{operation_id}}",
            mime_type="application/json",
        )
        async def operation_status(operation_id: str) -> OperationSnapshot:
            """Authoritative state for one asynchronous YARP operation."""
            try:
                return await self.operation_registry.get(operation_id)
            except OperationNotFoundError as exc:
                raise ValueError(f"Unknown operation: {operation_id}") from exc


__all__ = [
    "OperationSnapshot",
    "StartOperationResult",
    "Yarp_mcpServer_Operations",
]
