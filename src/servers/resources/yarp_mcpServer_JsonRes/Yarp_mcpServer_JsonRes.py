import json
import os
import sys
import logging
from typing import Dict, Any
import threading
import time
import yarp
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import Resource, TextContent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class Yarp_mcpServer_JsonRes:
    def __init__(self, config: yarp.ResourceFinder = None):
        self.mcp = FastMCP("JSON Data Server")
        self.yarp_network = None
        self.info_port = None
        self.info_port_running = False
        self.server_name = "json_data"
        self.base_url = "127.0.0.1"
        self.mcp_port = 4003
        self.json_file_path = None
        self.data: Dict[str, Any] = {}

        json_file_name = "tours-with-italian-dates-in-chars.json"
        json_file_context = "test_servers"

        if config:
            if config.check("json_file"):
                json_file_name = config.find("json_file").asString()
            if config.check("json_context"):
                json_file_context = config.find("json_context").asString()
            if config.check("mcp_host"):
                self.base_url = config.find("mcp_host").asString()
            if config.check("mcp_port"):
                self.mcp_port = config.find("mcp_port").asInt16()

        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"

        # Construct the full path to the JSON file
        jsonFinder = yarp.ResourceFinder()
        jsonFinder.setDefaultContext(json_file_context)
        self.json_file_path = jsonFinder.findFileByName(json_file_name)

        # Initialize the JSON data
        if self.json_file_path:
            self.load_json_data()

        # Build system prompt addendum
        self.system_prompt_addendum = self._build_system_prompt_addendum()

        # Register resources and tools
        self._register_resources()
        self._register_tools()

        # Start YARP RPC info port in a background thread
        self._start_info_port()

    def load_json_data(self) -> None:
        """Load JSON data from file"""
        try:
            if not os.path.exists(self.json_file_path):
                raise FileNotFoundError(f"JSON file not found at {self.json_file_path}")

            with open(self.json_file_path, 'r') as f:
                self.data = json.load(f)
            logger.info(f"Successfully loaded JSON data from {self.json_file_path}")
        except Exception as e:
            logger.error(f"Error loading JSON file: {e}")
            raise

    def _build_system_prompt_addendum(self) -> str:
        """Build system prompt addendum for the client to modify LLM behavior"""
        return """
═════════════════════════════════════════════════════════════════════════════════
JSON DATA RESOURCE SERVER:
═════════════════════════════════════════════════════════════════════════════════

You have access to a JSON data resource that you can query using the following tools:

AVAILABLE QUERY TOOLS:
1. search_json_keys(search_term) - Find keys in the JSON that match a search term
   Use this to discover what data is available in the JSON structure.
   Example: search_json_keys("room") to find all keys containing "room"

2. list_json_structure() - Show the top-level structure and available keys
   Use this to understand how the JSON is organized.

3. get_json_by_path(json_path) - Retrieve a specific value using dot notation
   Use this to access data at a specific path (e.g., "key1.key2.key3").
   For array indices, use [n] notation (e.g., "data[0].name").

4. search_json_values(search_term) - Search for values within the JSON
   Use this to find information when you don't know the exact path.
   Example: search_json_values("specific content") to find all mentions

WORKFLOW:
1. When user asks for information, first use search_json_keys() to find relevant data
2. Use list_json_structure() if you need to understand the organization
3. Use get_json_by_path() to retrieve specific data once you know the path
4. Use search_json_values() to find content by text when path is unknown

RESOURCE ACCESS:
The complete JSON data is available as a read-only resource: json://data
═════════════════════════════════════════════════════════════════════════════════"""

    def _register_resources(self):
        """Register MCP resources for the JSON data

        Resources expose the JSON file as passive, read-only data that applications
        can retrieve and use for context. Unlike tools, resources are not operations
        but rather data sources available to the application.
        """

        @self.mcp.resource("json://data")
        def get_json_data_resource() -> str:
            """Get the complete JSON data file as a resource.

            This resource exposes the entire JSON file contents as read-only data
            that applications can retrieve and use for context.

            URI: json://data
            MIME Type: application/json
            """
            if not self.data:
                return json.dumps({"error": "No JSON data loaded"})
            return json.dumps(self.data, indent=2)

        # Register additional resource for the specific file
        if self.json_file_path:
            filename = os.path.basename(self.json_file_path)
            resource_uri = f"json://file/{filename}"

            @self.mcp.resource(resource_uri)
            def get_json_file_resource() -> str:
                """Get the JSON file resource.

                This resource exposes the loaded JSON file as read-only data.

                MIME Type: application/json
                """
                if not self.data:
                    return json.dumps({"error": "No JSON data loaded"})
                return json.dumps(self.data, indent=2)

    def _register_tools(self):
        """Register MCP tools for operations on JSON data

        Unlike resources (which are passive data sources), tools represent
        actions that can be performed. In this case, we provide tools for
        querying, searching, navigating and reloading the JSON data.
        """

        @self.mcp.tool()
        async def search_json_keys(search_term: str) -> dict[str, Any]:
            """Search for keys in the JSON data that match a search term.

            This tool helps you find relevant sections in the JSON by searching for keys.
            Useful for discovering what information is available.

            Example: search_json_keys("sala") finds keys containing "sala"
            """
            if not self.data:
                return {
                    "success": False,
                    "error": "No JSON data loaded"
                }

            try:
                search_term_lower = search_term.lower()
                matching_keys = []

                def search_keys_recursive(obj, path=""):
                    """Recursively search for matching keys"""
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            full_path = f"{path}.{key}" if path else key
                            if search_term_lower in key.lower():
                                matching_keys.append({
                                    "key": key,
                                    "path": full_path,
                                    "type": type(value).__name__
                                })
                            search_keys_recursive(value, full_path)
                    elif isinstance(obj, list) and obj:
                        for i, item in enumerate(obj[:3]):  # Limit recursion
                            search_keys_recursive(item, f"{path}[{i}]")

                search_keys_recursive(self.data)

                return {
                    "success": True,
                    "search_term": search_term,
                    "matches_count": len(matching_keys),
                    "matches": matching_keys[:20]  # Return top 20 matches
                }
            except Exception as e:
                logger.error(f"Error searching JSON keys: {e}")
                return {
                    "success": False,
                    "error": f"Search error: {str(e)}"
                }


        @self.mcp.tool()
        async def list_json_structure() -> dict[str, Any]:
            """List the top-level structure of the JSON data.

            Shows what keys are available at the root level and their types.
            Useful for understanding the data organization.
            """
            if not self.data:
                return {
                    "success": False,
                    "error": "No JSON data loaded"
                }

            try:
                structure = {}
                for key, value in self.data.items():
                    value_type = type(value).__name__
                    if isinstance(value, dict):
                        structure[key] = {
                            "type": value_type,
                            "nested_keys": list(value.keys())[:10]
                        }
                    elif isinstance(value, list):
                        structure[key] = {
                            "type": value_type,
                            "length": len(value),
                            "item_type": type(value[0]).__name__ if value else "unknown"
                        }
                    else:
                        structure[key] = {
                            "type": value_type,
                            "value_preview": str(value)[:100]
                        }

                return {
                    "success": True,
                    "structure": structure
                }
            except Exception as e:
                logger.error(f"Error listing JSON structure: {e}")
                return {
                    "success": False,
                    "error": f"Structure error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_json_by_path(json_path: str) -> dict[str, Any]:
            """Retrieve a value from the JSON data using a dot-notation path.

            Navigates the JSON structure using dot notation (e.g., "key1.key2.key3").
            For array indices, use [n] notation (e.g., "key1[0].key2").

            Example: get_json_by_path("TOUR_MADAMA_3.m_availablePoIs.en-US.sala_guidobono")
            """
            if not self.data:
                return {
                    "success": False,
                    "error": "No JSON data loaded"
                }

            try:
                # Parse the path and navigate the structure
                import re
                current = self.data

                # Split path by dots but handle array notation
                parts = re.split(r'\.(?![^\[]*\])', json_path)

                for part in parts:
                    # Check for array index notation
                    match = re.match(r'(\w+)\[(\d+)\]', part)
                    if match:
                        key = match.group(1)
                        index = int(match.group(2))
                        current = current[key][index]
                    else:
                        if part not in current:
                            return {
                                "success": False,
                                "error": f"Path '{json_path}' not found. Key '{part}' does not exist at this level.",
                                "available_keys": list(current.keys()) if isinstance(current, dict) else "Not a dict"
                            }
                        current = current[part]

                # Convert the result to JSON string if it's a large object
                if isinstance(current, (dict, list)):
                    result_str = json.dumps(current, indent=2)
                else:
                    result_str = str(current)

                return {
                    "success": True,
                    "path": json_path,
                    "data_type": type(current).__name__,
                    "value": result_str
                }
            except KeyError as e:
                return {
                    "success": False,
                    "error": f"Key not found in path: {str(e)}"
                }
            except Exception as e:
                logger.error(f"Error retrieving JSON by path: {e}")
                return {
                    "success": False,
                    "error": f"Path error: {str(e)}"
                }

        @self.mcp.tool()
        async def set_json_by_path(json_path: str, new_value: str) -> dict[str, Any]:
            """Modify a value in the JSON data at a specific path.

            This tool allows you to update values in the JSON structure. The new_value will be
            parsed as JSON when possible (numbers, booleans, arrays, objects), otherwise stored as string.

            Example: set_json_by_path("key1.key2", "123") sets a number, not a string.
            Example: set_json_by_path("key1.key2", "hello") sets a string.
            """
            try:
                import re

                # Parse the new value - try JSON parsing first, fall back to string
                try:
                    parsed_value = json.loads(new_value)
                except json.JSONDecodeError:
                    # Not valid JSON, treat as string
                    parsed_value = new_value

                current = self.data
                parts = re.split(r'\.(?![^\[]*\])', json_path)

                # Navigate to the parent of the target element
                for part in parts[:-1]:
                    match = re.match(r'(\w+)\[(\d+)\]', part)
                    if match:
                        key = match.group(1)
                        index = int(match.group(2))
                        if key not in current:
                            return {
                                "success": False,
                                "error": f"Key '{key}' not found in current level."
                            }
                        current = current[key][index]
                    else:
                        if part not in current:
                            return {
                                "success": False,
                                "error": f"Path '{json_path}' not found. Key '{part}' does not exist.",
                                "available_keys": list(current.keys()) if isinstance(current, dict) else "Not a dict"
                            }
                        current = current[part]

                # Set the new value at the target path
                last_part = parts[-1]
                match = re.match(r'(\w+)\[(\d+)\]', last_part)
                if match:
                    key = match.group(1)
                    index = int(match.group(2))
                    if key not in current:
                        return {
                            "success": False,
                            "error": f"Key '{key}' not found in final parent."
                        }
                    current[key][index] = parsed_value
                else:
                    if not isinstance(current, dict):
                        return {
                            "success": False,
                            "error": f"Cannot set key '{last_part}' on non-dict object."
                        }
                    current[last_part] = parsed_value

                return {
                    "success": True,
                    "path": json_path,
                    "new_value": parsed_value,
                    "value_type": type(parsed_value).__name__,
                    "message": "Value updated successfully"
                }
            except Exception as e:
                logger.error(f"Error setting JSON by path: {e}")
                return {
                    "success": False,
                    "error": f"Set path error: {str(e)}"
                }

        @self.mcp.tool()
        async def save_current_json_to_file(file_path: str=None) -> dict[str, Any]:
            """Save the current JSON data to a specified file path.

            This tool allows you to export the current state of the JSON data to a new file.
            Useful for creating modified versions of the data or for backup purposes.
            If no file path is provided, it will attempt to overwrite the original file if it was loaded from one.

            Example: save_current_json_to_file("modified_data.json") saves the current JSON to that file.
            """
            if not self.data:
                return {
                    "success": False,
                    "error": "No JSON data loaded"
                }

            try:
                with open(file_path, 'w') as f:
                    json.dump(self.data, f, indent=2)

                logger.info(f"Successfully saved current JSON data to {file_path}")

                return {
                    "success": True,
                    "file_path": file_path,
                    "message": "Current JSON data saved successfully"
                }
            except Exception as e:
                logger.error(f"Error saving JSON to file: {e}")
                return {
                    "success": False,
                    "error": f"Save error: {str(e)}"
                }


        @self.mcp.tool()
        async def search_json_values(search_term: str, max_results: int = 10) -> dict[str, Any]:
            """Search for values in the JSON data matching a search term.

            Searches within string values in the JSON and returns matching results.
            Useful for finding information when you don't know the exact structure.

            Example: search_json_values("Guidobono") finds all mentions
            """
            if not self.data:
                return {
                    "success": False,
                    "error": "No JSON data loaded"
                }

            try:
                search_term_lower = search_term.lower()
                matches = []

                def search_values_recursive(obj, path=""):
                    """Recursively search for matching values"""
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            full_path = f"{path}.{key}" if path else key
                            search_values_recursive(value, full_path)
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            full_path = f"{path}[{i}]"
                            search_values_recursive(item, full_path)
                    elif isinstance(obj, str):
                        if search_term_lower in obj.lower():
                            matches.append({
                                "path": path,
                                "value": obj[:200]
                            })

                search_values_recursive(self.data)

                return {
                    "success": True,
                    "search_term": search_term,
                    "matches_count": len(matches),
                    "matches": matches[:max_results]
                }
            except Exception as e:
                logger.error(f"Error searching JSON values: {e}")
                return {
                    "success": False,
                    "error": f"Search error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_connection_status() -> dict[str, Any]:
            """Get the current status of the JSON data server.

            Returns information about whether data is loaded, how many keys are available,
            and the available resources that applications can access.
            """
            try:
                available_resources = ["json://data"]
                if self.json_file_path:
                    available_resources.append(f"json://file/{os.path.basename(self.json_file_path)}")

                status = {
                    "initialized": self.data is not None and len(self.data) > 0,
                    "json_file": self.json_file_path,
                    "data_loaded": len(self.data) > 0,
                    "data_keys_count": len(self.data.keys()) if self.data else 0,
                    "available_resources": available_resources
                }

                return {
                    "success": True,
                    "status": status
                }

            except Exception as e:
                logger.error(f"Error checking connection status: {e}")
                return {
                    "success": False,
                    "error": f"Status check failed: {str(e)}"
                }

        @self.mcp.tool()
        async def reload_json_data(file_path: str = None) -> dict[str, Any]:
            """Reload JSON data from file. Optionally specify a new file path."""
            try:
                target_file = file_path if file_path else self.json_file_path

                if not target_file:
                    return {
                        "success": False,
                        "error": "No file path provided and no default path set"
                    }

                if not os.path.exists(target_file):
                    return {
                        "success": False,
                        "error": f"File not found: {target_file}"
                    }

                with open(target_file, 'r') as f:
                    self.data = json.load(f)

                if file_path:
                    self.json_file_path = file_path

                logger.info(f"Successfully reloaded JSON data from {target_file}")

                return {
                    "success": True,
                    "file_path": target_file,
                    "data_keys": list(self.data.keys()),
                    "message": "JSON data reloaded successfully"
                }

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return {
                    "success": False,
                    "error": f"Invalid JSON format: {str(e)}"
                }
            except Exception as e:
                logger.error(f"Error reloading JSON data: {e}")
                return {
                    "success": False,
                    "error": f"Failed to reload data: {str(e)}"
                }

    def _start_info_port(self):
        """Start YARP RPC port for tool information"""
        try:
            # Initialize YARP network if not already done
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Create and open the RPC port
            self.info_port = yarp.RpcServer()
            port_name = "/mcp_server/json/info:o"

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
                            logger.debug(f"Received RPC command: {cmd_str}")
                            if "get_name" in cmd_str:
                                reply.addString(self.server_name)
                                self.info_port.reply(reply)
                            elif "get_mcp_url" in cmd_str:
                                reply.addString(self.mcp_url)
                                self.info_port.reply(reply)
                            elif "get_system_prompt_addendum" in cmd_str:
                                # Return the system prompt addendum
                                reply.addString(self.system_prompt_addendum)
                                self.info_port.reply(reply)
                    except Exception as e:
                        logger.debug(f"RPC port error: {e}")

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

    def run(self, host: str = None, port: int = None):
        """Run the MCP server using FastMCP's built-in server."""
        host_i = host if host else self.base_url
        port_i = port if port else self.mcp_port

        try:
            logger.info(f"Starting JSON MCP Server on {host_i}:{port_i}")
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()

            # Run the app with uvicorn
            uvicorn.run(asgi_app, host=host_i, port=port_i)
        except Exception as e:
            logger.error(f"Server error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_JsonRes(config)
    server.run()