from __future__ import annotations
import asyncio
import logging
from typing import List, Union

from .configuration import Configuration
from .events import EventBus, InternalEventBus
from .shares import (
    SharesManager,
    SharesShelveStorage,
    SharesStorage,
)
from .model import Room, User
from .network.network import Network
from .peer import PeerManager
from .server_manager import ServerManager
from .search import SearchRequest
from .state import State
from .settings import Settings
from .transfer import Transfer, TransferDirection, TransferManager
from .utils import ticket_generator


CLIENT_VERSION = 157
DEFAULT_SETTINGS_NAME = 'aioslsk'


logger = logging.getLogger(__name__)


class SoulSeek:

    def __init__(self, configuration: Configuration, event_bus: EventBus = None):
        super().__init__()
        self.configuration: Configuration = configuration
        self.settings: Settings = configuration.load_settings(DEFAULT_SETTINGS_NAME)

        self._ticket_generator = ticket_generator()
        self._stop_event: asyncio.Event = None

        self.events: EventBus = event_bus or EventBus()
        self._internal_events: InternalEventBus = InternalEventBus()

        self.state: State = State()

        self.network: Network = Network(
            self.state,
            self.settings,
            self._internal_events,
            self._stop_event
        )

        shares_storage: SharesStorage = SharesShelveStorage(self.configuration.data_directory)
        self.shares_manager: SharesManager = SharesManager(
            self.settings,
            shares_storage
        )

        self.transfer_manager: TransferManager = TransferManager(
            self.state,
            self.configuration,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.network
        )
        self.peer_manager: PeerManager = PeerManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.transfer_manager,
            self.network
        )
        self.server_manager: ServerManager = ServerManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.network
        )

    async def start(self):
        # Allows creating client before actually calling asyncio.run(client.start())
        # see https://stackoverflow.com/questions/55918048/asyncio-semaphore-runtimeerror-task-got-future-attached-to-a-different-loop
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self._exception_handler)

        self._stop_event = asyncio.Event()
        self.network._stop_event = self._stop_event

        await self.start_shares_manager()

        await self.connect()

        await self.start_transfer_manager()

    async def connect(self):
        await self.network.initialize()
        await self.server_manager.login(
            self.settings.get('credentials.username'),
            self.settings.get('credentials.password')
        )

    async def start_shares_manager(self):
        self.shares_manager.read_cache()
        self.shares_manager.load_from_settings()
        asyncio.create_task(self.shares_manager.scan())

    async def start_transfer_manager(self):
        await self.transfer_manager.read_transfers_from_storage()

    async def run_until_stopped(self):
        await self._stop_event.wait()
        await self.network.disconnect()

        logger.debug(f"tasks after disconnect : {asyncio.all_tasks()}")

        # Writing database needs to be last, as transfers need to go into the
        # incomplete state if they were still transfering
        self.transfer_manager.write_transfers_to_storage()

    async def stop(self):
        logger.info("signaling client to exit")
        self._stop_event.set()
        self.peer_manager.stop()
        self.transfer_manager.stop()
        self.shares_manager.write_cache()

    def _exception_handler(self, loop, context):
        message = f"unhandled exception on loop {loop!r} : context : {context!r}"
        logger.exception(message, exc_info=context.get('exception', None))

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    def save_settings(self):
        self.configuration.save_settings(DEFAULT_SETTINGS_NAME, self.settings)

    async def download(self, user: Union[str, User], filename: str):
        if isinstance(user, User):
            user = user.name
        transfer = await self.transfer_manager.add(
            Transfer(
                user,
                filename,
                TransferDirection.DOWNLOAD
            )
        )
        await self.transfer_manager.queue(transfer)
        return transfer

    def get_uploads(self) -> List[Transfer]:
        return self.transfer_manager.get_uploads()

    def get_downloads(self) -> List[Transfer]:
        return self.transfer_manager.get_downloads()

    async def remove_transfer(self, transfer: Transfer):
        await self.transfer_manager.remove(transfer)

    async def abort_transfer(self, transfer: Transfer):
        await self.transfer_manager.abort(transfer)

    async def queue_transfer(self, transfer: Transfer):
        await self.transfer_manager.queue(transfer)

    async def join_room(self, room: Union[str, Room]):
        if isinstance(room, Room):
            await self.server_manager.join_room(room.name)
        else:
            await self.server_manager.join_room(room)

    async def get_room_list(self):
        await self.server_manager.get_room_list()

    async def leave_room(self, room: Union[str, Room]):
        if isinstance(room, Room):
            await self.server_manager.leave_room(room.name)
        else:
            await self.server_manager.leave_room(room)

    async def set_room_ticker(self, room: Union[str, Room]):
        if isinstance(room, Room):
            await self.server_manager.set_room_ticker(room.name)
        else:
            await self.server_manager.set_room_ticker(room)

    async def send_private_message(self, user: Union[str, User], message: str):
        if isinstance(user, User):
            await self.server_manager.send_private_message(user.name, message)
        else:
            await self.server_manager.send_private_message(user, message)

    async def send_room_message(self, room: Union[str, Room], message: str):
        if isinstance(room, Room):
            await self.server_manager.send_room_message(room.name, message)
        else:
            await self.server_manager.send_room_message(room, message)

    async def search(self, query: str) -> SearchRequest:
        """Performs a search, returns the generated ticket number for the search
        """
        logger.info(f"Starting search for query: {query}")
        return await self.server_manager.search(query)

    def get_search_results_by_ticket(self, ticket: int):
        """Returns all search results for given ticket"""
        return self.state.search_queries[ticket]

    def remove_search_results_by_ticket(self, ticket: int):
        return self.state.search_queries.pop(ticket)

    async def get_user_stats(self, user: Union[str, User]):
        await self.server_manager.get_user_stats(
            self.state.get_or_create_user(user).name)

    async def get_user_status(self, user: Union[str, User]):
        await self.server_manager.get_user_status(
            self.state.get_or_create_user(user).name)

    async def track_user(self, user: Union[str, User]) -> User:
        return await self.server_manager.track_users(
            self.state.get_or_create_user(user).name)

    async def remove_user(self, user: Union[str, User]):
        await self.server_manager.remove_user(
            self.state.get_or_create_user(user).name)

    # Peer requests
    async def get_user_info(self, user: Union[str, User]):
        await self.peer_manager.get_user_info(
            self.state.get_or_create_user(user).name)

    async def get_user_shares(self, user: Union[str, User]):
        await self.peer_manager.get_user_shares(
            self.state.get_or_create_user(user).name)

    async def get_user_directory(self, user: Union[str, User], directory: List[str]):
        await self.peer_manager.get_user_directory(
            self.state.get_or_create_user(user).name, directory)
