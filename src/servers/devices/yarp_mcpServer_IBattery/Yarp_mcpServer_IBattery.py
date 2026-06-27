#!/usr/bin/env python3
"""
MCP Server for YARP IBattery interface (Streamable HTTP)

Run:
    pip install uvicorn fastapi
    python mcpServer_yarpBattery.py
Then the MCP endpoint will be available at:
    http://127.0.0.1:4001/mcp
"""
import asyncio
import logging
from typing import Any, Sequence
import sys
import os
import json
import inspect
import time
import argparse


from ...lib_server.YARP_mcpServer_DeviceBase import Yarp_mcpServer_DeviceBase
from ...lib_server.YARP_mcpServer_Notifier import Yarp_mcpServer_Notifier

# MCP imports
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.models import InitializationOptions
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel,
    ServerNotification,
    TaskStatusNotification,
    TaskStatusNotificationParams
)

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Yarp_mcpServer_IBattery(Yarp_mcpServer_DeviceBase, Yarp_mcpServer_Notifier):
    """YARP Battery MCP Server"""

    def __init__(self, conf=None):
        Yarp_mcpServer_DeviceBase.__init__(self, conf)
        Yarp_mcpServer_Notifier.__init__(self)
        self.mcp = FastMCP("YARP Battery Server")
        self.server_name = "battery"
        self.device_name = "battery_nwc_yarp"
        self.remote_port = "/battery_nws_yarp"
        self.local_port = "/battery_nwc_yarp"

        if conf:
            if conf.check("yarp_device"):
                self.device_name = conf.find("yarp_device").asString()
            if conf.check("yarp_remote"):
                self.remote_port = conf.find("yarp_remote").asString()
            if conf.check("yarp_local"):
                self.local_port = conf.find("yarp_local").asString()
        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"
        self.system_prompt_addendum = self._build_system_prompt_addendum()

        # Register tools
        self._register_tools()


    async def _battery_charge_monitor_loop(
        self,
        task_id: str,
        threshold: float,
        direction: str,
        poll_interval: float,
        timeout: float,
    ) -> None:
        """Poll battery charge and notify subscribers when the threshold is crossed."""
        start_time = time.monotonic()
        comparison = "<" if direction == "below" else ">"

        try:
            await self._emit_task_status_to_subscribers(
                task_id=task_id,
                status="working",
                tool="get_battery_charge",
                data={
                    "threshold": threshold,
                    "direction": direction,
                    "condition": f"charge {comparison} {threshold}",
                },
                status_message=f"Monitoring battery charge until it is {direction} {threshold}%",
                event="started",
            )
            await asyncio.sleep(poll_interval)

            while True:
                if self.battery_interface is None:
                    await self._emit_task_status_to_subscribers(
                        task_id=task_id,
                        status="failed",
                        tool="get_battery_charge",
                        data={
                            "threshold": threshold,
                            "direction": direction,
                            "error": "YARP battery not initialized",
                        },
                        status_message="Battery monitor failed: interface not initialized",
                        event="failed",
                    )
                    return

                charge = self.battery_interface.getBatteryCharge()
                crossed = charge < threshold if direction == "below" else charge > threshold
                data = {
                    "charge": charge,
                    "unit": "percent",
                    "threshold": threshold,
                    "direction": direction,
                    "condition": f"charge {comparison} {threshold}",
                }

                if crossed:
                    await self._emit_task_status_to_subscribers(
                        task_id=task_id,
                        status="completed",
                        tool="get_battery_charge",
                        data=data,
                        status_message=f"Battery charge is {charge:.1f}%, {direction} threshold {threshold:.1f}%",
                        event="complete",
                    )
                    return

                if timeout > 0 and time.monotonic() - start_time >= timeout:
                    data["error"] = "timeout"
                    await self._emit_task_status_to_subscribers(
                        task_id=task_id,
                        status="failed",
                        tool="get_battery_charge",
                        data=data,
                        status_message=f"Battery monitor timed out after {timeout:.1f}s",
                        event="timeout",
                    )
                    return

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            await self._emit_task_status_to_subscribers(
                task_id=task_id,
                status="cancelled",
                tool="get_battery_charge",
                data={
                    "threshold": threshold,
                    "direction": direction,
                },
                status_message="Battery charge monitor cancelled",
                event="cancelled",
            )
            raise
        except Exception as e:
            logger.error(f"Battery charge monitor {task_id} failed: {e}")
            await self._emit_task_status_to_subscribers(
                task_id=task_id,
                status="failed",
                tool="get_battery_charge",
                data={
                    "threshold": threshold,
                    "direction": direction,
                    "error": str(e),
                },
                status_message=f"Battery monitor failed: {e}",
                event="failed",
            )
        finally:
            with self.notification_lock:
                self.battery_monitor_tasks.pop(task_id, None)

    def _register_tools(self):
        """Register MCP tools"""

        @self.mcp.tool()
        async def subscribe_notifications(ctx: Context) -> dict[str, Any]:
            """Subscribe this MCP session to server-side battery task notifications."""
            session_key = self._register_notification_session(ctx.session)
            return {
                "success": True,
                "session_key": session_key,
                "message": "Subscribed to battery server task notifications"
            }

        @self.mcp.tool()
        async def get_battery_voltage() -> dict[str, Any]:
            """Get the instantaneous battery voltage measurement in volts."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                voltage = self.battery_interface.getBatteryVoltage()

                return {
                    "success": True,
                    "voltage": voltage,
                    "unit": "volts"
                }

            except Exception as e:
                logger.error(f"Error getting battery voltage: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get voltage: {str(e)}"
                }

        @self.mcp.tool()
        async def get_battery_current() -> dict[str, Any]:
            """Get the instantaneous battery current measurement in amperes."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                current = self.battery_interface.getBatteryCurrent()

                return {
                    "success": True,
                    "current": current,
                    "unit": "amperes"
                }

            except Exception as e:
                logger.error(f"Error getting battery current: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get current: {str(e)}"
                }

        @self.mcp.tool()
        async def get_battery_charge() -> dict[str, Any]:
            """
            Get the battery charge level (state of charge) as a percentage (0-100%).
            x-monitoring metadata:
            {
                "pollable": true,
                "expected_fields": ["charge"],
                "suggested_conditions": ["charge < 20"],
                "polling_suggestion": "1.0 second"
            }
            """
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                charge = self.battery_interface.getBatteryCharge()

                await self._emit_tool_snapshot(
                    "get_battery_charge",
                    {
                        "charge": charge,
                        "unit": "percent"
                    }
                )

                return {
                    "success": True,
                    "charge": charge,
                    "unit": "percent"
                }

            except Exception as e:
                logger.error(f"Error getting battery charge: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get charge: {str(e)}"
                }

        @self.mcp.tool()
        async def start_battery_charge_monitor(
            threshold: float,
            direction: str = "below",
            poll_interval: float = 1.0,
            timeout: float = 0.0,
        ) -> dict[str, Any]:
            """Start a server-side task that notifies when battery charge crosses a threshold.

            direction must be "below" or "above". A timeout of 0 disables timeout.
            Notifications are sent as MCP notifications/tasks/status messages to
            subscribed clients.
            """
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            direction_normalized = direction.lower().strip()
            aliases = {
                "under": "below",
                "less": "below",
                "low": "below",
                "over": "above",
                "greater": "above",
                "high": "above",
            }
            direction_normalized = aliases.get(direction_normalized, direction_normalized)
            if direction_normalized not in {"below", "above"}:
                return {
                    "success": False,
                    "error": "direction must be 'below' or 'above'"
                }

            if poll_interval <= 0:
                return {
                    "success": False,
                    "error": "poll_interval must be positive"
                }

            if timeout < 0:
                return {
                    "success": False,
                    "error": "timeout cannot be negative"
                }

            task_id = self._new_task_id("battery_charge")
            task = asyncio.create_task(
                self._battery_charge_monitor_loop(
                    task_id=task_id,
                    threshold=threshold,
                    direction=direction_normalized,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
            )
            with self.notification_lock:
                self.battery_monitor_tasks[task_id] = task

            comparison = "<" if direction_normalized == "below" else ">"
            return {
                "success": True,
                "task_id": task_id,
                "condition": f"charge {comparison} {threshold}",
                "message": f"Started server-side battery monitor {task_id}"
            }

        @self.mcp.tool()
        async def stop_battery_charge_monitor(task_id: str) -> dict[str, Any]:
            """Cancel a server-side battery charge monitor."""
            with self.notification_lock:
                task = self.battery_monitor_tasks.get(task_id)

            if task is None:
                return {
                    "success": False,
                    "error": f"Battery monitor {task_id} not found"
                }

            task.cancel()
            return {
                "success": True,
                "task_id": task_id,
                "message": f"Battery monitor {task_id} cancellation requested"
            }

        @self.mcp.tool()
        async def get_battery_temperature() -> dict[str, Any]:
            """Get the battery temperature in Celsius."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                temperature = self.battery_interface.getBatteryTemperature()

                return {
                    "success": True,
                    "temperature": temperature,
                    "unit": "celsius"
                }

            except Exception as e:
                logger.error(f"Error getting battery temperature: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get temperature: {str(e)}"
                }

        @self.mcp.tool()
        async def get_battery_status() -> dict[str, Any]:
            """Get the overall battery status (OK, charging, in use, error, timeout, low warning, critical warning)."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                status = self.battery_interface.getBatteryStatus()

                # Map status enum to string
                status_map = {
                    0: "BATTERY_OK_STANBY",
                    1: "BATTERY_OK_IN_CHARGE",
                    2: "BATTERY_OK_IN_USE",
                    3: "BATTERY_GENERAL_ERROR",
                    4: "BATTERY_TIMEOUT",
                    5: "BATTERY_LOW_WARNING",
                    6: "BATTERY_CRITICAL_WARNING"
                }

                status_str = status_map.get(status, f"UNKNOWN_STATUS_{status}")

                await self._emit_tool_snapshot(
                    "get_battery_status",
                    {
                        "status": status_str,
                        "status_code": status
                    }
                )

                return {
                    "success": True,
                    "status": status_str,
                    "status_code": status
                }

            except Exception as e:
                logger.error(f"Error getting battery status: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get status: {str(e)}"
                }

        @self.mcp.tool()
        async def get_battery_info() -> dict[str, Any]:
            """Get battery hardware characteristics and information."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                info = self.battery_interface.getBatteryInfo()

                return {
                    "success": True,
                    "info": info
                }

            except Exception as e:
                logger.error(f"Error getting battery info: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get info: {str(e)}"
                }

        @self.mcp.tool()
        async def get_all_battery_data() -> dict[str, Any]:
            """Get all battery measurements and status in a single call (voltage, current, charge, temperature, status, info)."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                data = {
                    "success": True
                }

                # Get all measurements
                try:
                    data["voltage"] = self.battery_interface.getBatteryVoltage()
                except Exception as e:
                    data["voltage_error"] = str(e)

                try:
                    data["current"] = self.battery_interface.getBatteryCurrent()
                except Exception as e:
                    data["current_error"] = str(e)

                try:
                    data["charge"] = self.battery_interface.getBatteryCharge()
                except Exception as e:
                    data["charge_error"] = str(e)

                try:
                    data["temperature"] = self.battery_interface.getBatteryTemperature()
                except Exception as e:
                    data["temperature_error"] = str(e)

                try:
                    status = self.battery_interface.getBatteryStatus()
                    status_map = {
                        0: "BATTERY_OK_STANBY",
                        1: "BATTERY_OK_IN_CHARGE",
                        2: "BATTERY_OK_IN_USE",
                        3: "BATTERY_GENERAL_ERROR",
                        4: "BATTERY_TIMEOUT",
                        5: "BATTERY_LOW_WARNING",
                        6: "BATTERY_CRITICAL_WARNING"
                    }
                    data["status"] = status_map.get(status, f"UNKNOWN_STATUS_{status}")
                    data["status_code"] = status
                except Exception as e:
                    data["status_error"] = str(e)

                try:
                    data["info"] = self.battery_interface.getBatteryInfo()
                except Exception as e:
                    data["info_error"] = str(e)

                return data

            except Exception as e:
                logger.error(f"Error getting battery data: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get battery data: {str(e)}"
                }

        @self.mcp.tool()
        async def get_connection_status() -> dict[str, Any]:
            """Get the current status of the YARP battery connection, including initialization state and device status."""
            if self.battery_interface is None:
                return {
                    "initialized": False,
                    "error": "System not initialized"
                }

            try:
                status = {
                    "initialized": True,
                    "device_valid": self.device_driver.isValid() if self.device_driver else False,
                    "interface_available": self.battery_interface is not None,
                    "network_connected": self.yarp_network.checkNetwork() if self.yarp_network else False
                }

                return status

            except Exception as e:
                return {
                    "initialized": True,
                    "error": f"Status check failed: {str(e)}"
                }

        @self.mcp.tool()
        async def cleanup_yarp_battery() -> dict[str, Any]:
            """Shutdown the YARP battery monitoring and free all system resources. Use this when you want to clean up the battery system."""
            try:
                cleanup_status = []

                with self.notification_lock:
                    monitor_tasks = list(self.battery_monitor_tasks.values())
                    self.battery_monitor_tasks.clear()
                for task in monitor_tasks:
                    task.cancel()
                if monitor_tasks:
                    cleanup_status.append(f"Cancelled {len(monitor_tasks)} battery monitor task(s)")

                if self.device_driver:
                    self.device_driver.close()
                    cleanup_status.append("Device driver closed")
                    self.device_driver = None

                self.battery_interface = None

                if self.yarp_network:
                    yarp.Network.fini()
                    cleanup_status.append("YARP network finalized")
                    self.yarp_network = None

                self.battery_interface = False

                return {
                    "success": True,
                    "cleanup_actions": cleanup_status
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Cleanup failed: {str(e)}"
                }

        # Start YARP RPC info port in a background thread
        self._start_info_port()

    def _build_system_prompt_addendum(self) -> str:
        """Build prompt guidance for clients that consume server instructions."""
        return """
BATTERY SERVER INSTRUCTIONS:

When the user asks to be notified when battery charge goes below or above a
threshold, prefer the server-side MCP notification tool:
  - start_battery_charge_monitor(threshold, direction, poll_interval, timeout)

Examples:
  - "Tell me when battery is below 20%" -> start_battery_charge_monitor(20, "below")
  - "Tell me when battery is above 80%" -> start_battery_charge_monitor(80, "above")

The monitor sends notifications/tasks/status MCP notifications when the threshold
condition is reached. Use get_battery_charge() for one-shot battery reads.
"""

    def _start_info_port(self):
        """Start YARP RPC port for tool information"""
        try:
            # Initialize YARP network if not already done
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Create and open the RPC port
            self.info_port = yarp.RpcServer()
            port_name = "/mcp_server/battery/info:o"

            if not self.info_port.open(port_name):
                logger.warning(f"Failed to open info port {port_name}")
                self.info_port = None
                return

            logger.info(f"Opened YARP info port at {port_name}")
            self.info_port_running = True

            # Start listening for RPC commands in a background thread
            def rpc_loop():
                while self.info_port_running:
                    try:
                        cmd = yarp.Bottle()
                        reply = yarp.Bottle()

                        if self.info_port.read(cmd, True):
                            cmd_str = cmd.toString()
                            print(f"Received RPC command: {cmd_str}")
                            if "get_name" in cmd_str:
                                # Return the server name
                                reply.addString(self.server_name)
                                self.info_port.reply(reply)
                            elif "get_mcp_url" in cmd_str:
                                # Return the MCP server URL
                                reply.addString(self.mcp_url)
                                self.info_port.reply(reply)
                            elif "get_system_prompt_addendum" in cmd_str:
                                # Return the system prompt addendum
                                reply.addString(self.system_prompt_addendum)
                                self.info_port.reply(reply)
                    except Exception as e:
                        logger.debug(f"RPC port error: {e}")

                    # Small sleep to prevent busy waiting
                    time.sleep(0.01)

            # Start the background thread as a daemon
            rpc_thread = threading.Thread(target=rpc_loop, daemon=True)
            rpc_thread.start()

        except Exception as e:
            logger.error(f"Error starting info port: {e}")

    def __del__(self):
        """Destructor to ensure cleanup"""
        self.info_port_running = False
        with self.notification_lock:
            monitor_tasks = list(self.battery_monitor_tasks.values())
            self.battery_monitor_tasks.clear()
        for task in monitor_tasks:
            task.cancel()

        if self.info_port:
            try:
                self.info_port.close()
            except:
                pass

        if self.battery_interface:
            try:
                if self.device_driver:
                    self.device_driver.close()
                if self.yarp_network:
                    yarp.Network.fini()
            except:
                pass

    def run(self, host: str = None, port: int = None):
        """
        Run the MCP server using FastMCP's built-in server.
        """

        # Create PolyDriver for battery
        options = yarp.Property()
        options.put("device",  self.device_name)
        options.put("remote", self.remote_port)
        options.put("local", self.local_port)

        self.device_driver = yarp.PolyDriver(options)

        if not self.device_driver.isValid():
            logger.error(f"Failed to create {self.device_name} device. Check if the device is available.")
            return

        self.battery_interface = self.device_driver.viewIBattery()

        if self.battery_interface is None:
            logger.error(f"Failed to view IBattery interface for {self.device_name}.")
            return

        host_i = host if host else self.base_url
        port_i = port if port else self.mcp_port
        try:
            import uvicorn
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()

            # Run the app directly without mounting
            logger.info(f"Starting YARP Battery MCP Server on {host_i}:{port_i}")
            uvicorn.run(asgi_app, host=host_i, port=port_i)
        except Exception as e:
            logger.exception("Failed to run MCP server: %s", e)
            raise

if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_IBattery(config)
    server.run()
