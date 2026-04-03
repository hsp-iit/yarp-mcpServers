#!/usr/bin/env python3
"""
YARP WakeWord rpc mcp server (Streamable HTTP)

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

class Yarp_mcpServer_WakeWordRPC:
    """YARP WakeWord RPC MCP Server"""

    def __init__(self, conf=None):
        self.mcp = FastMCP("YARP WakeWord RPC Server")
        self.yarp_network = None
        self.device_driver = None
        self.speech_interface = None
        self.is_initialized = False
        self.autoconnect = True
        self.tool_descriptions = {}
        self.info_port = None
        self.info_port_running = False
        self.server_name = "wake_word"
        self.base_url = "127.0.0.1"
        self.mcp_port = 4005
        self.local_port_name = "/mcp_ww/rpc:o"
        self.remote_port_name = "/wake/rpc:i"
        self.local_port = None

        if conf:
            # Handle both dict-like and object-like config
            if hasattr(conf, 'check') and hasattr(conf, 'find'):
                # YARP Property object
                if conf.check("yarp_remote"):
                    self.remote_port_name = conf.find("yarp_remote").asString()
                if conf.check("yarp_local"):
                    self.local_port_name = conf.find("yarp_local").asString()
                if conf.check("mcp_host"):
                    self.base_url = conf.find("mcp_host").asString()
                if conf.check("mcp_port"):
                    self.mcp_port = conf.find("mcp_port").asInt16()
                if conf.check("autoconnect"):
                    self.autoconnect = conf.find("autoconnect").asInt8() != 0
            elif isinstance(conf, dict):
                # Dict-like config
                self.remote_port_name = conf.get("yarp_remote", self.remote_port)
                self.local_port_name = conf.get("yarp_local", self.local_port)
                self.base_url = conf.get("mcp_host", self.base_url)
                self.mcp_port = conf.get("mcp_port", self.mcp_port)

        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"
        self.system_prompt_addendum = self._build_system_prompt_addendum()

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register MCP tools"""

        @self.mcp.tool()
        async def stop() -> dict[str, Any]:
            """Asks the wakeword detector to stop passing audio to the next stage (e.g. speech recognition) and wait for the next wakeword trigger to resume passing audio."""
            # ... (kept your implementation unchanged)
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "YARP wake word rpc not initialized. Call initialize_yarp first."
                }

            success = True
            try:
                reply = yarp.Bottle()
                toWakeWord = yarp.Bottle()
                toWakeWord.addString("stop")
                self.local_port.write(toWakeWord, reply)
                if reply is not None and reply.get(0).asString() == "nack":
                    logger.error("DialogueManager::interactWithDialogMng. Orchestrator returned NACK.")
                    success = False

                return {
                    "success": success,
                    "wake_word_status": "stopped" if success else "error"
                }

            except Exception as e:
                logger.error(f"Error during speech synthesis: {e}")
                return {
                    "success": False,
                    "error": f"Speech synthesis error: {str(e)}"
                }


        @self.mcp.tool()
        async def cleanup_yarp_wakeword() -> dict[str, Any]:
            """Shutdown the YARP wake word detector rpc client and free all system resources. Use this when you want to clean up the wake word system."""
            # ... (kept your implementation unchanged)
            try:
                cleanup_status = []

                if self.local_port:
                    self.local_port.close()
                    cleanup_status.append("Local RPC port closed")
                    self.local_port = None

                if self.yarp_network:
                    yarp.Network.fini()
                    cleanup_status.append("YARP network finalized")
                    self.yarp_network = None

                self.is_initialized = False

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
        """Build system prompt addendum for the client to modify LLM behavior"""
        return """
System Prompt Addendum:
- This MCP server provides RPC tools to control a YARP wake word detection system.
- Available tools:
  - stop: Stop passing audio to the next stage until the next wake word trigger.
  - cleanup_yarp_wakeword: Clean up YARP resources used by the wake word system.
- The server listens for RPC commands on the YARP port specified in the configuration (default: /wake_word/rpc:i) and sends commands to the wake word system via the local YARP port (default: /mcp_ww/rpc:o).
- Use the provided tools to control the wake word detection behavior as needed. The stop tool should be called every time the user wants to end the conversation.
  If the intention of the user is to stop talking to you, call the stop tool and do not pass any more user input to the next stage until the next wake word trigger.
  If the intention of the user is to stop talking to you and they will not talk again, call the stop tool.
"""

    def _start_info_port(self):
        """Start YARP RPC port for tool information"""
        try:
            # Initialize YARP network if not already done
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Create and open the RPC port
            self.info_port = yarp.RpcServer()
            port_name = "/mcp_server/wakeword/info:o"

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

                            if "get_description" in cmd_str:
                                # Return all tool descriptions as JSON
                                reply.addString(json.dumps(self.tool_descriptions))
                                self.info_port.reply(reply)
                            elif "get_name" in cmd_str:
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
        if self.info_port:
            try:
                self.info_port.close()
            except:
                pass

        if self.is_initialized:
            try:
                if self.local_port:
                    self.local_port.close()
                if self.yarp_network:
                    yarp.Network.fini()
            except:
                pass

    def run(self, host: str = None, port: int = None):
        """
        Run the MCP server using FastMCP's built-in server.
        """
        # Initialize YARP network
        yarp.Network.init()
        self.yarp_network = yarp.Network()

        # Check if YARP server is running
        if not self.yarp_network.checkNetwork():
            logger.error("YARP network not available. Please start yarpserver.")
            return

        # Create local port for Sound
        self.local_port = yarp.Port()
        if not self.local_port.open(self.local_port_name):
            logger.warning(f"Failed to open local port {self.local_port_name}")
            self.local_port = None

        if self.autoconnect and self.local_port:
            # Connect local port to remote port
            if not yarp.Network.connect(self.local_port_name, self.remote_port_name):
                logger.warning(f"Failed to connect {self.local_port_name} to {self.remote_port_name}")
            else:
                logger.info(f"Connected {self.local_port_name} to {self.remote_port_name}")
        self.is_initialized = True

        host_i = host if host else self.base_url
        port_i = port if port else self.mcp_port

        try:
            import uvicorn
            logger.info(f"Starting YARP WakeWord MCP Server on {host_i}:{port_i}")
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()

            # Run the app directly without mounting
            uvicorn.run(asgi_app, host=host_i, port=port_i)
        except Exception as e:
            logger.exception("Failed to run MCP server: %s", e)
            raise

if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)
    server = Yarp_mcpServer_WakeWordRPC(config)
    server.run()
