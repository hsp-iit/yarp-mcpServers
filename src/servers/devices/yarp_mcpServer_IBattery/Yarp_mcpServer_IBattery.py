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
import threading
import time
import argparse

# MCP imports
from mcp.server.fastmcp import FastMCP
from mcp.server.models import InitializationOptions
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
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

class Yarp_mcpServer_IBattery:
    """YARP Battery MCP Server"""

    def __init__(self, conf=None):
        self.mcp = FastMCP("YARP Battery Server")
        self.yarp_network = None
        self.device_driver = None
        self.battery_interface = None
        self.info_port = None
        self.info_port_running = False
        self.server_name = "battery"
        self.base_url = "127.0.0.1"
        self.mcp_port = "4001"
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
            if conf.check("mcp_host"):
                self.base_url = conf.find("mcp_host").asString()
            if conf.check("mcp_port"):
                self.mcp_port = conf.find("mcp_port").asInt()
        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"

        # Register tools
        self._register_tools()

    def _register_tools(self):
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
            """Get the battery charge level (state of charge) as a percentage (0-100%)."""
            if self.battery_interface is None:
                return {
                    "success": False,
                    "error": "YARP battery not initialized. Call initialize_yarp first."
                }

            try:
                charge = self.battery_interface.getBatteryCharge()

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
                                reply.addString("NOT_IMPLEMENTED")
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

    def run(self, host: str = "127.0.0.1", port: int = 4001):
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

        try:
            import uvicorn
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()

            # Run the app directly without mounting
            uvicorn.run(asgi_app, host=host, port=port)
        except Exception as e:
            logger.exception("Failed to run MCP server: %s", e)
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YARP Battery MCP Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=4001, help="Server port (default: 4001)")
    parser.add_argument("--yarp_remote", type=str, default="/battery_nws", help="YARP remote port (default: /battery_nws)")
    parser.add_argument("--yarp_local", type=str, default="/mcp_battery/client", help="YARP local port (default: /mcp_battery/client)")
    args = parser.parse_args()

    server = YarpBatteryMCP(args)
    server.run(host=args.host, port=args.port)
