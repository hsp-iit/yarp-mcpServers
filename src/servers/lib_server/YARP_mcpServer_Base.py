"""
Base class for YARP_mcpServer. This class is used to create a server that can communicate with YARP clients.
"""

from abc import ABC, abstractmethod
import asyncio
import logging
import json
import threading
import time
import argparse
import sys
import uvicorn
from typing import Any, Sequence

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


class MissingParameterError(Exception):
    """Custom exception for missing parameters in the configuration."""
    def __init__(self, parameter_name: str):
        super().__init__(f"Missing required parameter: {parameter_name}")
        self.parameter_name = parameter_name



class McpServer_rpcHandler(yarp.RFModule):
    """YARP RPC handler for MCP server"""

    def __init__(self, mcp_server):
        yarp.RFModule.__init__(self)
        self.mcp_server = mcp_server

    def respond(self, command: yarp.Bottle, reply: yarp.Bottle) -> bool:
        """Handle incoming YARP RPC commands"""
        cmd_str = command.toString()
        logger.info(f"Received command: {cmd_str}")

        # Process the command and generate a response
        response = self.mcp_server.handle_command(cmd_str)
        reply.fromString(response)
        return True

class Yarp_mcpServer_Base(ABC):
    """Abstract Base class for Yarp_mcpServer"""

    @abstractmethod
    def __init__(self, conf:yarp.ResourceFinder=None):
        self.yarp_network = None
        self.is_initialized = False
        self.tool_descriptions = {}
        self.info_port = None
        self.info_port_running = False
        self.base_url = "127.0.0.1"
        self.mcp_port = None
        self.server_name = None
        self.rpcHandler = None

        if conf:
            # YARP Property object
            if conf.check("mcp_host"):
                self.base_url = conf.find("mcp_host").asString()
            if conf.check("mcp_port"):
                self.mcp_port = conf.find("mcp_port").asInt16()
            else:
                raise MissingParameterError("mcp_port")
            if conf.check("server_name"):
                self.server_name = conf.find("server_name").asString()
            else:
                raise MissingParameterError("server_name")
        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"
        self.mcp = FastMCP(f"YARP {self.server_name} Server")

    @abstractmethod
    def _register_tools(self):
        """Register MCP tools"""
        ...

    @abstractmethod
    def _build_system_prompt_addendum(self) -> str:
        """Build system prompt addendum for the client to modify LLM behavior"""
        ...

    def handle_command(self, cmd_str: str) -> str:
        """Handle incoming YARP RPC commands and return a response"""
        if "get_name" in cmd_str:
            return self.server_name
        elif "get_mcp_url" in cmd_str:
            return self.mcp_url
        elif "get_system_prompt_addendum" in cmd_str:
            return self._build_system_prompt_addendum()
        else:
            return "Unknown command"

    def _start_info_port(self):
        """Start YARP RPC port for tool information"""
        try:
            # Initialize YARP network if not already done
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Create and open the RPC port
            self.info_port = yarp.RpcServer()
            port_name = f"/mcp_server/{self.server_name}/info:o"

            if not self.info_port.open(port_name):
                logger.warning(f"Failed to open info port {port_name}")
                self.info_port = None
                return

            logger.info(f"Opened YARP info port at {port_name}")
            self.info_port_running = True
            self.rpcHandler = McpServer_rpcHandler(self)
            self.rpcHandler.attach(self.info_port)

        except Exception as e:
            logger.error(f"Error starting info port: {e}")

    @abstractmethod
    def __del__(self):
        """Destructor to clean up resources"""
        if self.info_port:
            try:
                self.info_port.close()
            except:
                pass

    @abstractmethod
    def _initialize(self):
        """Initialize mcp server and YARP network"""
        ...

    def run(self, host: str = None, port: int = None):
        """
        Run the MCP server using uvicorn.
        """

        self._initialize()

        host_i = host if host else self.base_url
        port_i = port if port else self.mcp_port
        try:
            logger.info(f"Starting YARP {self.server_name} MCP Server on {host_i}:{port_i}")
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()
            # Run the app with uvicorn
            uvicorn.run(asgi_app, host=host_i, port=port_i)
        except Exception as e:
            logger.error(f"Server error: {e}")
            sys.exit(1)