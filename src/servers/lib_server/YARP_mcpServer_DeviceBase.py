"""
Base class for yarp device based YARP_mcpServer. This class is used to create a server that can communicate with YARP clients.
"""

from .YARP_mcpServer_Notifier import *

# Configure logging
logging.basicConfig(level=logging.INFO)
globLogger = logging.getLogger(__name__)

class Yarp_mcpServer_DeviceBase(Yarp_mcpServer_Notifier):
    """Abstract Base class for device related Yarp_mcpServer"""

    @abstractmethod
    def __init__(self, conf:yarp.ResourceFinder=None, logger: logging.Logger = globLogger, enableExplicitLogging: bool = True):
        Yarp_mcpServer_Notifier.__init__(self, conf, logger, enableExplicitLogging)
        self.device_driver = None

        self.driver_options = yarp.Property()

        if conf:
            # YARP Property object
            if conf.check("device"):
                self.driver_options.put("device", conf.find("device").asString())
            else:
                raise MissingParameterError("device")
            if conf.check("remote"):
                self.driver_options.put("remote", conf.find("remote").asString())
            if conf.check("local"):
                self.driver_options.put("local", conf.find("local").asString())
            else:
                raise MissingParameterError("local")

    @abstractmethod
    def _interfaceView(self, devDriver:yarp.PolyDriver) -> bool :
        """Abstract method to get the interface view of the device driver"""
        ...

    def _initialize(self) -> bool:

        if not Yarp_mcpServer_Notifier._initialize(self):
            return False

        self.device_driver = yarp.PolyDriver(self.driver_options)

        if not self.device_driver.isValid():
            self.fancyLog.ERROR(f"Failed to create {self.driver_options.find('device').asString()} device. Check if the device is available.")
            return False


        return self._interfaceView(self.device_driver)

