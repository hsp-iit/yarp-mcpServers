#!/usr/bin/env python3
"""
YARP Speech Synthesis MCP Server (Streamable HTTP)

Run:
    pip install uvicorn fastapi
    python yarp_mcp_server.py
Then the MCP endpoint will be available at:
    http://127.0.0.1:4000/mcp
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

class Yarp_mcpServer_ISpeechSynthesizer:
    """YARP Speech Synthesis MCP Server"""

    def __init__(self, conf=None):
        self.mcp = FastMCP("YARP Speech Synthesis Server")
        self.yarp_network = None
        self.device_driver = None
        self.speech_interface = None
        self.output_port = None
        self.is_initialized = False
        self.tool_descriptions = {}
        self.info_port = None
        self.info_port_running = False
        self.server_name = "speech"
        self.base_url = "127.0.0.1"
        self.mcp_port = 4000
        self.device_name = "speechSynthesizer_nwc_yarp"
        self.local_port = "/mcp_synth/client"
        self.remote_port = "/speechSynthesizer_nws"

        if conf:
            # Handle both dict-like and object-like config
            if hasattr(conf, 'check') and hasattr(conf, 'find'):
                # YARP Property object
                if conf.check("yarp_device"):
                    self.device_name = conf.find("yarp_device").asString()
                if conf.check("yarp_remote"):
                    self.remote_port = conf.find("yarp_remote").asString()
                if conf.check("yarp_local"):
                    self.local_port = conf.find("yarp_local").asString()
                if conf.check("output_port"):
                    self.output_port_name = conf.find("output_port").asString()
                if conf.check("mcp_host"):
                    self.base_url = conf.find("mcp_host").asString()
                if conf.check("mcp_port"):
                    self.mcp_port = conf.find("mcp_port").asInt()
            elif isinstance(conf, dict):
                # Dict-like config
                self.device_name = conf.get("yarp_device", self.device_name)
                self.remote_port = conf.get("yarp_remote", self.remote_port)
                self.local_port = conf.get("yarp_local", self.local_port)
                self.output_port_name = conf.get("output_port", self.output_port_name)
                self.base_url = conf.get("mcp_host", self.base_url)
                self.mcp_port = conf.get("mcp_port", self.mcp_port)

        self.output_port_name = self.local_port + "/audio:o"
        self.mcp_url = f"http://{self.base_url}:{self.mcp_port}/mcp"
        self.system_prompt_addendum = self._build_system_prompt_addendum()

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register MCP tools"""

        @self.mcp.tool()
        async def synthesize_speech(text: str, language: str = "auto", voice: str = "auto",
                                  speed: float = 1.0, pitch: float = 1.0) -> dict[str, Any]:
            """Generate speech audio from text using the YARP MCP server. The language has to be set using standard codes (e.g., 'en-US', 'fr-FR'). The system will create audio and report details like sample count, frequency, and channels."""
            # ... (kept your implementation unchanged)
            if not self.is_initialized:
                return {
                    "success": False,
                    "error": "YARP speech synthesis not initialized. Call initialize_yarp first."
                }

            if not text.strip():
                return {
                    "success": False,
                    "error": "Empty text provided"
                }

            try:
                # Set voice parameters
                if language != "auto":
                    ret = self.speech_interface.setLanguage(language)
                    if not ret:
                        logger.warning(f"Failed to set language to {language}")

                if voice != "auto":
                    ret = self.speech_interface.setVoice(voice)
                    if not ret:
                        logger.warning(f"Failed to set voice to {voice}")

                if speed != 1.0:
                    ret = self.speech_interface.setSpeed(speed)
                    if not ret:
                        logger.warning(f"Failed to set speed to {speed}")

                if pitch != 1.0:
                    ret = self.speech_interface.setPitch(pitch)
                    if not ret:
                        logger.warning(f"Failed to set pitch to {pitch}")

                # Create Sound object for output
                sound = yarp.Sound()

                # Perform synthesis
                ret = self.speech_interface.synthesize(text, sound)

                if not ret:
                    return {
                        "success": False,
                        "error": "Speech synthesis failed"
                    }

                self.output_port.write(sound)
                port_status = "Sound sent to connected port(s)"
                # Send sound through output port if connected
                # if self.output_port and self.output_port.getOutputCount() > 0:
                #     self.output_port.write(sound)
                #     port_status = f"Sound sent to {self.output_port.getOutputCount()} connected port(s)"
                # else:
                #     port_status = "No output ports connected"

                return {
                    "success": True,
                    "text": text,
                    "language": language,
                    "voice": voice,
                    "speed": speed,
                    "pitch": pitch,
                    "sound_samples": sound.getSamples(),
                    "sound_frequency": sound.getFrequency(),
                    "sound_channels": sound.getChannels(),
                    "port_status": port_status
                }

            except Exception as e:
                logger.error(f"Error during speech synthesis: {e}")
                return {
                    "success": False,
                    "error": f"Speech synthesis error: {str(e)}"
                }

        @self.mcp.tool()
        async def get_speech_status() -> dict[str, Any]:
            """Get the current status of the YARP speech synthesizer system, including initialization state, device status, and connection information."""
            # ... (kept your implementation unchanged)
            if not self.is_initialized:
                return {
                    "initialized": False,
                    "error": "System not initialized"
                }

            try:
                status = {
                    "initialized": True,
                    "device_valid": self.device_driver.isValid() if self.device_driver else False,
                    "interface_available": self.speech_interface is not None,
                    "output_port_open": self.output_port is not None,
                    "network_connected": self.yarp_network.checkNetwork() if self.yarp_network else False
                }

                if self.output_port:
                    status["output_connections"] = self.output_port.getOutputCount()
                    status["output_port_name"] = self.output_port.getName()

                # Try to get current voice settings
                if self.speech_interface:
                    try:
                        current_language = yarp.std_string()
                        if self.speech_interface.getLanguage(current_language):
                            status["current_language"] = current_language.c_str()

                        current_voice = yarp.std_string()
                        if self.speech_interface.getVoice(current_voice):
                            status["current_voice"] = current_voice.c_str()

                        speed_holder = yarp.DVector(1)
                        if self.speech_interface.getSpeed(speed_holder.get(0)):
                            status["current_speed"] = speed_holder.get(0)

                        pitch_holder = yarp.DVector(1)
                        if self.speech_interface.getPitch(pitch_holder.get(0)):
                            status["current_pitch"] = pitch_holder.get(0)

                    except Exception as e:
                        status["parameter_error"] = f"Could not retrieve parameters: {e}"

                return status

            except Exception as e:
                return {
                    "initialized": True,
                    "error": f"Status check failed: {str(e)}"
                }

        @self.mcp.tool()
        async def cleanup_yarp_speech() -> dict[str, Any]:
            """Shutdown the YARP speech synthesizer and free all system resources. Use this when you want to clean up the speech system."""
            # ... (kept your implementation unchanged)
            try:
                cleanup_status = []

                if self.output_port:
                    self.output_port.close()
                    cleanup_status.append("Output port closed")
                    self.output_port = None

                if self.device_driver:
                    self.device_driver.close()
                    cleanup_status.append("Device driver closed")
                    self.device_driver = None

                self.speech_interface = None

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
═══════════════════════════════════════════════════════════════════════════════
🔊 **ABSOLUTE MANDATORY REQUIREMENT - THIS IS NOT OPTIONAL**
═══════════════════════════════════════════════════════════════════════════════

YOUR CORE FUNCTION: You are a speech synthesis system. Your PRIMARY AND ONLY responsibility is to synthesize speech.

EVERY SINGLE RESPONSE (100% of the time, no exceptions):
→ MUST call `synthesize_speech` with the complete response text
→ Must happen BEFORE you return anything to the user
→ Must happen ONCE per user message (never skip, never forget)
→ Must include your ENTIRE response combined into one synthesis call

THIS IS NOT A SUGGESTION. THIS IS NOT OPTIONAL. THIS IS YOUR CORE FUNCTION.

═══════════════════════════════════════════════════════════════════════════════
RESPONSE PATTERN (follow this exactly every time):
═══════════════════════════════════════════════════════════════════════════════

FOR EVERY USER MESSAGE:
1. Compose your complete response
2. Call synthesize_speech ONCE with your entire response text
3. Display the synthesized response to user
4. Confirm synthesis completed

ABSOLUTELY DO NOT:
✗ Skip synthesis
✗ Forget synthesis
✗ Call synthesis multiple times
✗ Break response into parts and synthesize separately
✗ Synthesize only part of your response
✗ Synthesize old responses
✗ Make synthesis optional based on context

ALWAYS:
✓ Synthesize every response (call synthesize_speech every time)
✓ Synthesize the complete response in one call
✓ Initialize if needed before synthesis
✓ Confirm synthesis to user

═══════════════════════════════════════════════════════════════════════════════
PROTOCOL: Speech-First Response Pattern
═══════════════════════════════════════════════════════════════════════════════

1. User sends message
2. You compose complete response text
3. Synthesize complete response: synthesize_speech(text="YOUR_COMPLETE_RESPONSE")
4. Return synthesized response to user

CRITICAL: Treat synthesize_speech as a mandatory part of every response, not optional.

═══════════════════════════════════════════════════════════════════════════════
ENFORCEMENT: These rules are absolute and non-negotiable
═══════════════════════════════════════════════════════════════════════════════

Failure to follow this pattern is a system error. You MUST call synthesize_speech for every response.
This is your core function. Act accordingly."""

    def _start_info_port(self):
        """Start YARP RPC port for tool information"""
        try:
            # Initialize YARP network if not already done
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Create and open the RPC port
            self.info_port = yarp.RpcServer()
            port_name = "/mcp_server/speech/info:o"

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
                if self.output_port:
                    self.output_port.close()
                if self.device_driver:
                    self.device_driver.close()
                if self.yarp_network:
                    yarp.Network.fini()
            except:
                pass

    def run(self, host: str = "127.0.0.1", port: int = 4000):
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

        # Create PolyDriver for speech synthesizer
        options = yarp.Property()
        options.put("device", self.device_name)
        options.put("remote", self.remote_port)
        options.put("local", "/mcp_synth/client")

        self.device_driver = yarp.PolyDriver(options)

        if not self.device_driver.isValid():
            logger.error(f"Failed to create {self.device_name} device. Check if the device is available.")
            return

        # Get ISpeechSynthesizer interface
        self.speech_interface = self.device_driver.viewISpeechSynthesizer()

        if self.speech_interface is None:
            logger.error("Failed to get ISpeechSynthesizer interface")
            return

        # Create output port for Sound
        self.output_port = yarp.Port()
        if not self.output_port.open(self.output_port_name):
            logger.warning(f"Failed to open output port {self.output_port_name}")
            self.output_port = None

        self.is_initialized = True

        try:
            import uvicorn
            logger.info(f"Starting YARP Speech Synthesis MCP Server on {host}:{port}")
            # Get the ASGI app from FastMCP
            asgi_app = self.mcp.streamable_http_app()

            # Run the app directly without mounting
            uvicorn.run(asgi_app, host=host, port=port)
        except Exception as e:
            logger.exception("Failed to run MCP server: %s", e)
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YARP Speech Synthesis MCP Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=4000, help="Server port (default: 4000)")
    parser.add_argument("--yarp_device", type=str, default="speechSynthesizer_nwc_yarp", help="YARP device name (default: speechSynthesizer_nwc_yarp)")
    parser.add_argument("--yarp_remote", type=str, default="/speechSynthesizer_nws", help="YARP remote port (default: /speechSynthesizer_nws)")
    parser.add_argument("--output_port", type=str, default="/mcp_synth/audio:o", help="Output port name (default: /mcp_synth/audio:o)")
    args = parser.parse_args()

    # Convert args to dict for config
    config = vars(args)
    server = Yarp_mcpServer_ISpeechSynthesizer(config)
    server.run(host=args.host, port=args.port)
