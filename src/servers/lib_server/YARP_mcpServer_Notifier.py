from abc import ABC, abstractmethod
import threading
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence
import logging

# MCP imports
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.models import InitializationOptions
from mcp.types import (
    Tool,
    LoggingLevel,
    ServerNotification,
    TaskStatusNotification,
    TaskStatusNotificationParams
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Yarp_mcpServer_Notifier(ABC):

    def __init__(self):
        # Notification infrastructure for MCP streaming.
        # Clients subscribe with subscribe_notifications(); monitoring tasks then
        # broadcast official notifications/tasks/status messages to those sessions.
        self.notification_sessions = {}
        self.notification_lock = threading.Lock()
        self.task_counter = 0
        self.task_created_at = {}


    def _new_task_id(self, prefix: str) -> str:
        """Generate a unique server-side monitoring task ID."""
        with self.notification_lock:
            self.task_counter += 1
            return f"{prefix}_{self.task_counter}_{uuid.uuid4().hex[:8]}"

    def _register_notification_session(self, session: Any) -> str:
        """Remember a session that wants server-side task notifications."""
        session_key = str(id(session))
        with self.notification_lock:
            self.notification_sessions[session_key] = session
        return session_key

    def _task_created_time(self, task_id: str) -> datetime:
        """Return the original creation time for a task notification."""
        with self.notification_lock:
            return self.task_created_at.setdefault(task_id, datetime.now(timezone.utc))

    async def _emit_task_status_to_subscribers(
        self,
        task_id: str,
        status: str,
        tool: str,
        data: dict[str, Any] | None = None,
        status_message: str | None = None,
        event: str | None = None,
    ) -> None:
        """Emit an official MCP task-status notification to subscribed sessions."""
        created_at = self._task_created_time(task_id)
        params = TaskStatusNotificationParams(
            taskId=task_id,
            status=status,
            statusMessage=status_message,
            createdAt=created_at,
            lastUpdatedAt=datetime.now(timezone.utc),
            ttl=None,
            tool=tool,
            event=event or status,
            data=data or {},
        )
        notification = ServerNotification(TaskStatusNotification(params=params))

        with self.notification_lock:
            sessions = list(self.notification_sessions.items())

        dead_sessions = []
        for session_key, session in sessions:
            try:
                await session.send_notification(notification)
            except Exception as e:
                logger.debug(f"Failed to emit task notification to session {session_key}: {e}")
                dead_sessions.append(session_key)

        if dead_sessions:
            with self.notification_lock:
                for session_key in dead_sessions:
                    self.notification_sessions.pop(session_key, None)

    async def _emit_tool_snapshot(self, tool: str, data: dict[str, Any]) -> None:
        """Broadcast a non-terminal snapshot from a synchronous getter tool."""
        task_id = self._new_task_id(f"{tool}_snapshot")
        await self._emit_task_status_to_subscribers(
            task_id=task_id,
            status="working",
            tool=tool,
            data=data,
            status_message=f"{tool} status update",
            event="status_changed",
        )
        with self.notification_lock:
            self.task_created_at.pop(task_id, None)