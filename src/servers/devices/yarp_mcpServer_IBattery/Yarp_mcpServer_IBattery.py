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


from ...lib_server.YARP_mcpServer_DeviceBase import *
from ...lib_server.operation_models import OperationErrorResult, StartOperationResult

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)


# Configure logging
logging.basicConfig(level=logging.INFO)
globLogger = logging.getLogger(__name__)

class Yarp_mcpServer_IBattery(Yarp_mcpServer_DeviceBase):
    """YARP Battery MCP Server"""

    def __init__(self, conf=None, logger: logging.Logger = globLogger, enableExplicitLogging: bool = True):
        self.battery_interface = None
        server_name = "yarp_mcpServer_IBattery"
        device_name = "battery_nwc_yarp"
        remote_port = "/battery_nws_yarp"
        local_port = "/battery_nwc_yarp"

        if conf:
            if not conf.check("device"):
                conf.setDefault("device", device_name)
            if not conf.check("remote"):
                conf.setDefault("remote", remote_port)
            if not conf.check("local"):
                conf.setDefault("local", local_port)
            if not conf.check("server_name"):
                conf.setDefault("server_name", server_name)

        Yarp_mcpServer_DeviceBase.__init__(self, conf, logger, enableExplicitLogging)


    async def _battery_charge_monitor_loop(
        self,
        operation_id: str,
        threshold: float,
        direction: str,
        poll_interval: float,
        timeout: float,
    ) -> None:
        """Poll battery charge and update its authoritative operation resource."""
        start_time = time.monotonic()
        comparison = "<" if direction == "below" else ">"

        try:
            await self.operation_registry.update(
                operation_id,
                status="working",
                details={
                    "threshold": threshold,
                    "direction": direction,
                    "condition": f"charge {comparison} {threshold}",
                },
                status_message=f"Monitoring battery charge until it is {direction} {threshold}%",
            )
            await asyncio.sleep(poll_interval)

            while True:
                if self.battery_interface is None:
                    await self.operation_registry.update(
                        operation_id,
                        status="failed",
                        error={"message": "YARP battery not initialized"},
                        details={
                            "threshold": threshold,
                            "direction": direction,
                        },
                        status_message="Battery monitor failed: interface not initialized",
                    )
                    return

                charge = await self._call_yarp(self.battery_interface.getBatteryCharge)
                crossed = charge < threshold if direction == "below" else charge > threshold
                data = {
                    "charge": charge,
                    "unit": "percent",
                    "threshold": threshold,
                    "direction": direction,
                    "condition": f"charge {comparison} {threshold}",
                }

                if crossed:
                    await self.operation_registry.update(
                        operation_id,
                        status="completed",
                        details=data,
                        result=data,
                        status_message=f"Battery charge is {charge:.1f}%, {direction} threshold {threshold:.1f}%",
                    )
                    return

                if timeout > 0 and time.monotonic() - start_time >= timeout:
                    await self.operation_registry.update(
                        operation_id,
                        status="failed",
                        details=data,
                        error={"message": "timeout", "timeout_seconds": timeout},
                        status_message=f"Battery monitor timed out after {timeout:.1f}s",
                    )
                    return

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            await self.operation_registry.update(
                operation_id,
                status="cancelled",
                details={"threshold": threshold, "direction": direction},
                status_message="Battery charge monitor cancelled",
            )
            raise
        except Exception as e:
            self.fancyLog.ERROR(f"Battery charge monitor {operation_id} failed: {e}")
            await self.operation_registry.update(
                operation_id,
                status="failed",
                details={"threshold": threshold, "direction": direction},
                error={"message": str(e)},
                status_message=f"Battery monitor failed: {e}",
            )

    def _register_internal_tools(self):
        """Register MCP tools"""

        @self.mcp.tool()
        async def get_battery_voltage() -> dict[str, Any]:
            """Get the instantaneous battery voltage measurement in volts."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                voltage = await self._call_yarp(self.battery_interface.getBatteryVoltage)

                return {
                    "success": True,
                    "voltage": voltage,
                    "unit": "volts"
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery voltage: {e}")
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
                current = await self._call_yarp(self.battery_interface.getBatteryCurrent)

                return {
                    "success": True,
                    "current": current,
                    "unit": "amperes"
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery current: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get current: {str(e)}"
                }

        @self.mcp.tool()
        async def get_battery_charge() -> dict[str, Any]:
            """
            Get the battery charge level (state of charge) as a percentage (0-100%).
            """
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                charge = await self._call_yarp(self.battery_interface.getBatteryCharge)

                return {
                    "success": True,
                    "charge": charge,
                    "unit": "percent"
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery charge: {e}")
                return {
                    "success": False,
                    "error": f"Failed to get charge: {str(e)}"
                }

        @self.mcp.tool(structured_output=True)
        async def start_battery_charge_monitor(
            threshold: float,
            direction: str = "below",
            poll_interval: float = 1.0,
            timeout: float = 0.0,
        ) -> StartOperationResult | OperationErrorResult:

            if self.battery_interface is None:
                return OperationErrorResult(
                    error="YARP battery not initialized. Call initialize_yarp first."
                )

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
                return OperationErrorResult(error="direction must be 'below' or 'above'")

            if poll_interval <= 0:
                return OperationErrorResult(error="poll_interval must be positive")

            if timeout < 0:
                return OperationErrorResult(error="timeout cannot be negative")

            comparison = "<" if direction_normalized == "below" else ">"
            operation = await self.operation_registry.create(
                "battery_charge_monitor",
                status_message=f"Monitoring battery charge until it is {direction_normalized} {threshold}%",
                details={
                    "threshold": threshold,
                    "direction": direction_normalized,
                    "condition": f"charge {comparison} {threshold}",
                },
                poll_interval_ms=max(1, round(poll_interval * 1000)),
            )
            await self._start_operation_task(
                operation,
                self._battery_charge_monitor_loop(
                    operation_id=operation.operation_id,
                    threshold=threshold,
                    direction=direction_normalized,
                    poll_interval=poll_interval,
                    timeout=timeout,
                ),
            )
            return StartOperationResult(
                operation_id=operation.operation_id,
                operation_type=operation.operation_type,
                status_uri=operation.status_uri,
                poll_interval_ms=operation.poll_interval_ms,
                message=f"Started server-side battery monitor {operation.operation_id}",
            )

        @self.mcp.tool()
        async def stop_battery_charge_monitor(operation_id: str) -> dict[str, Any]:
            """Cancel a server-side battery charge monitor."""
            try:
                snapshot = await self.operation_registry.cancel(operation_id)
            except Exception:
                return {
                    "success": False,
                    "error": f"Battery monitor {operation_id} not found"
                }
            return {
                "success": True,
                "operation_id": operation_id,
                "status": snapshot.status,
                "message": f"Battery monitor {operation_id} cancellation requested"
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
                temperature = await self._call_yarp(self.battery_interface.getBatteryTemperature)

                return {
                    "success": True,
                    "temperature": temperature,
                    "unit": "celsius"
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery temperature: {e}")
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
                status = await self._call_yarp(self.battery_interface.getBatteryStatus)

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

                return {
                    "success": True,
                    "status": status_str,
                    "status_code": status
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery status: {e}")
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
                info = await self._call_yarp(self.battery_interface.getBatteryInfo)

                return {
                    "success": True,
                    "info": info
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery info: {e}")
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
                    data["voltage"] = await self._call_yarp(
                        self.battery_interface.getBatteryVoltage
                    )
                except Exception as e:
                    data["voltage_error"] = str(e)

                try:
                    data["current"] = await self._call_yarp(
                        self.battery_interface.getBatteryCurrent
                    )
                except Exception as e:
                    data["current_error"] = str(e)

                try:
                    data["charge"] = await self._call_yarp(
                        self.battery_interface.getBatteryCharge
                    )
                except Exception as e:
                    data["charge_error"] = str(e)

                try:
                    data["temperature"] = await self._call_yarp(
                        self.battery_interface.getBatteryTemperature
                    )
                except Exception as e:
                    data["temperature_error"] = str(e)

                try:
                    status = await self._call_yarp(self.battery_interface.getBatteryStatus)
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
                    data["info"] = await self._call_yarp(self.battery_interface.getBatteryInfo)
                except Exception as e:
                    data["info_error"] = str(e)

                return data

            except Exception as e:
                self.fancyLog.ERROR(f"Error getting battery data: {e}")
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

        # Start YARP RPC info port in a background thread
        self._start_info_port()

    def _build_system_prompt_addendum(self) -> str:
        """Build prompt guidance for clients that consume server instructions."""
        return """
BATTERY SERVER INSTRUCTIONS:

When the user asks to be notified when battery charge goes below or above a
threshold, prefer the server-side operation tool:
  - start_battery_charge_monitor(threshold, direction, poll_interval, timeout)

Examples:
  - "Tell me when battery is below 20%" -> start_battery_charge_monitor(20, "below")
  - "Tell me when battery is above 80%" -> start_battery_charge_monitor(80, "above")

The tool returns an operation_id and status_uri. The client can subscribe to the
operation resource and refetch it when notified. Use get_battery_charge() for a
one-shot battery read.
""".lstrip("\n")

    async def cleanup(self) -> None:
        """Stop battery monitoring and release the YARP resources."""
        self.fancyLog.INFO("Cleaning up YARP battery resources...")
        try:
            await self._cleanup_operations()
        finally:
            self._close_resource("device_driver", "battery device driver")
            self.battery_interface = None
            self._finalize_yarp_network()
            self.is_initialized = False
            self._cleanup_base_resources()
        self.fancyLog.INFO("YARP battery resources cleaned up successfully.")

    def _interfaceView(self, devDriver):
        self.battery_interface = devDriver.viewIBattery()

        if self.battery_interface is None:
            self.fancyLog.ERROR(f"Failed to view IBattery interface for {self.device_name}.")
            return False

        return True

if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_IBattery(config)
    server.run()
