import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence, TypeVar
from collections.abc import Callable

F = TypeVar("F", bound=Callable[..., Any])

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
globLogger = logging.getLogger(__name__)

from .YARP_mcpServer_Base import *

class Yarp_mcpServer_Notifier(Yarp_mcpServer_Base):

    def __init__(self, conf:yarp.ResourceFinder=None, logger: logging.Logger = globLogger, enableExplicitLogging: bool = True):
        Yarp_mcpServer_Base.__init__(self, conf, logger, enableExplicitLogging)
        # Notification infrastructure for MCP streaming.
        # Clients subscribe with subscribe_notifications(); monitoring tasks then
        # broadcast official notifications/tasks/status messages to those sessions.
        self.notification_sessions = {}
        self.notification_lock = threading.Lock()
        self.task_counter = 0
        self.task_created_at = {}


    def notification_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        notification_kind: str = "task_status",
        notification_method: str = "notifications/tasks/status",
        meta: dict[str, Any] | None = None,
        **tool_kwargs: Any,
    ) -> Callable[[F], F]:
        """
        Register a tool that may emit server-side notifications.

        This only advertises notification capability in tools/list.
        The tool itself must still call _emit_task_status_to_subscribers(...)
        or another notification helper.
        """
        merged_meta = {
            **(meta or {}),
            "x-yarp/emitsNotifications": True,
            "x-yarp/notificationKind": notification_kind,
            "x-yarp/notificationMethod": notification_method
        }

        return self.mcp.tool(
            name=name,
            description=description,
            meta=merged_meta,
            **tool_kwargs,
        )


    def progress_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        meta: dict[str, Any] | None = None,
        **tool_kwargs: Any,
    ) -> Callable[[F], F]:
        """
        Register an MCP tool that may emit request-scoped MCP progress
        notifications through ctx.report_progress(...).

        This does not itself send progress. It only advertises the capability
        in tools/list and delegates normal registration to FastMCP.tool().
        """
        merged_meta = {
            **(meta or {}),
            "x-yarp/emitsProgress": True,
            "x-yarp/progressNotificationMethod": "notifications/progress",
        }

        return self.mcp.tool(
            name=name,
            description=description,
            meta=merged_meta,
            **tool_kwargs,
        )


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
                self.fancyLog.DEBUG(f"Failed to emit task notification to session {session_key}: {e}")
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

    def _register_common_tools(self):
        """Register common MCP tools for notification subscription."""
        @self.mcp.tool()
        async def subscribe_notifications(ctx: Context) -> dict[str, Any]:
            f"""Subscribe this MCP session to server-side {self.server_name} task notifications."""
            session_key = self._register_notification_session(ctx.session)
            return {
                "success": True,
                "session_key": session_key,
                "message": f"Subscribed to {self.server_name} task notifications"
            }