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

from ...lib_server.YARP_mcpServer_Base import *

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
globLogger = logging.getLogger(__name__)

class Yarp_mcpServer_WakeWordRPC(Yarp_mcpServer_Base):
    """YARP WakeWord RPC MCP Server"""

    def __init__(self, conf=None, logger : logging.Logger = globLogger, enableFancyLogging: bool = True):
        self.autoconnect = True
        server_name = "yarp_mcpServer_WakeWordRPC"
        self.local_port_name = "/mcp_ww/rpc:o"
        self.remote_port_name = "/wake/rpc:i"
        self.local_port = None

        if conf:
            if conf.check("remote"):
                self.remote_port_name = conf.find("remote").asString()
            if conf.check("local"):
                self.local_port_name = conf.find("local").asString()
            if conf.check("autoconnect"):
                self.autoconnect = conf.find("autoconnect").asInt8() != 0
            if not conf.check("server_name"):
                conf.setDefault("server_name", server_name)

        Yarp_mcpServer_Base.__init__(self, conf, logger, enableFancyLogging)

    def _register_internal_tools(self):
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
                    self.fancyLog.ERROR("DialogueManager::interactWithDialogMng. Orchestrator returned NACK.")
                    success = False

                return {
                    "success": success,
                    "wake_word_status": "stopped" if success else "error"
                }

            except Exception as e:
                self.fancyLog.ERROR(f"Error during speech synthesis: {e}")
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

    def _register_common_tools(self):
        """Register common MCP tools (none are needed by this synchronous server)."""
        # Register the common tools from the base class
        self.fancyLog.INFO("Not yet implemented: _register_common_tools for Yarp_mcpServer_WakeWordRPC")

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

    def _initialize(self) -> bool:

        if not Yarp_mcpServer_Base._initialize(self):
            return False

        # Create local port for Sound
        self.local_port = yarp.Port()
        if not self.local_port.open(self.local_port_name):
            self.fancyLog.WARNING(f"Failed to open local port {self.local_port_name}")
            return False

        if self.autoconnect and self.local_port:
            # Connect local port to remote port
            if not yarp.Network.connect(self.local_port_name, self.remote_port_name):
                self.fancyLog.WARNING(f"Failed to connect {self.local_port_name} to {self.remote_port_name}")
            else:
                self.fancyLog.INFO(f"Connected {self.local_port_name} to {self.remote_port_name}")
        return True


if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_WakeWordRPC(config)
    server.run()
