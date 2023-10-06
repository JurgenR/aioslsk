from __future__ import annotations
import asyncio
import logging
from typing import List, Union

from .distributed import DistributedNetwork
from .events import EventBus, InternalEventBus
from .shares.cache import SharesCache, SharesNullCache
from .shares.manager import SharesManager
from .model import Room, User, TrackingFlag
from .network.network import Network
from .peer import PeerManager
from .server import ServerManager
from .search.manager import SearchManager
from .search.model import SearchRequest, SearchResult
from .state import State
from .settings import Settings
from .transfer.cache import TransferCache, TransferNullCache
from .transfer.manager import TransferManager
from .transfer.model import Transfer, TransferDirection
from .utils import ticket_generator


CLIENT_VERSION = 157
DEFAULT_SETTINGS_NAME = 'aioslsk'


logger = logging.getLogger(__name__)


class SoulSeekClient:
    """SoulSeek client class"""

    def __init__(
            self, settings: Settings,
            shares_cache: SharesCache = None, transfer_cache: TransferCache = None,
            event_bus: EventBus = None):
        super().__init__()
        self.settings: Settings = settings

        self._ticket_generator = ticket_generator()
        self._stop_event: asyncio.Event = None

        self.events: EventBus = event_bus or EventBus()
        self._internal_events: InternalEventBus = InternalEventBus()

        self.state: State = State()

        self.network: Network = self.create_network()

        self.shares_manager: SharesManager = self.create_shares_manager(
            shares_cache or SharesNullCache()
        )

        self.transfer_manager: TransferManager = self.create_transfer_manager(
            transfer_cache or TransferNullCache()
        )
        self.peer_manager: PeerManager = self.create_peer_manager()
        self.search_manager: SearchManager = self.create_search_manager()
        self.distributed_network: DistributedNetwork = self.create_distributed_network()
        self.server_manager: ServerManager = self.create_server_manager()

    @property
    def event_loop(self):
        return asyncio.get_running_loop()

    async def start(self, scan_shares=True):
        """Performs a full start up of the client consisting of:
        * Connecting to the server
        * Opening listening ports
        * Performs a login with the user credentials defined in the settings
        * Reading transfer and shares caches
        * Optionally performs an initial scan of the shares

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
        """Initializes the network by connecting to the server and opening the
        configured listening ports
        """
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
        """Reads the shares cache and loads the shared directories from the
        settings

        :param scan: Boolean to indicate whether to start and initial scan or not
        """
        self.shares_manager.read_cache()
        self.shares_manager.load_from_settings()
        if scan:
            asyncio.create_task(self.shares_manager.scan())

    async def start_transfer_manager(self):
        await self.transfer_manager.read_cache()

    async def run_until_stopped(self):
        await self._stop_event.wait()

    async def stop(self):
        """Stops the client this method consists of:

        * Disconnecting the network and waiting for all connections to close
        * Cancel all pending tasks and waiting for them to complete
        * Write the transfer and shares caches
        """
        logger.info("signaling client to exit")
        self._stop_event.set()

        await self.network.disconnect()

        cancelled_tasks = (
            self.transfer_manager.stop() +
            self.search_manager.stop() +
            self.distributed_network.stop()
        )
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)

        self.shares_manager.write_cache()
        self.transfer_manager.write_cache()

    def _exception_handler(self, loop, context):
        message = f"unhandled exception on loop {loop!r} : context : {context!r}"
        logger.exception(message, exc_info=context.get('exception', None))

    async def __aenter__(self) -> SoulSeekClient:
        await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    async def download(self, user: Union[str, User], filename: str) -> Transfer:
        """Requests to start a downloading the file from the given user

        :return: a `Transfer` object from which the status of the transfer can
            be requested
        """
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

    async def get_recommendations(self):
        await self.server_manager.get_recommendations()

    async def get_global_recommendations(self):
        await self.server_manager.get_global_recommendations()

    async def get_item_recommendations(self, item: str):
        await self.server_manager.get_item_recommendations(item)

    async def get_similar_users(self, item: str = None):
        await self.server_manager.get_similar_users(item=item)

    async def get_user_interests(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_interests(username)

    async def add_interest(self, interest: str):
        await self.server_manager.add_interest(interest)

    async def remove_interest(self, interest: str):
        await self.server_manager.remove_interest(interest)

    async def add_hated_interest(self, hated_interest: str):
        await self.server_manager.add_hated_interest(hated_interest)

    async def remove_hated_interest(self, hated_interest: str):
        await self.server_manager.remove_hated_interest(hated_interest)

    async def remove_transfer(self, transfer: Transfer):
        await self.transfer_manager.remove(transfer)

    async def abort_transfer(self, transfer: Transfer):
        await self.transfer_manager.abort(transfer)

    async def queue_transfer(self, transfer: Transfer):
        await self.transfer_manager.queue(transfer)

    async def track_user(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.track_user(username, TrackingFlag.REQUESTED)

    async def untrack_user(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.server_manager.untrack_user(username, TrackingFlag.REQUESTED)

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
        return await self.search_manager.search(query)

    async def search_user(self, query: str, user: Union[str, User]) -> SearchRequest:
        username = user.name if isinstance(user, User) else user
        return await self.search_manager.search_user(username, query)

    async def search_room(self, query: str, room: Union[str, Room]) -> SearchRequest:
        room_name = room.name if isinstance(room, Room) else room
        return await self.search_manager.search_room(room_name, query)

    def get_search_request_by_ticket(self, ticket: int) -> SearchRequest:
        """Returns a search request with given ticket"""
        return self.search_manager.search_requests[ticket]

    def get_search_results_by_ticket(self, ticket: int) -> List[SearchResult]:
        """Returns all search results for given ticket"""
        return self.search_manager.search_requests[ticket].results

    def remove_search_request_by_ticket(self, ticket: int) -> SearchRequest:
        """Removes a search request for given ticket"""
        return self.search_manager.search_requests.pop(ticket)

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

    # Creation methods

    def create_network(self) -> Network:
        return Network(
            self.state,
            self.settings,
            self._internal_events,
            self._stop_event
        )

    def create_shares_manager(self, cache: SharesCache) -> SharesManager:
        return SharesManager(
            self.settings,
            self._internal_events,
            cache=cache
        )

    def create_transfer_manager(self, cache: TransferCache) -> TransferManager:
        return TransferManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.network,
            cache=cache
        )

    def create_search_manager(self) -> SearchManager:
        return SearchManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.transfer_manager,
            self.network
        )

    def create_server_manager(self) -> ServerManager:
        return ServerManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.network
        )

    def create_peer_manager(self) -> PeerManager:
        return PeerManager(
            self.state,
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.transfer_manager,
            self.network
        )

    def create_distributed_network(self) -> DistributedNetwork:
        return DistributedNetwork(
            self.settings,
            self._internal_events,
            self.network
        )
