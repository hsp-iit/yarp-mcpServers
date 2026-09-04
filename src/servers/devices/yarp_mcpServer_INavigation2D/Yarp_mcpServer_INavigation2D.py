#!/usr/bin/env python3
"""
MCP Server for YARP INavigation2D, ILocalization2D, and IMap2D interfaces (Streamable HTTP)

Run:
    pip install uvicorn fastapi
    python mcpServer_yarpNav.py
Then the MCP endpoint will be available at:
    http://127.0.0.1:4002/mcp
"""

import asyncio
import sys
import logging
import json
import threading
import time
import argparse
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from ...lib_server.YARP_mcpServer_DeviceBase import *
from ...lib_server.operation_models import (
    OperationErrorResult,
    OperationSnapshot,
    StartOperationResult,
)

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
globLogger = logging.getLogger(__name__)

class Yarp_mcpServer_INavigation2D(Yarp_mcpServer_DeviceBase):
    """MCP Server for YARP INavigation2D, ILocalization2D, and IMap2D interfaces (Streamable HTTP)"""

    def __init__(self, conf=None, logger: logging.Logger = globLogger, enableExplicitLogging: bool = True):
        self.navigation_interface = None
        server_name = "yarp_mcpServer_INavigation2D"
        self.device_name = "navigation2D_nwc_yarp"
        self.remote_port = "/navigation2D_nws_yarp"
        self.local_port = "/navigation2D_nwc_yarp"
        self.navigation_server = "/navigation2D_nws_yarp"
        self.map_locations_server = "/map2D_nws_yarp"
        self.localization_server = "/localization2D_nws_yarp"

        if conf:
            if not conf.check("device"):
                conf.setDefault("device",self.device_name)
            if not conf.check("local"):
                conf.setDefault("local",self.local_port)
            if not conf.check("navigation_server"):
                conf.setDefault("navigation_server",self.navigation_server)
            if not conf.check("map_locations_server"):
                conf.setDefault("map_locations_server",self.map_locations_server)
            if not conf.check("localization_server"):
                conf.setDefault("localization_server",self.localization_server)
            if not conf.check("server_name"):
                conf.setDefault("server_name", server_name)

        Yarp_mcpServer_DeviceBase.__init__(self, conf, logger, enableExplicitLogging)

        self.driver_options.put("navigation_server", conf.find("navigation_server").asString())
        self.driver_options.put("map_locations_server", conf.find("map_locations_server").asString())
        self.driver_options.put("localization_server", conf.find("localization_server").asString())


    def _navigation_status_name(self, status: Any) -> str:
        """Convert a YARP navigation status enum into a stable string."""
        status_names = {
            yarp.navigation_status_idle: 'idle',
            yarp.navigation_status_preparing_before_move: 'preparing_before_move',
            yarp.navigation_status_moving: 'moving',
            yarp.navigation_status_waiting_obstacle: 'waiting_obstacle',
            yarp.navigation_status_goal_reached: 'goal_reached',
            yarp.navigation_status_aborted: 'aborted',
            yarp.navigation_status_failing: 'failing',
            yarp.navigation_status_paused: 'paused',
            yarp.navigation_status_thinking: 'thinking',
            yarp.navigation_status_error: 'error'
        }
        return status_names.get(int(status), f'unknown({int(status)})')

    async def _cancel_operation(self, operation_id: str) -> OperationSnapshot:
        """Stop physical navigation before cancelling its monitoring operation."""
        operation = await self.operation_registry.get(operation_id)
        if operation.status == "working" and operation.operation_type.startswith("navigation_"):
            if not self.is_initialized or self.navigation_interface is None:
                raise RuntimeError("Navigation system is not initialized; cannot stop the robot")
            stopped = await self._call_yarp(self.navigation_interface.stopNavigation)
            if not stopped:
                raise RuntimeError("YARP rejected the request to stop navigation")
        return await super()._cancel_operation(operation_id)

    async def _navigation_monitor_loop(
        self,
        operation_id: str,
        command_tool: str,
        target_data: dict[str, Any],
        poll_interval: float,
        timeout: float,
    ) -> None:
        """Poll navigation status and update the operation resource."""
        start_time = time.monotonic()
        last_status_name = None
        seen_active_navigation = False
        active_statuses = {
            "preparing_before_move", "moving", "waiting_obstacle", "paused", "thinking",
        }
        terminal_success = {"goal_reached"}
        terminal_failure = {"aborted", "failing", "error"}

        try:
            await self.operation_registry.update(
                operation_id,
                status="working",
                details={
                    **target_data,
                    "command_tool": command_tool,
                    "navigation_status": "command_sent",
                },
                status_message=f"Navigation command accepted for {command_tool}",
            )
            await asyncio.sleep(poll_interval)

            while True:
                if not self.is_initialized or self.navigation_interface is None:
                    await self.operation_registry.update(
                        operation_id,
                        status="failed",
                        details={
                            **target_data,
                            "command_tool": command_tool,
                        },
                        error={"message": "Navigation system not initialized"},
                        status_message="Navigation monitor failed: interface not initialized",
                    )
                    return

                status_code = await self._call_yarp(self.navigation_interface.getNavigationStatus)
                status_name = self._navigation_status_name(status_code)
                data = {
                    **target_data,
                    "command_tool": command_tool,
                    "navigation_status": status_name,
                    "navigation_status_code": int(status_code),
                }

                if status_name != last_status_name:
                    await self.operation_registry.update(
                        operation_id,
                        status="working",
                        details=data,
                        status_message=f"Navigation status: {status_name}",
                    )
                    last_status_name = status_name

                if status_name in active_statuses:
                    seen_active_navigation = True

                if status_name in terminal_success:
                    await self.operation_registry.update(
                        operation_id,
                        status="completed",
                        details=data,
                        result=data,
                        status_message="Navigation goal reached",
                    )
                    return

                # Some navigation implementations transition directly from an
                # active state to idle instead of retaining goal_reached long
                # enough for a polling client to observe it.
                if status_name == "idle" and seen_active_navigation:
                    await self.operation_registry.update(
                        operation_id,
                        status="completed",
                        details=data,
                        result=data,
                        status_message="Navigation completed and returned to idle",
                    )
                    return

                if status_name in terminal_failure:
                    await self.operation_registry.update(
                        operation_id,
                        status="failed",
                        details=data,
                        error={"message": f"Navigation ended with status: {status_name}"},
                        status_message=f"Navigation ended with status: {status_name}",
                    )
                    return

                if timeout > 0 and time.monotonic() - start_time >= timeout:
                    await self.operation_registry.update(
                        operation_id,
                        status="failed",
                        details=data,
                        error={"message": "timeout", "timeout_seconds": timeout},
                        status_message=f"Navigation monitor timed out after {timeout:.1f}s",
                    )
                    return

                self.fancyLog.INFO(f"Navigation monitor {operation_id}: status={status_name}, elapsed={time.monotonic() - start_time:.1f}s")

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            await self.operation_registry.update(
                operation_id,
                status="cancelled",
                details={
                    **target_data,
                    "command_tool": command_tool,
                },
                status_message="Navigation monitor cancelled",
            )
            raise
        except Exception as e:
            self.fancyLog.ERROR(f"Navigation monitor {operation_id} failed: {e}")
            await self.operation_registry.update(
                operation_id,
                status="failed",
                details={
                    **target_data,
                    "command_tool": command_tool,
                },
                error={"message": str(e)},
                status_message=f"Navigation monitor failed: {e}",
            )

    def _register_internal_tools(self):
        """Register MCP tools"""

        # ===================== NAVIGATION TOOLS =====================
        @self.mcp.tool(structured_output=True)
        async def goto_target_by_absolute_location(
            x: float, y: float, theta: float,
        ) -> StartOperationResult | OperationErrorResult:
            """Navigate the robot to an absolute location in the map. Coordinates are in meters and theta is in degrees."""
            if not self.is_initialized:
                return OperationErrorResult(
                    error="Navigation system not initialized. Call initialize_yarp_navigation first."
                )

            try:
                location = yarp.Map2DLocation()
                location.x = x
                location.y = y
                location.theta = theta

                result = await self._call_yarp(
                    self.navigation_interface.gotoTargetByAbsoluteLocation, location,
                )
                target_data = {
                    "target_x": x,
                    "target_y": y,
                    "target_theta": theta
                }

                if not result:
                    return OperationErrorResult(error="Failed to send navigation command")

                operation = await self.operation_registry.create(
                    "navigation_absolute",
                    status_message="Absolute navigation command accepted",
                    details={**target_data, "command_tool": "goto_target_by_absolute_location"},
                    poll_interval_ms=250,
                )
                await self._start_operation_task(operation, self._navigation_monitor_loop(
                    operation_id=operation.operation_id,
                    command_tool="goto_target_by_absolute_location",
                    target_data=target_data,
                    poll_interval=0.25,
                    timeout=300.0,
                ))
                return StartOperationResult(
                    operation_id=operation.operation_id,
                    operation_type=operation.operation_type,
                    status_uri=operation.status_uri,
                    poll_interval_ms=operation.poll_interval_ms,
                    message="Navigation command sent; operation monitoring is active",
                )
            except Exception as e:
                self.fancyLog.ERROR(f"Error in goto_target: {e}")
                return OperationErrorResult(error=f"Navigation error: {str(e)}")

        @self.mcp.tool(structured_output=True)
        async def goto_target_by_relative_location(
            x: float, y: float, theta: float = 0.0,
        ) -> StartOperationResult | OperationErrorResult:
            """Navigate the robot by a relative displacement from its current location. x and y are in meters, theta is in degrees."""
            if not self.is_initialized:
                return OperationErrorResult(
                    error="Navigation system not initialized. Call initialize_yarp_navigation first."
                )

            try:
                result = await self._call_yarp(
                    self.navigation_interface.gotoTargetByRelativeLocation, x, y, theta,
                )
                target_data = {
                    "relative_x": x,
                    "relative_y": y,
                    "relative_theta": theta
                }

                if not result:
                    return OperationErrorResult(error="Failed to send relative navigation command")

                operation = await self.operation_registry.create(
                    "navigation_relative",
                    status_message="Relative navigation command accepted",
                    details={**target_data, "command_tool": "goto_target_by_relative_location"},
                    poll_interval_ms=250,
                )
                await self._start_operation_task(operation, self._navigation_monitor_loop(
                    operation_id=operation.operation_id,
                    command_tool="goto_target_by_relative_location",
                    target_data=target_data,
                    poll_interval=0.25,
                    timeout=300.0,
                ))
                return StartOperationResult(
                    operation_id=operation.operation_id,
                    operation_type=operation.operation_type,
                    status_uri=operation.status_uri,
                    poll_interval_ms=operation.poll_interval_ms,
                    message="Relative navigation command sent; operation monitoring is active",
                )
            except Exception as e:
                self.fancyLog.ERROR(f"Error in goto_target_by_relative_location: {e}")
                return OperationErrorResult(error=f"Relative navigation error: {str(e)}")

        @self.mcp.tool(structured_output=True)
        async def follow_path(
            waypoints: list[dict[str, float]],
        ) -> StartOperationResult | OperationErrorResult:
            """Follow a path defined by a sequence of waypoints. Each waypoint is a dict with x, y, and theta (in degrees)."""
            if not self.is_initialized:
                return OperationErrorResult(
                    error="Navigation system not initialized. Call initialize_yarp_navigation first."
                )

            if not waypoints or len(waypoints) == 0:
                return OperationErrorResult(error="At least one waypoint is required")

            try:
                # Create a vector of locations
                locations = yarp.Map2DLocationVector()
                for wp in waypoints:
                    if 'x' not in wp or 'y' not in wp:
                        return OperationErrorResult(
                            error="Each waypoint must have 'x' and 'y' coordinates"
                        )

                    loc = yarp.Map2DLocation()
                    loc.x = wp['x']
                    loc.y = wp['y']
                    loc.theta = wp.get('theta', 0.0)
                    locations.push_back(loc)

                # Create path data
                path = yarp.Map2DPath()
                path.waypoints = locations

                result = await self._call_yarp(self.navigation_interface.followPath, path)
                target_data = {
                    "waypoints_count": len(waypoints),
                    "waypoints": waypoints
                }

                if not result:
                    return OperationErrorResult(error="Failed to send path command")

                operation = await self.operation_registry.create(
                    "navigation_path",
                    status_message="Path navigation command accepted",
                    details={**target_data, "command_tool": "follow_path"},
                    poll_interval_ms=250,
                )
                await self._start_operation_task(operation, self._navigation_monitor_loop(
                    operation_id=operation.operation_id,
                    command_tool="follow_path",
                    target_data=target_data,
                    poll_interval=0.25,
                    timeout=300.0,
                ))
                return StartOperationResult(
                    operation_id=operation.operation_id,
                    operation_type=operation.operation_type,
                    status_uri=operation.status_uri,
                    poll_interval_ms=operation.poll_interval_ms,
                    message="Path navigation command sent; operation monitoring is active",
                )
            except Exception as e:
                self.fancyLog.ERROR(f"Error in follow_path: {e}")
                return OperationErrorResult(error=f"Path following error: {str(e)}")

        @self.mcp.tool()
        async def get_current_position() -> dict[str, Any]:
            """Get the current position and orientation of the robot."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                # Use the reference parameter version which works better with SWIG
                location = yarp.Map2DLocation()
                result = await self._call_yarp(
                    self.navigation_interface.getCurrentPosition, location,
                )

                if result:
                    return {
                        "success": True,
                        "x": location.x,
                        "y": location.y,
                        "theta": location.theta,
                        "map_id": location.map_id
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to get current position"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_current_position: {e}")
                return {
                    "success": False,
                    "error": f"Position retrieval error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_navigation_status() -> dict[str, Any]:
            """
            Get the current navigation status (idle, moving, goal_reached, aborted, etc.).
            x-monitoring metadata:
            {
                "pollable": true,
                "expected_fields": ["status", "success", "status_code"],
                "suggested_conditions": ["status == 'goal_reached'"],
                "polling_suggestion": "1.0 second"
            }
            """
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                status = await self._call_yarp(self.navigation_interface.getNavigationStatus)
                status_name = self._navigation_status_name(status)

                return {
                    "success": True,
                    "status": status_name,
                    "status_code": int(status)
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_navigation_status: {e}")
                return {
                    "success": False,
                    "error": f"Status retrieval error: {str(e)}"
                }

        @self.mcp.tool()
        async def stop_navigation() -> dict[str, Any]:
            """Stop the current navigation immediately."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(self.navigation_interface.stopNavigation)

                if result:
                    active_operations = await self.operation_registry.list(active_only=True)
                    for operation in active_operations:
                        if operation.operation_type.startswith("navigation_"):
                            await self.operation_registry.cancel(operation.operation_id)

                return {
                    "success": bool(result),
                    "message": "Navigation stopped successfully" if result else "Failed to stop navigation"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in stop_navigation: {e}")
                return {
                    "success": False,
                    "error": f"Stop error: {str(e)}"
                }

        @self.mcp.tool()
        async def suspend_navigation() -> dict[str, Any]:
            """Suspend the current navigation (can be resumed later)."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(self.navigation_interface.suspendNavigation)

                return {
                    "success": bool(result),
                    "message": "Navigation suspended successfully" if result else "Failed to suspend navigation"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in suspend_navigation: {e}")
                return {
                    "success": False,
                    "error": f"Suspend error: {str(e)}"
                }

        @self.mcp.tool()
        async def resume_navigation() -> dict[str, Any]:
            """Resume a previously suspended navigation."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(self.navigation_interface.resumeNavigation)

                return {
                    "success": bool(result),
                    "message": "Navigation resumed successfully" if result else "Failed to resume navigation"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in resume_navigation: {e}")
                return {
                    "success": False,
                    "error": f"Resume error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_absolute_target_location() -> dict[str, Any]:
            """Get the absolute location of the current navigation target."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                # Use the reference parameter version which works better with SWIG
                location = yarp.Map2DLocation()
                result = await self._call_yarp(
                    self.navigation_interface.getAbsoluteLocationOfCurrentTarget, location,
                )

                if result:
                    return {
                        "success": True,
                        "target_x": location.x,
                        "target_y": location.y,
                        "target_theta": location.theta,
                        "map_id": location.map_id
                    }
                else:
                    return {
                        "success": False,
                        "error": "No current target"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_absolute_target_location: {e}")
                return {
                    "success": False,
                    "error": f"Target location query error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_connection_status() -> dict[str, Any]:
            """Get the current status of the YARP navigation connection."""
            try:
                status = {
                    "initialized": self.is_initialized,
                    "device_valid": False,
                    "interface_available": False,
                    "yarp_network_available": False
                }

                if self.yarp_network:
                    status["yarp_network_available"] = self.yarp_network.checkNetwork()

                if self.device_driver:
                    status["device_valid"] = self.device_driver.isValid()

                if self.navigation_interface:
                    status["interface_available"] = True

                return {
                    "success": True,
                    "status": status
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error checking connection status: {e}")
                return {
                    "success": False,
                    "error": f"Connection status error: {str(e)}"
                }

        # ===================== LOCALIZATION TOOLS =====================

        @self.mcp.tool()
        async def start_localization_service() -> dict[str, Any]:
            """Start the localization service."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.startLocalizationService
                )

                return {
                    "success": bool(result),
                    "message": "Localization service started" if result else "Failed to start localization service"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in start_localization_service: {e}")
                return {
                    "success": False,
                    "error": f"Localization start error: {str(e)}"
                }

        @self.mcp.tool()
        async def stop_localization_service() -> dict[str, Any]:
            """Stop the localization service."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.stopLocalizationService
                )

                return {
                    "success": bool(result),
                    "message": "Localization service stopped" if result else "Failed to stop localization service"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in stop_localization_service: {e}")
                return {
                    "success": False,
                    "error": f"Localization stop error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_localization_status() -> dict[str, Any]:
            """Get the current status of the localization service."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                status = await self._call_yarp(
                    self.navigation_interface.getLocalizationStatus
                )

                status_names = {
                    0: 'not_yet_localized',
                    1: 'localized_ok',
                    2: 'error'
                }

                status_name = status_names.get(int(status), f'unknown({int(status)})')

                return {
                    "success": True,
                    "status": status_name,
                    "status_code": int(status)
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_localization_status: {e}")
                return {
                    "success": False,
                    "error": f"Localization status error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_estimated_poses() -> dict[str, Any]:
            """Get all pose estimates computed by the localization algorithm."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                poses = yarp.Map2DLocationVector()
                result = await self._call_yarp(
                    self.navigation_interface.getEstimatedPoses, poses,
                )

                poses_list = []
                for i in range(poses.size()):
                    pose = poses.get(i)
                    poses_list.append({
                        "x": pose.x,
                        "y": pose.y,
                        "theta": pose.theta,
                        "map_id": pose.map_id
                    })

                return {
                    "success": bool(result),
                    "poses": poses_list,
                    "pose_count": len(poses_list)
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_estimated_poses: {e}")
                return {
                    "success": False,
                    "error": f"Pose estimation error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_estimated_odometry() -> dict[str, Any]:
            """Get the estimated odometry including robot velocity."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                x_odom = yarp.DVector(1)
                y_odom = yarp.DVector(1)
                theta_odom = yarp.DVector(1)
                vx = yarp.DVector(1)
                vy = yarp.DVector(1)
                vtheta = yarp.DVector(1)

                result = await self._call_yarp(
                    self.navigation_interface.getEstimatedOdometry,
                    x_odom, y_odom, theta_odom, vx, vy, vtheta,
                )

                if result:
                    return {
                        "success": True,
                        "x": float(x_odom[0]),
                        "y": float(y_odom[0]),
                        "theta": float(theta_odom[0]),
                        "vx": float(vx[0]),
                        "vy": float(vy[0]),
                        "vtheta": float(vtheta[0])
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to get odometry data"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_estimated_odometry: {e}")
                return {
                    "success": False,
                    "error": f"Odometry retrieval error: {str(e)}"
                }

        @self.mcp.tool()
        async def set_initial_pose(x: float, y: float, theta: float, map_id: str = "") -> dict[str, Any]:
            """Set the initial pose for the localization algorithm."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                location = yarp.Map2DLocation()
                location.x = x
                location.y = y
                location.theta = theta
                location.map_id = map_id

                result = await self._call_yarp(
                    self.navigation_interface.setInitialPose, location,
                )

                return {
                    "success": bool(result),
                    "x": x,
                    "y": y,
                    "theta": theta,
                    "map_id": map_id,
                    "message": "Initial pose set successfully" if result else "Failed to set initial pose"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in set_initial_pose: {e}")
                return {
                    "success": False,
                    "error": f"Set initial pose error: {str(e)}"
                }

        # ===================== MAP MANAGEMENT TOOLS =====================

        @self.mcp.tool()
        async def store_location(location_name: str, x: float, y: float, theta: float, map_id: str = "") -> dict[str, Any]:
            """Store a named location in the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                location = yarp.Map2DLocation()
                location.x = x
                location.y = y
                location.theta = theta
                location.map_id = map_id

                result = await self._call_yarp(
                    self.navigation_interface.storeLocation, location_name, location,
                )

                return {
                    "success": bool(result),
                    "location_name": location_name,
                    "x": x,
                    "y": y,
                    "theta": theta,
                    "message": "Location stored successfully" if result else "Failed to store location"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in store_location: {e}")
                return {
                    "success": False,
                    "error": f"Store location error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_location(location_name: str) -> dict[str, Any]:
            """Retrieve a named location from the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                location = yarp.Map2DLocation()
                result = await self._call_yarp(
                    self.navigation_interface.getLocation, location_name, location,
                )

                if result:
                    return {
                        "success": True,
                        "location_name": location_name,
                        "x": location.x,
                        "y": location.y,
                        "theta": location.theta,
                        "map_id": location.map_id
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Location '{location_name}' not found"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_location: {e}")
                return {
                    "success": False,
                    "error": f"Get location error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_locations_list() -> dict[str, Any]:
            """Get the list of all stored location names."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                locations = await self._call_yarp(
                    self.navigation_interface.getLocationsList
                )
                locations = [loc for loc in locations]

                if True:
                    return {
                        "success": True,
                        "locations": locations,
                        "location_count": len(locations)
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to get locations list"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_locations_list: {e}")
                return {
                    "success": False,
                    "error": f"Get locations list error: {str(e)}"
                }

        @self.mcp.tool()
        async def delete_location(location_name: str) -> dict[str, Any]:
            """Delete a named location from the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.deleteLocation, location_name,
                )

                return {
                    "success": bool(result),
                    "location_name": location_name,
                    "message": "Location deleted successfully" if result else "Failed to delete location"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in delete_location: {e}")
                return {
                    "success": False,
                    "error": f"Delete location error: {str(e)}"
                }

        @self.mcp.tool()
        async def rename_location(original_name: str, new_name: str) -> dict[str, Any]:
            """Rename a stored location."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.renameLocation, original_name, new_name,
                )

                return {
                    "success": bool(result),
                    "original_name": original_name,
                    "new_name": new_name,
                    "message": "Location renamed successfully" if result else "Failed to rename location"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in rename_location: {e}")
                return {
                    "success": False,
                    "error": f"Rename location error: {str(e)}"
                }

        @self.mcp.tool()
        async def store_area(area_name: str, x1: float, y1: float, x2: float, y2: float, map_id: str = "") -> dict[str, Any]:
            """Store a rectangular area in the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                # Create two points (bottom-left and top-right corners)
                area = yarp.Map2DArea()
                area.map_id = map_id
                # Store the two corners as a rectangle
                area.points = yarp.Vector2DVector()

                point1 = yarp.Vector2D(x1, y1)
                point2 = yarp.Vector2D(x2, y2)
                area.points.push_back(point1)
                area.points.push_back(point2)

                result = await self._call_yarp(
                    self.navigation_interface.storeArea, area_name, area,
                )

                return {
                    "success": bool(result),
                    "area_name": area_name,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "message": "Area stored successfully" if result else "Failed to store area"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in store_area: {e}")
                return {
                    "success": False,
                    "error": f"Store area error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_area(area_name: str) -> dict[str, Any]:
            """Retrieve a named area from the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                area = yarp.Map2DArea()
                result = await self._call_yarp(
                    self.navigation_interface.getArea, area_name, area,
                )

                if result:
                    points = []
                    if hasattr(area, 'points') and area.points:
                        for i in range(area.points.size()):
                            p = area.points.get(i)
                            points.append({"x": p.x, "y": p.y})

                    return {
                        "success": True,
                        "area_name": area_name,
                        "points": points,
                        "map_id": area.map_id
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Area '{area_name}' not found"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_area: {e}")
                return {
                    "success": False,
                    "error": f"Get area error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_areas_list() -> dict[str, Any]:
            """Get the list of all stored area names."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                areas = await self._call_yarp(self.navigation_interface.getAreasList)
                areas = [area for area in areas]

                if True:
                    return {
                        "success": True,
                        "areas": areas,
                        "area_count": len(areas)
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to get areas list"
                    }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in get_areas_list: {e}")
                return {
                    "success": False,
                    "error": f"Get areas list error: {str(e)}"
                }

        @self.mcp.tool()
        async def delete_area(area_name: str) -> dict[str, Any]:
            """Delete a named area from the map server."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.deleteArea, area_name,
                )

                return {
                    "success": bool(result),
                    "area_name": area_name,
                    "message": "Area deleted successfully" if result else "Failed to delete area"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in delete_area: {e}")
                return {
                    "success": False,
                    "error": f"Delete area error: {str(e)}"
                }

        @self.mcp.tool()
        async def check_inside_area(area_name: str) -> dict[str, Any]:
            """Check if the robot is currently inside a specified area."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                is_inside = False
                result = await self._call_yarp(
                    self.navigation_interface.checkInsideArea, area_name, is_inside,
                )

                return {
                    "success": bool(result),
                    "area_name": area_name,
                    "is_inside": is_inside
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in check_inside_area: {e}")
                return {
                    "success": False,
                    "error": f"Check inside area error: {str(e)}"
                }

        @self.mcp.tool()
        async def store_current_position(location_name: str) -> dict[str, Any]:
            """Store the current robot position as a named location."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.storeCurrentPosition, location_name,
                )

                return {
                    "success": bool(result),
                    "location_name": location_name,
                    "message": "Current position stored successfully" if result else "Failed to store current position"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in store_current_position: {e}")
                return {
                    "success": False,
                    "error": f"Store current position error: {str(e)}"
                }

        @self.mcp.tool()
        async def save_locations_and_extras(file_name: str) -> dict[str, Any]:
            """Save all stored locations and extras to a file."""
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "Navigation system not initialized. Call initialize_yarp_navigation first."
                }

            try:
                result = await self._call_yarp(
                    self.navigation_interface.saveLocationsAndExtras, file_name,
                )

                return {
                    "success": bool(result),
                    "file_name": file_name,
                    "message": "Locations and extras saved successfully" if result else "Failed to save locations and extras"
                }
            except Exception as e:
                self.fancyLog.ERROR(f"Error in save_locations_and_extras: {e}")
                return {
                    "success": False,
                    "error": f"Save locations and extras error: {str(e)}"
                }

        # Start YARP RPC info port in a background thread
        self._start_info_port()

    def _build_system_prompt_addendum_old(self) -> str:
        """Build system prompt addendum for the client to modify LLM behavior"""
        return """
If the user asks for relative movements like "go forward 1 meter" or "turn right 90 degrees", take into consideration
the current robot orientation (let's call it theta) and position in order to compute the correct absolute target location and follow this rule:
Forward means moving in the direction of the current robot orientation (movement direction is theta),
Backward means moving in the opposite direction of the current robot orientation (movement direction is theta + 180 degrees),
left means turning clockwise from the current robot orientation (movement direction is theta + 90 degrees),
Right means turning counterclockwise from the current robot orientation (movement direction is theta - 90 degrees).
Consider also that X of the map is aligned with 0 degrees orientation, Y is aligned with 90 degrees orientation.
ALWAYS provide the absolute target location in the map reference frame as X, Y coordinates and orientation in degrees, when the user asks for relative movements.
Do NOT respond with relative movements, ALWAYS convert them to absolute target locations.
        """

    def _build_system_prompt_addendum_old_new(self) -> str:
        """Build system prompt addendum for the client to modify LLM behavior"""
        return """
If the user asks for relative movements like "go forward 1 meter" or "turn right 90 degrees", use your current position and orientation to compute the correct absolute target location.
Forward means moving in the direction of the current robot orientation. Backward means moving in the opposite direction of the current robot orientation. Increasing theta value means turning counterclockwise, decreasing theta means turning clockwise.
Consider also that X of the map is aligned with 0 degrees orientation, Y is aligned with 90 degrees orientation.
ALWAYS provide the absolute target location in the map reference frame as X, Y coordinates and orientation in degrees, when the user asks for relative movements.
        """

    def _build_system_prompt_addendum(self) -> str:
        """Build system prompt addendum for the client to modify LLM behavior"""
        return """
═════════════════════════════════════════════════════════════════════════════════
NAVIGATION SERVER INSTRUCTIONS:
═════════════════════════════════════════════════════════════════════════════════

COORDINATE SYSTEM & ORIENTATION:
- Remember that left means rotating counterclockwise (increasing theta)
- Right means rotating clockwise (decreasing theta) from the current robot orientation
- X of the map is aligned with 0 degrees orientation
- Y is aligned with 90 degrees orientation

MONITORING FOR NAVIGATION (CRITICAL):
When the user asks you to navigate somewhere, ALWAYS follow this pattern:
  1. Call goto_target_by_absolute_location() or goto_target_by_relative_location()
  2. Keep the returned operation_id and status_uri
  3. Tell the user navigation started and the operation is monitored automatically
  4. Use get_operation_status() if an explicit status check is requested

Example Navigation with Monitoring:
  User: "Navigate to the kitchen (x=5, y=3)"
  → Call: goto_target_by_absolute_location(x=5.0, y=3.0, theta=0.0)
  → Response: "Starting navigation to coordinates (5.0, 3.0). I'll monitor progress and notify you when complete."

Navigation Status Values:
The get_navigation_status() tool returns: idle, preparing, moving, waiting_obstacle, goal_reached, aborted, failing, paused, thinking, error

Relative Movement Conversion:
If the user asks for relative movements like "go forward 1 meter" or "turn right 90 degrees":
  - Get current position using get_current_position()
  - Convert relative movement to absolute coordinates
  - Call goto_target_by_absolute_location() with the computed absolute target
  - Monitor the navigation as described above

Example Relative Navigation:
  User: "Go forward 2 meters"
  → Call: get_current_position() to get current x, y, theta
  → Compute: new_x = current_x + 2.0 * cos(theta_radians), new_y = current_y + 2.0 * sin(theta_radians)
  → Call: goto_target_by_absolute_location(x=new_x, y=new_y, theta=current_theta)
  → Response: "Moving forward 2 meters with monitoring enabled. I'll notify you when complete."
═════════════════════════════════════════════════════════════════════════════════""".lstrip("\n")

    async def cleanup(self) -> None:
        """Stop navigation operations and release the YARP resources."""
        self.fancyLog.INFO("Cleaning up YARP navigation resources...")
        try:
            await self._cleanup_operations()
        finally:
            self._close_resource("device_driver", "navigation device driver")
            self.navigation_interface = None
            self._finalize_yarp_network()
            self.is_initialized = False
            self._cleanup_base_resources()
        self.fancyLog.INFO("YARP navigation resources cleaned up successfully.")

    def _interfaceView(self, devDriver:yarp.PolyDriver) -> bool:

        # Get INavigation2D interface
        self.navigation_interface = devDriver.viewINavigation2D()

        if self.navigation_interface is None:
            self.fancyLog.ERROR("Failed to get INavigation2D interface")
            return False

        return True


if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_INavigation2D(config)
    server.run()
