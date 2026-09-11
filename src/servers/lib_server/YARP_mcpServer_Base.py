"""
Base class for YARP_mcpServer. This class is used to create a server that can communicate with YARP clients.
"""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
import json
import threading
import time
import argparse
import sys
import uvicorn
from typing import Any, Sequence

# MCP imports
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)

class MissingParameterError(Exception):
    """Custom exception for missing parameters in the configuration."""
    def __init__(self, parameter_name: str):
        super().__init__(f"Missing required parameter: {parameter_name}")
        self.parameter_name = parameter_name



class McpServerRpcReader(yarp.PortReader):
    def __init__(self, mcp_server):
        yarp.PortReader.__init__(self)
        self.mcp_server = mcp_server
        self.log_component = yarp.LogComponent(self.__class__.__name__)
        self.log = yarp.Log(__file__, 0, self.__class__.__name__, None, self.log_component)

    def read(self, connection):
        command = yarp.Bottle()
        if not command.read(connection):
            return False

        self.log.info(f"Received command: {command.toString()}")

        reply = yarp.Bottle()
        reply.fromString(self.mcp_server.handle_command(command.toString()))

        writer = connection.getWriter()
        if writer is not None:
            reply.write(writer)

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
        self._uvicorn_server = None
        if not hasattr(self, "log"):
            self.log_component = yarp.LogComponent(self.__class__.__name__)
            self.log = yarp.Log(__file__, 0, self.__class__.__name__, None, self.log_component)

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
        @asynccontextmanager
        async def server_lifespan(_server):
            start_maintenance = getattr(self, "_start_operation_maintenance", None)
            if start_maintenance is not None:
                await start_maintenance()
            try:
                yield None
            finally:
                await self.cleanup()

        self.subscription_bus = InMemorySubscriptionBus()
        self.mcp = MCPServer(
            name=f"YARP {self.server_name} Server",
            version="0.2.0",
            subscriptions=self.subscription_bus,
            lifespan=server_lifespan,
        )

        self._register_common_tools()
        self._register_internal_tools()

    @abstractmethod
    def _register_internal_tools(self):
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

            self.log.info(f"Opened YARP info port at {port_name}")
            self.info_port_running = True
            self.rpcHandler = McpServerRpcReader(self)
            self.info_port.setReader(self.rpcHandler)
            if not self.info_port.open(port_name):
                self.log.warning(f"Failed to open info port {port_name}")
                self.info_port = None
                return

        except Exception as e:
            self.log.error(f"Error starting info port: {e}")

    @abstractmethod
    def _register_common_tools(self):
        """Register common MCP tools and resources."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Stop ongoing work and release all resources owned by the server."""
        ...

    def _cleanup_base_resources(self) -> None:
        """Release resources shared by all server implementations."""
        self.info_port_running = False
        self._close_resource("info_port", "info port")
        self._close_resource("rpcHandler", "RPC handler")

        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True

    def _close_resource(self, attribute: str, description: str) -> None:
        """Close one optional YARP resource and clear its attribute."""
        resource = getattr(self, attribute, None)
        if resource:
            try:
                resource.close()
            except Exception as exc:
                self.log.warning(f"Error closing {description}: {exc}")
            finally:
                setattr(self, attribute, None)

    def _finalize_yarp_network(self) -> None:
        """Finalize this server's YARP network handle if it was initialized."""
        if self.yarp_network:
            try:
                yarp.Network.fini()
            except Exception as exc:
                self.log.warning(f"Error finalizing YARP network: {exc}")
            finally:
                self.yarp_network = None

    @abstractmethod
    def _initialize(self) -> bool:
        """Initialize mcp server and YARP network"""
        # Check if YARP server is running
        self.yarp_network = yarp.Network()
        if not self.yarp_network.checkNetwork():
            self.log.error("YARP network not available. Please start yarpserver.")
            return False
        return True

    def run(self, host: str = None, port: int = None):
        """
        Run the MCP server using uvicorn.
        """

        self.is_initialized = self._initialize()
        if not self.is_initialized:
            self.log.error("Failed to initialize the server. Exiting.")
            return

        host_i = host if host else self.base_url
        port_i = port if port else self.mcp_port
        try:
            self.log.info(f"Starting YARP {self.server_name} MCP Server on {host_i}:{port_i}")
            # Get the ASGI app from MCPServer. Its lifespan owns transport work.
            asgi_app = self.mcp.streamable_http_app()
            # Keep the server object so cleanup() can request a graceful stop.
            config = uvicorn.Config(asgi_app, host=host_i, port=port_i)
            self._uvicorn_server = uvicorn.Server(config)
            self._uvicorn_server.run()
        except Exception as e:
            self.log.error(f"Server error: {e}")
        finally:
            self._uvicorn_server = None
