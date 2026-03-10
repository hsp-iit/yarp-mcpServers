import xml.etree.ElementTree as ET
import os
import yarp


class McpConfigParser:
    def __init__(self, resource_finder):
        """
        Initialize McpConfigParser with a YARP ResourceFinder.

        The ResourceFinder must contain a "config" key pointing to a valid XML configuration file.
        Values in the XML can be overridden using ResourceFinder entries with keys matching
        the 'extern-name' attributes of parameters.

        Args:
            resource_finder: A YARP ResourceFinder object that must contain
                           a "config" key with a valid XML configuration filename

        Raises:
            ValueError: If ResourceFinder doesn't contain "config" key or it doesn't point to a valid file
            FileNotFoundError: If the configuration file specified doesn't exist
        """
        # Get config filename from ResourceFinder
        config_key = "config"
        if not resource_finder.check(config_key):
            raise ValueError(
                f"ResourceFinder must contain '{config_key}' key with a valid configuration filename"
            )

        # Get the config file name from ResourceFinder
        config_value = resource_finder.find(config_key)
        config_filename = config_value.asString()

        if not config_filename:
            raise ValueError(f"'{config_key}' key does not point to a valid file")

        # Use ResourceFinder's findFileByName to locate the file in configured paths
        self.config_file = resource_finder.findFileByName(config_filename)

        if not self.config_file:
            raise FileNotFoundError(f"Configuration file not found: {config_filename}")

        self.resource_finder = resource_finder
        self.tree = None
        self.root = None
        self.config_data = yarp.Property()
        self.config_data.clear()
        self.devices_dict = {}

        # Load and parse the configuration
        self.load_config()

    def load_config(self):
        """Load and parse the XML configuration file and apply ResourceFinder overrides."""
        try:
            self.tree = ET.parse(self.config_file)
            self.root = self.tree.getroot()
        except ET.ParseError as e:
            print(f"Error parsing XML file: {e}")
            raise
        except FileNotFoundError:
            print(f"Configuration file not found: {self.config_file}")
            raise

        # Extract settings and apply ResourceFinder overrides
        self._extract_and_override_settings()

    def _convert_value_to_type(self, value):
        """
        Automatically convert string value to appropriate type.
        Tries: int -> float -> str (in that order).

        Args:
            value (str): The string value to convert

        Returns:
            int, float, or str: The value converted to its appropriate type
        """
        if value is None:
            return None

        value_str = str(value).strip()

        # Try to convert to int
        try:
            return int(value_str)
        except ValueError:
            pass

        # Try to convert to float
        try:
            return float(value_str)
        except ValueError:
            pass

        # Keep as string
        return value_str

    def _extract_and_override_settings(self):
        """Extract settings from XML and override with ResourceFinder values."""
        # Navigate to devices section
        devices = self.root.find("devices")
        if devices is None:
            return

        # Process each device
        for device in devices.findall("device"):
            device_name = device.get("name")
            # Create a group for this device in the Property
            device_group = self.config_data.addGroup(device_name)
            device_type = device.get("type")
            device_group.put("type", device_type)

            # Store device name and type in devices_dict
            self.devices_dict[device_name] = device_type

            # Process direct parameters
            for param in device.findall("param"):
                param_name = param.get("name")
                extern_name = param.get("extern-name")
                param_value = param.text

                # Check if there's an override in ResourceFinder
                if extern_name and self.resource_finder.check(extern_name):
                    override_value = self.resource_finder.find(extern_name)
                    param_value = override_value.asString()

                converted_value = self._convert_value_to_type(param_value)
                device_group.put(param_name, converted_value)

            # Process grouped parameters
            for group in device.findall("group"):
                group_name = group.get("name")
                # Create a sub-group for the parameters
                group_item = device_group.addGroup(group_name)

                for param in group.findall("param"):
                    param_name = param.get("name")
                    extern_name = param.get("extern-name")
                    param_value = param.text

                    # Check if there's an override in ResourceFinder
                    if extern_name and self.resource_finder.check(extern_name):
                        override_value = self.resource_finder.find(extern_name)
                        param_value = override_value.asString()

                    converted_value = self._convert_value_to_type(param_value)
                    group_item.put(param_name, converted_value)

    def get_setting(self, device_name, param_name):
        """
        Retrieve a specific parameter value from a device configuration.

        Args:
            device_name (str): Name of the device
            param_name (str): Name of the parameter

        Returns:
            str/int/float or None: The parameter value, or None if not found
        """
        device_group = self.config_data.findGroup(device_name)
        if device_group.isNull():
            print(f"Device '{device_name}' not found in configuration.")
            return None

        value = device_group.find(param_name)
        if value.isNull():
            print(f"Setting '{device_name}.{param_name}' not found in configuration.")
            return None

        return value.asString()

    def get_minimal_devices_info(self):
        """
        Retrieve a minimal dictionary of device names and their types.

        Returns:
            dict: A dictionary where keys are device names and values are device types
        """
        return self.devices_dict

    def get_all_settings(self):
        """
        Retrieve all settings from the configuration as a yarp.Property object.

        Returns:
            yarp.Property: Property object containing all device configurations
        """
        return self.config_data

    def get_device_settings(self, device_name):
        """
        Retrieve all settings for a specific device.

        Args:
            device_name (str): Name of the device

        Returns:
            yarp.Bottle or None: Group containing all device settings, or None if device not found
        """
        device_group = self.config_data.findGroup(device_name)
        if device_group.isNull():
            print(f"Device '{device_name}' not found in configuration.")
            return None

        return device_group

