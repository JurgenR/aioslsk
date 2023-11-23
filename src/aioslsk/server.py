import asyncio
import logging
from typing import Optional

from .base_manager import BaseManager
from .constants import SERVER_PING_INTERVAL
from .events import ConnectionStateChangedEvent, EventBus
from .protocol.messages import Ping
from .network.connection import ConnectionState, ServerConnection
from .network.network import Network
from .settings import Settings
from .utils import task_counter


logger = logging.getLogger(__name__)


class ServerManager(BaseManager):
    """Class handling server state changes"""

    def __init__(self, settings: Settings, event_bus: EventBus, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network

        self._ping_task: Optional[asyncio.Task] = None

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
        while True:
            await asyncio.sleep(SERVER_PING_INTERVAL)
            try:
                await self.send_ping()
            except Exception as exc:
                logger.warning(f"failed to ping server. exception={exc!r}")

    def _cancel_ping_task(self):
        if self._ping_task is not None:
            self._ping_task.cancel()
            self._ping_task = None

    # Listeners

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            self._ping_task = asyncio.create_task(
                self._ping_job(),
                name=f'ping-task-{task_counter()}'
            )

        elif event.state == ConnectionState.CLOSING:

            self._cancel_ping_task()
