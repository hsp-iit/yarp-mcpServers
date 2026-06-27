"""
Base class for yarp device based YARP_mcpServer. This class is used to create a server that can communicate with YARP clients.
"""

from .YARP_mcpServer_Base import *

class Yarp_mcpServer_DeviceBase(Yarp_mcpServer_Base):
    """Abstract Base class for device related Yarp_mcpServer"""

    @abstractmethod
    def __init__(self, conf:yarp.ResourceFinder=None):
        Yarp_mcpServer_Base.__init__(self, conf)
        self.device_driver = None

        self.driver_options = yarp.Property()

        if conf:
            # YARP Property object
            if conf.check("yarp_device"):
                self.driver_options.put("device", conf.find("yarp_device").asString())
            else:
                raise MissingParameterError("yarp_device")
            if conf.check("yarp_remote"):
                self.driver_options.put("remote", conf.find("yarp_remote").asString())
            if conf.check("yarp_local"):
                self.driver_options.put("local", conf.find("yarp_local").asString())
            else:
                raise MissingParameterError("yarp_local")

    @abstractmethod
    def _interfaceView(self, devDriver:yarp.PolyDriver) -> bool :
        """Abstract method to get the interface view of the device driver"""
        ...

    def _initialize(self):
        # Initialize YARP network

        # Check if YARP server is running
        if not self.yarp_network.checkNetwork():
            logger.error("YARP network not available. Please start yarpserver.")
            return

        self.device_driver = yarp.PolyDriver(self.driver_options)

        if not self.device_driver.isValid():
            logger.error(f"Failed to create {self.driver_options.find('device').asString()} device. Check if the device is available.")
            return


        self.is_initialized = self._interfaceView(self.device_driver)

