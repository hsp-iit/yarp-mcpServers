import sys
import yarp
import inspect
import signal
import threading
from src.modules.McpConfigParser import McpConfigParser
import src.servers

if __name__ == "__main__":
    print("This is the main module.")
    rfArgs = yarp.ResourceFinder()
    rfArgs.configure(sys.argv)
    print(f"Command-line arguments: {sys.argv}")
    parser = McpConfigParser(rfArgs)
    config_data = parser.get_all_settings()
    minimal_devices_info = parser.get_minimal_devices_info()
    print(f"Parsed Configuration Data: {config_data.toString()}")
    print(f"Minimal Devices Info: {minimal_devices_info}")
    AvailableServers = {
        name: cls for name, cls in inspect.getmembers(src.servers, inspect.isclass)
        if cls.__module__.startswith('src.servers')
    }
    print(f"Available servers: {AvailableServers}")
    if "--just_import" in sys.argv:
        print("Just import flag is set. Exiting without starting servers.")
        sys.exit(0)

    # List to keep track of server threads
    server_threads = []
    server_instances = []
    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        """Handle termination signals (SIGTERM, SIGKILL)"""
        print(f"\nReceived signal {signum}. Shutting down servers...")
        shutdown_event.set()

        # Delete server instances to trigger __del__ cleanup
        for server_instance in server_instances:
            try:
                print(f"Cleaning up {server_instance.__class__.__name__}...")
                del server_instance
            except Exception as e:
                print(f"Error cleaning up server: {e}")

        server_instances.clear()

        # Exit immediately - daemon threads will be forcefully terminated
        print("All servers shut down.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)  # Also handle Ctrl+C

    # Create and start server threads
    for device_name, serv_type in minimal_devices_info.items():
        if serv_type in AvailableServers.keys():
            device_params = config_data.findGroup(device_name)
            server_class = AvailableServers.get(serv_type)
            if server_class:
                server_instance = server_class(device_params)
                server_instances.append(server_instance)

                # Create thread for each server
                thread = threading.Thread(
                    target=server_instance.run,
                    name=f"{serv_type}-{device_name}",
                    daemon=True
                )
                server_threads.append(thread)
                thread.start()
                print(f"Started {serv_type} server for device {device_name}")
            else:
                print(f"Server class not found for device type: {serv_type}")

    # Keep the main thread alive while daemon threads run
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        print("\nInterrupted. Shutting down...")
        signal_handler(signal.SIGINT, None)


