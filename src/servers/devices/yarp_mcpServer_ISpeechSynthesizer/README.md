# YARP Speech Synthesis MCP Server

An MCP (Model Context Protocol) server that provides speech synthesis functionality using YARP (Yet Another Robot Platform).

## Overview

This server accepts text input and uses a YARP `ISpeechSynthesizer` device to generate audio output, which is then transmitted through a YARP `BufferedPort<Sound>`. It's designed to work with YARP's speech synthesis network wrapper servers.

## Prerequisites

- YARP installed with Python bindings
- A running YARP server (`yarpserver`)
- A YARP speech synthesis device (e.g., `speechSynthesizer_nws_yarp`)

## Installation

```bash
# Install dependencies
uv pip install -e .

# Or using pip
pip install -e .
```

## Usage

### 1. Start YARP Infrastructure

```bash
# Start YARP server
yarpserver

# In another terminal, start a speech synthesis device
yarpdev --device speechSynthesizer_nws_yarp --name /speechSynthesizer
```

### 2. Run the MCP Server

```bash
python mcpServer_yarpSpeech.py
```

### 3. Available Tools

The MCP server provides the following tools:

#### `initialize_yarp`
Initialize YARP network and connect to speech synthesis device.

Parameters:
- `device_name`: YARP device driver name (default: "speechSynthesizer_nwc_yarp")
- `remote_port`: Remote port name for the speech synthesizer (default: "/speechSynthesizer/rpc")
- `output_port_name`: Local output port name for audio (default: "/mcp_synth/audio:o")

#### `synthesize_speech`
Synthesize speech from text.

Parameters:
- `text`: The text to synthesize (required)
- `language`: Language code, e.g., "en", "it", "auto" (default: "auto")
- `voice`: Voice name, device-dependent (default: "auto")
- `speed`: Speech speed, 1.0 = normal (default: 1.0)
- `pitch`: Speech pitch, 1.0 = normal (default: 1.0)

#### `get_speech_status`
Get current status of the speech synthesis system.

#### `cleanup_yarp`
Clean up YARP resources and close connections.

## Example Usage Sequence

1. First, call `initialize_yarp` to set up the YARP connection
2. Call `synthesize_speech` with your text to generate audio
3. Optionally call `get_speech_status` to check system status
4. Call `cleanup_yarp` when done to clean up resources

## YARP Network Architecture

```
[MCP Server] -> [speechSynthesizer_nwc_yarp] -> [Network] -> [speechSynthesizer_nws_yarp] -> [Actual TTS Device]
                                                    |
                                              [BufferedPort<Sound>] -> [Audio Output]
```

## Notes

- The server automatically handles YARP network initialization and cleanup
- Audio output is sent through a YARP `BufferedPort<Sound>` to any connected ports
- Voice parameters (language, voice, speed, pitch) are optional and device-dependent
- Error handling is built-in for network failures and device issues

## Troubleshooting

- Ensure YARP server is running before starting the MCP server
- Check that the speech synthesis device is available and properly configured
- Verify YARP network connectivity with `yarp name list`
- Check port connections with `yarp name query /speechSynthesizer/rpc`
