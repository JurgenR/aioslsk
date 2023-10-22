import asyncio
import logging
from typing import Optional

from .network.connection import ConnectionState, ServerConnection
from .constants import (
    SERVER_PING_INTERVAL,
)
from .events import (
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
    ScanCompleteEvent,
    ServerDisconnectedEvent,
)
from .protocol.messages import Ping, SharedFoldersFiles
from .network.network import Network
from .shares.manager import SharesManager
from .settings import Settings
from .utils import task_counter


logger = logging.getLogger(__name__)


class ServerManager:
    """Class handling server state changes"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network

        self._ping_task: Optional[asyncio.Task] = None

        self.register_listeners()

    @property
    def connection_state(self) -> ConnectionState:
        return self._network.server_connection.state

    def register_listeners(self):
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    async def send_ping(self):
        """Send ping to the server"""
        await self._network.send_server_messages(Ping.Request())

    async def report_shares(self):
        """Reports the shares amount to the server"""
        folder_count, file_count = self._shares_manager.get_stats()
        logger.debug(f"reporting shares to the server (folder_count={folder_count}, file_count={file_count})")
        await self._network.send_server_messages(
            SharedFoldersFiles.Request(
                shared_folder_count=folder_count,
                shared_file_count=file_count
            )
        )

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

    async def _on_scan_completed(self, event: ScanCompleteEvent):
        await self.report_shares()

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

        elif event.state == ConnectionState.CLOSED:

            await self._event_bus.emit(ServerDisconnectedEvent())
