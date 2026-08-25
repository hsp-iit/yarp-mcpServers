import logging

class LogStyle:
    HEADER = '\033[95m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    COLORS = {"WARNING":'\033[93m',
              "ERROR":'\033[91m',
              "COMPONENT":'\033[96m',
              "DEBUG":'\033[92m',
              "INFO":'\033[94m'}

class FancyLogger:
    def __init__(self, classToLog:str, logger: logging.Logger = None, enableExplicitLogging: bool = True):
        self.classToLog = classToLog
        self.enableExplicitLogging = enableExplicitLogging
        if logger is None:
            self.logger = logging.getLogger(classToLog)
        else:
            self.logger = logger
        self.defLoggerLevels = {
            "DEBUG": self.logger.debug,
            "INFO": self.logger.info,
            "WARNING": self.logger.warning,
            "ERROR": self.logger.error
        }

    def logMe(self, level:str, message:str):
            self.defLoggerLevels.get(level.upper(), self.logger.info)(message)
            if self.enableExplicitLogging:
                styled = LogStyle()
                comp = "COMPONENT"
                if level.upper() in styled.COLORS.keys():
                    print(f"[{styled.BOLD}{styled.COLORS[level.upper()]}{level.upper()}{styled.ENDC}] " + f"|{styled.BOLD}{styled.COLORS[comp]}{self.classToLog}{styled.ENDC}| " + message)
                else:
                    print("[{0}] [{1}] {2}".format(level.upper(),f"{self.classToLog}",message))

    def ERROR(self, message:str):
        self.logMe("ERROR", message)

    def WARNING(self, message:str):
        self.logMe("WARNING", message)

    def DEBUG(self, message:str):
        self.logMe("DEBUG", message)

    def INFO(self, message:str):
        self.logMe("INFO", message)
