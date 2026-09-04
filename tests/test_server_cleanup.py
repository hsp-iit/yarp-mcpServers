import inspect
from types import SimpleNamespace

from src.servers import (
    Yarp_mcpServer_IBattery,
    Yarp_mcpServer_INavigation2D,
    Yarp_mcpServer_ISpeechSynthesizer,
    Yarp_mcpServer_JsonRes,
    Yarp_mcpServer_WakeWordRPC,
)
from src.servers.lib_server.YARP_mcpServer_Base import Yarp_mcpServer_Base


class LifecycleServer(Yarp_mcpServer_Base):
    def __init__(self) -> None:
        pass

    def _register_internal_tools(self) -> None:
        pass

    def _register_common_tools(self) -> None:
        pass

    def _build_system_prompt_addendum(self) -> str:
        return ""

    def _initialize(self) -> bool:
        return True

    async def cleanup(self) -> None:
        self._cleanup_base_resources()


def test_all_launchable_servers_implement_async_cleanup() -> None:
    server_classes = (
        Yarp_mcpServer_IBattery,
        Yarp_mcpServer_INavigation2D,
        Yarp_mcpServer_ISpeechSynthesizer,
        Yarp_mcpServer_JsonRes,
        Yarp_mcpServer_WakeWordRPC,
    )

    for server_class in server_classes:
        assert not inspect.isabstract(server_class)
        assert inspect.iscoroutinefunction(server_class.cleanup)


def test_base_resource_cleanup_closes_port_and_requests_server_exit() -> None:
    close_calls = []
    server = LifecycleServer()
    server.info_port_running = True
    server.info_port = SimpleNamespace(close=lambda: close_calls.append(True))
    server._uvicorn_server = SimpleNamespace(should_exit=False)

    server._cleanup_base_resources()

    assert close_calls == [True]
    assert server.info_port is None
    assert server.info_port_running is False
    assert server._uvicorn_server.should_exit is True
