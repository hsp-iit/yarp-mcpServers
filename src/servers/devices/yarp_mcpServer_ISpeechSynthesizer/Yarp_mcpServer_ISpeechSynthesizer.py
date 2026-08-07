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

from ...lib_server.YARP_mcpServer_DeviceBase import *

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Yarp_mcpServer_ISpeechSynthesizer(Yarp_mcpServer_DeviceBase):
    """YARP Speech Synthesis MCP Server"""

    def __init__(self, conf=None):
        self.speech_interface = None
        self.output_port = None
        server_name = "yarp_mcpServer_ISpeechSynthesizer"
        self.device_name = "speechSynthesizer_nwc_yarp"
        self.local_port = "/mcp_synth/client"
        self.remote_port = "/speechSynthesizer_nws"

        if conf:
            if not conf.check("device"):
                conf.setDefault("device", self.device_name)
            if not conf.check("remote"):
                conf.setDefault("remote", self.remote_port)
            if not conf.check("local"):
                conf.setDefault("local", self.local_port)
            if not conf.check("server_name"):
                conf.setDefault("server_name", server_name)

        self.output_port_name = self.local_port + "/audio:o"
        Yarp_mcpServer_DeviceBase.__init__(self, conf)

    def _register_internal_tools(self):
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

    def _interfaceView(self, devDriver:yarp.PolyDriver) -> bool:

        # Get ISpeechSynthesizer interface
        self.speech_interface = devDriver.viewISpeechSynthesizer()

        if self.speech_interface is None:
            logger.error("Failed to get ISpeechSynthesizer interface")
            return False

        # Create output port for Sound
        self.output_port = yarp.Port()
        if not self.output_port.open(self.output_port_name):
            logger.warning(f"Failed to open output port {self.output_port_name}")
            self.output_port = None
            return False

        return True


if __name__ == "__main__":
    config = yarp.ResourceFinder()
    config.configure(sys.argv)

    server = Yarp_mcpServer_ISpeechSynthesizer(config)
    server.run()
