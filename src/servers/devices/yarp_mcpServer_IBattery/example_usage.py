#!/usr/bin/env python3
"""
Example script showing how to use the YARP Battery MCP Server
"""

import asyncio
import json
from servers.yarp_mcpServer_IBattery.Yarp_mcpServer_IBattery import Yarp_mcpServer_IBattery

async def example_usage():
    """Example of using the YARP Battery MCP Server"""

    # Create server instance
    server = Yarp_mcpServer_IBattery()

    print("YARP Battery MCP Server Example")
    print("=" * 50)

    # Initialize YARP
    print("\n1. Initializing YARP...")
    init_response = await server.mcp.call_tool("initialize_yarp", {})
    init_result = init_response[1] if len(init_response) > 1 else {}
    print(f"Initialization result: {json.dumps(init_result, indent=2)}")

    if not init_result.get("success", False):
        print("Failed to initialize YARP. Make sure yarpserver is running and battery device is available.")
        return

    # Get connection status
    print("\n2. Getting connection status...")
    status_response = await server.mcp.call_tool("get_connection_status", {})
    status_result = status_response[1] if len(status_response) > 1 else {}
    print(f"Connection status: {json.dumps(status_result, indent=2)}")

    # Get battery voltage
    print("\n3. Getting battery voltage...")
    voltage_response = await server.mcp.call_tool("get_battery_voltage", {})
    voltage_result = voltage_response[1] if len(voltage_response) > 1 else {}
    print(f"Voltage: {json.dumps(voltage_result, indent=2)}")

    # Get battery current
    print("\n4. Getting battery current...")
    current_response = await server.mcp.call_tool("get_battery_current", {})
    current_result = current_response[1] if len(current_response) > 1 else {}
    print(f"Current: {json.dumps(current_result, indent=2)}")

    # Get battery charge
    print("\n5. Getting battery charge level...")
    charge_response = await server.mcp.call_tool("get_battery_charge", {})
    charge_result = charge_response[1] if len(charge_response) > 1 else {}
    print(f"Charge: {json.dumps(charge_result, indent=2)}")

    # Get battery temperature
    print("\n6. Getting battery temperature...")
    temp_response = await server.mcp.call_tool("get_battery_temperature", {})
    temp_result = temp_response[1] if len(temp_response) > 1 else {}
    print(f"Temperature: {json.dumps(temp_result, indent=2)}")

    # Get battery status
    print("\n7. Getting battery status...")
    status_response = await server.mcp.call_tool("get_battery_status", {})
    status_result = status_response[1] if len(status_response) > 1 else {}
    print(f"Battery status: {json.dumps(status_result, indent=2)}")

    # Get battery info
    print("\n8. Getting battery info...")
    info_response = await server.mcp.call_tool("get_battery_info", {})
    info_result = info_response[1] if len(info_response) > 1 else {}
    print(f"Battery info: {json.dumps(info_result, indent=2)}")

    # Get all battery data at once
    print("\n9. Getting all battery data...")
    all_data_response = await server.mcp.call_tool("get_all_battery_data", {})
    all_data_result = all_data_response[1] if len(all_data_response) > 1 else {}
    print(f"All battery data: {json.dumps(all_data_result, indent=2)}")

    # Cleanup
    print("\n10. Cleaning up...")
    cleanup_response = await server.mcp.call_tool("cleanup_yarp", {})
    cleanup_result = cleanup_response[1] if len(cleanup_response) > 1 else {}
    print(f"Cleanup result: {json.dumps(cleanup_result, indent=2)}")

    print("\nExample completed!")

if __name__ == "__main__":
    asyncio.run(example_usage())