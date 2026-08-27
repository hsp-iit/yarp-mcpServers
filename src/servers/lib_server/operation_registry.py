"""Concurrency-safe lifecycle management for long-running YARP operations."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .operation_models import OperationSnapshot, OperationStatus


class OperationNotFoundError(KeyError):
    """Raised when an operation ID is unknown or has expired."""


class InvalidOperationTransitionError(RuntimeError):
    """Raised when code attempts to mutate a terminal operation."""


class OperationRegistry:
    """Store operation state and publish resource invalidations after commits."""

    TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

    def __init__(
        self,
        server_name: str,
        publish_update: Callable[[str], Awaitable[None]],
        *,
        terminal_retention: timedelta = timedelta(minutes=30),
    ) -> None:
        self._server_name = server_name
        self._publish_update = publish_update
        self._terminal_retention = terminal_retention
        self._operations: dict[str, OperationSnapshot] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    def status_uri(self, operation_id: str) -> str:
        return f"yarp-operation://{self._server_name}/{operation_id}"

    async def create(
        self,
        operation_type: str,
        *,
        status_message: str | None = None,
        details: dict[str, Any] | None = None,
        poll_interval_ms: int = 1000,
    ) -> OperationSnapshot:
        operation_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        snapshot = OperationSnapshot(
            operation_id=operation_id,
            operation_type=operation_type,
            status="working",
            status_message=status_message,
            created_at=now,
            updated_at=now,
            poll_interval_ms=poll_interval_ms,
            status_uri=self.status_uri(operation_id),
            details=details or {},
        )
        async with self._lock:
            self._operations[operation_id] = snapshot
        return snapshot.model_copy(deep=True)

    async def get(self, operation_id: str) -> OperationSnapshot:
        async with self._lock:
            snapshot = self._operations.get(operation_id)
            if snapshot is None:
                raise OperationNotFoundError(operation_id)
            return snapshot.model_copy(deep=True)

    async def list(self, *, active_only: bool = False) -> list[OperationSnapshot]:
        async with self._lock:
            snapshots = self._operations.values()
            if active_only:
                snapshots = (item for item in snapshots if item.status not in self.TERMINAL_STATUSES)
            return [item.model_copy(deep=True) for item in snapshots]

    async def update(
        self,
        operation_id: str,
        *,
        status: OperationStatus | None = None,
        status_message: str | None = None,
        progress: float | None = None,
        details: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> OperationSnapshot:
        async with self._lock:
            current = self._operations.get(operation_id)
            if current is None:
                raise OperationNotFoundError(operation_id)

            if current.status in self.TERMINAL_STATUSES:
                if status is None or status == current.status:
                    return current.model_copy(deep=True)
                raise InvalidOperationTransitionError(
                    f"Operation {operation_id} is already {current.status}"
                )

            changes: dict[str, Any] = {
                "updated_at": datetime.now(timezone.utc),
                "revision": current.revision + 1,
            }
            if status is not None:
                changes["status"] = status
            if status_message is not None:
                changes["status_message"] = status_message
            if progress is not None:
                changes["progress"] = progress
            if details is not None:
                changes["details"] = {**current.details, **details}
            if result is not None:
                changes["result"] = result
            if error is not None:
                changes["error"] = error

            # model_copy(update=...) deliberately skips Pydantic validation.
            # Re-validate the complete snapshot so bounds and status types stay
            # true even when updates originate in device-specific loops.
            updated = OperationSnapshot.model_validate({
                **current.model_dump(),
                **changes,
            })
            self._operations[operation_id] = updated

        # State is authoritative before subscribers are told to refetch it.
        await self._publish_update(updated.status_uri)
        return updated.model_copy(deep=True)

    async def attach_task(self, operation_id: str, task: asyncio.Task[Any]) -> None:
        async with self._lock:
            if operation_id not in self._operations:
                task.cancel()
                raise OperationNotFoundError(operation_id)
            self._tasks[operation_id] = task

        def forget(completed: asyncio.Task[Any]) -> None:
            try:
                loop = completed.get_loop()
                loop.create_task(self._forget_task(operation_id, completed))
            except RuntimeError:
                pass

        task.add_done_callback(forget)

    async def _forget_task(self, operation_id: str, task: asyncio.Task[Any]) -> None:
        async with self._lock:
            if self._tasks.get(operation_id) is task:
                self._tasks.pop(operation_id, None)

    async def cancel(self, operation_id: str) -> OperationSnapshot:
        async with self._lock:
            current = self._operations.get(operation_id)
            if current is None:
                raise OperationNotFoundError(operation_id)
            task = self._tasks.get(operation_id)

        if current.status in self.TERMINAL_STATUSES:
            return current.model_copy(deep=True)
        if task is not None:
            task.cancel()
        return await self.update(
            operation_id,
            status="cancelled",
            status_message="Cancellation requested",
        )

    async def remove_expired(self) -> int:
        cutoff = datetime.now(timezone.utc) - self._terminal_retention
        async with self._lock:
            expired = [
                operation_id
                for operation_id, snapshot in self._operations.items()
                if snapshot.status in self.TERMINAL_STATUSES and snapshot.updated_at <= cutoff
            ]
            for operation_id in expired:
                self._operations.pop(operation_id, None)
                self._tasks.pop(operation_id, None)
            return len(expired)

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
