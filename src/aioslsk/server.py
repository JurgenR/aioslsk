import logging

from .base_manager import BaseManager
from .constants import SERVER_PING_INTERVAL
from .events import ConnectionStateChangedEvent, EventBus
from .protocol.messages import Ping
from .network.connection import ConnectionState, ServerConnection
from .network.network import Network
from .settings import Settings
from .tasks import BackgroundTask


logger = logging.getLogger(__name__)


class ServerManager(BaseManager):
    """Class handling server state changes"""

    def __init__(self, settings: Settings, event_bus: EventBus, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network

        self._ping_task: BackgroundTask = BackgroundTask(
            interval=SERVER_PING_INTERVAL,
            task_coro=self._ping_job,
            preempt_wait=True,
            name='server-ping-task'
        )

        self.register_listeners()

    @property
    def connection_state(self) -> ConnectionState:
        return self._network.server_connection.state

    def register_listeners(self):
        self._event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    async def send_ping(self):
        """Send ping to the server"""
        await self._network.send_server_messages(Ping.Request())

    # Job methods
    async def _ping_job(self):
        try:
            await self.send_ping()
        except Exception as exc:
            logger.warning("failed to ping server. exception=%r", exc)

    # Listeners

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            self._ping_task.start()

        elif event.state == ConnectionState.CLOSING:
            self._ping_task.cancel()
