# YARP MCP Servers for Device Interfaces

A Python-based Model Context Protocol (MCP) server framework that bridges YARP (Yet Another Robot Platform) device interfaces and enables communication through MCP. This project provides server implementations for various YARP device types, allowing seamless integration with AI models and applications that support the MCP protocol.

## ⚠️ Disclaimer

This codebase has been written with the contribution of generative AI. While the code has been tested, please use it carefully and review it for your specific use case before deploying in production environments.

**This repository is under active development** and may change significantly with each new commit. Breaking changes may occur without notice.


## Overview

This project implements MCP servers that expose YARP device interfaces:

- **Yarp_mcpServer_IBattery** - Battery device interface for monitoring battery status and voltage
- **Yarp_mcpServer_INavigation2D** - 2D Navigation interface for robot path planning and movement
- **Yarp_mcpServer_ISpeechSynthesizer** - Speech synthesis interface for text-to-speech functionality

Each server runs as a separate thread and communicates with YARP devices through local network ports.

## Prerequisites

- Python >= 3.12
- YARP (Yet Another Robot Platform) installed and yarpserver running
- Connected YARP devices to communicate with

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd yarp-mcpServers-devices
   ```

2. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

   Key dependencies (defined in pyproject.toml):
   - `mcp[cli]>=1.14.1` - Model Context Protocol framework
   - `fastapi>=0.118.0` - Web framework for MCP server
   - `uvicorn>=0.37.0` - ASGI server
   - `ollama>=0.6.0` - Optional: for local LLM support
   - `python-dotenv>=1.1.1` - Environment configuration

   > **Note:** This project uses [uv](https://github.com/astral-sh/uv) for fast Python dependency management. Make sure it's installed on your system.

## Quick Start

### Using yarp_server_launcher.py

The `yarp_server_launcher.py` script launches one or more MCP servers based on a configuration file.

**Basic usage:**
```bash
python yarp_server_launcher.py --from config.xml
```

**With multiple parameter overrides:**
```bash
python yarp_server_launcher.py --from config.xml --set param_name new_value
```

### Configuration

Configuration uses YARP's ResourceFinder format (XML files). Here's an example structure:

**example.xml:**
```xml
<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE robot PUBLIC "-//YARP//DTD yarprobotinterface 3.0//EN" "http://www.yarp.it/DTD/yarprobotinterfaceV3.0.dtd">
<robot name="mcpServers" prefix="servers" portprefix="/servers" xmlns:xi="http://www.w3.org/2001/XInclude">
    <devices>
        <!-- Battery Server Configuration -->
        <device name="batteryDevice" type="Yarp_mcpServer_IBattery">
            <param name="yarp_device">battery_nwc_yarp</param>
            <param name="yarp_remote">/battery_nws</param>
            <param name="yarp_local">/battery_nwc</param>
        </device>

        <!-- Navigation Server Configuration -->
        <device name="navDevice" type="Yarp_mcpServer_INavigation2D">
            <param name="yarp_device">navigation_nwc_yarp</param>
            <param name="yarp_remote">/nav2d_nws</param>
            <param name="yarp_local">/nav2d_nwc</param>
        </device>

        <!-- Speech Synthesizer Server Configuration -->
        <device name="synthDevice" type="Yarp_mcpServer_ISpeechSynthesizer">
            <param name="yarp_device">synth_nwc_yarp</param>
            <param name="yarp_remote">/synth_nws</param>
            <param name="yarp_local">/synth_nwc</param>
        </device>
    </devices>
</robot>
```

**example.ini (command-line parameter overrides):**
```ini
config example.xml
yarp_remote /custom_battery_nws
yarp_local /custom_battery_nwc
```

### How It Works

1. **Configuration Parsing**: The launcher reads the XML configuration file using YARP's ResourceFinder
2. **Server Instantiation**: For each device defined in the config, a corresponding MCP server class is instantiated
3. **Thread Management**: Each server runs in its own daemon thread for concurrent operation
4. **Signal Handling**: The launcher gracefully handles SIGINT (Ctrl+C) and SIGTERM signals to cleanly shut down all servers
5. **YARP Communication**: Servers connect to YARP devices through TCP/IP ports and expose their interfaces via MCP tools

## Project Structure

```
yarp-mcpServers-devices/
├── yarp_server_launcher.py      # Main launcher script
├── example.xml                   # Example configuration file
├── example.ini                   # Example parameter overrides
├── pyproject.toml               # Project dependencies and metadata
└── src/
    ├── modules/
    │   └── McpConfigParser.py   # Configuration parsing utilities
    └── servers/
        ├── yarp_mcpServer_IBattery/           # Battery interface MCP server
        ├── yarp_mcpServer_INavigation2D/      # Navigation interface MCP server
        └── yarp_mcpServer_ISpeechSynthesizer/ # Speech synthesis MCP server
```

## Running Servers

### Single Server
```bash
python yarp_server_launcher.py --from resources/contexts/test_servers/test_battery.xml
```

### Multiple Servers (Battery + Navigation)
```bash
python yarp_server_launcher.py --from resources/contexts/test_servers/test_batteryNnavigation.xml
```

### All Servers (Battery + Navigation + Speech Synthesizer)
```bash
python yarp_server_launcher.py --from resources/contexts/test_servers/test_batteryNnavigationNSynth.xml
```

### With Parameter Overrides
```bash
python yarp_server_launcher.py --from example.xml \
    --set battery_yarp_remote /my_battery_nws \
    --set battery_yarp_local /my_battery_nwc
```

## Stopping Servers

Press **Ctrl+C** to gracefully shut down all running servers. The launcher will:
- Catch the interrupt signal
- Clean up server instances
- Close YARP connections
- Exit cleanly

## Troubleshooting

### "yarpserver is not running"
Make sure YARP server is running:
```bash
yarpserver
```

### "Cannot find device"
Verify that:
1. The YARP device is properly initialized
2. The `yarp_remote` port in your config matches the actual device's port
3. YARP network is properly configured (`yarp detect` to check)

### "Server class not found"
Ensure the device `type` attribute in your XML config matches an available server class name:
- `Yarp_mcpServer_IBattery`
- `Yarp_mcpServer_INavigation2D`
- `Yarp_mcpServer_ISpeechSynthesizer`

## Development

To add new MCP servers for additional YARP interfaces:

1. Create a new package in `src/servers/yarp_mcpServer_<InterfaceName>/`
2. Implement the server class following the pattern of existing servers
3. Add the server to the configuration XML
4. Launch with `yarp_server_launcher.py`

## Contributing

Contributions are welcome! Please ensure:
- Code follows Python standards
- Configuration files are well-documented
- Changes are tested with actual YARP devices when possible

## License

[Add your license here]

## References

- [YARP Documentation](http://www.yarp.it/)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
