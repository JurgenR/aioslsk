from __future__ import annotations
import asyncio
import logging
from typing import List, Union

from .configuration import Configuration
from .events import EventBus, InternalEventBus
from .shares.cache import (
    SharesShelveCache,
    SharesCache,
)
from .shares.manager import SharesManager
from .model import Room, User
from .network.network import Network
from .peer import PeerManager
from .server import ServerManager
from .search import SearchRequest
from .state import State
from .settings import Settings
from .transfer.manager import TransferManager
from .transfer.model import Transfer, TransferDirection
from .utils import ticket_generator


CLIENT_VERSION = 157
DEFAULT_SETTINGS_NAME = 'aioslsk'


logger = logging.getLogger(__name__)


class SoulSeekClient:

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

        shares_cache: SharesCache = SharesShelveCache(self.configuration.data_directory)
        self.shares_manager: SharesManager = SharesManager(
            self.settings,
            shares_cache,
            self._internal_events
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

    @property
    def event_loop(self):
        return asyncio.get_running_loop()

    async def start(self, scan_shares=True):
        """Starts the client

        :param scan_shares: start a shares scan as soon as the client starts
        """
        self.event_loop.set_exception_handler(self._exception_handler)

        # Allows creating client before actually calling asyncio.run(client.start())
        # see https://stackoverflow.com/questions/55918048/asyncio-semaphore-runtimeerror-task-got-future-attached-to-a-different-loop
        self._stop_event = asyncio.Event()
        self.network._stop_event = self._stop_event

        await self.start_shares_manager(scan=scan_shares)
        await self.start_transfer_manager()
        await self.connect()
        await self.login()
        await self.transfer_manager.manage_transfers()

    async def connect(self):
        await self.network.initialize()

    async def login(self):
        """Performs a logon to the server with the `credentials` defined in the
        `settings`
        """
        await self.server_manager.login(
            self.settings.get('credentials.username'),
            self.settings.get('credentials.password')
        )

    async def start_shares_manager(self, scan=True):
        self.shares_manager.read_cache()
        self.shares_manager.load_from_settings()
        if scan:
            asyncio.create_task(self.shares_manager.scan())

    async def start_transfer_manager(self):
        await self.transfer_manager.read_cache()

    async def run_until_stopped(self):
        await self._stop_event.wait()

    async def stop(self):
        logger.info("signaling client to exit")
        self._stop_event.set()

        await self.network.disconnect()

        logger.debug(f"tasks after disconnect : {asyncio.all_tasks()}")

        self.peer_manager.stop()
        self.transfer_manager.stop()
        self.shares_manager.write_cache()
        self.transfer_manager.write_cache()

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

    async def track_user(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.track_user(username)

    async def untrack_user(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.untrack_user(username)

    async def get_room_list(self):
        await self.server_manager.get_room_list()

    async def join_room(self, room: Union[str, Room], private: bool = False):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.join_room(room_name, private=private)

    async def leave_room(self, room: Union[str, Room]):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.leave_room(room_name)

    async def add_user_to_room(self, room: Union[str, Room], user: Union[str, User]):
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.add_user_to_room(room_name, username)

    async def remove_user_from_room(self, room: Union[str, Room], user: Union[str, User]):
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.remove_user_from_room(room_name, username)

    async def grant_operator(self, room: Union[str, Room], user: Union[str, User]):
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.grant_operator(room_name, username)

    async def revoke_operator(self, room: Union[str, Room], user: Union[str, User]):
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.revoke_operator(room_name, username)

    async def drop_room_membership(self, room: Union[str, Room]):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.drop_room_membership(room_name)

    async def drop_room_ownership(self, room: Union[str, Room]):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.drop_room_ownership(room_name)

    async def set_room_ticker(self, room: Union[str, Room]):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.set_room_ticker(room_name)

    async def send_private_message(self, user: Union[str, User], message: str):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.send_private_message(username, message)

    async def send_room_message(self, room: Union[str, Room], message: str):
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.send_room_message(room_name, message)

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
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_stats(username)

    async def get_user_status(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_status(username)

    # Peer requests
    async def get_user_info(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_info(username)

    async def get_user_shares(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_shares(username)

    async def get_user_directory(self, user: Union[str, User], directory: List[str]):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_directory(username, directory)
