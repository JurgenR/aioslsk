from __future__ import annotations
import asyncio
import logging
from typing import List, Optional, Union

from .commands import BaseCommand, LoginCommand
from .distributed import DistributedNetwork
from .events import EventBus, InternalEventBus
from .shares.cache import SharesCache, SharesNullCache
from .shares.manager import SharesManager
from .network.network import Network
from .peer import PeerManager
from .room.manager import RoomManager
from .room.model import Room
from .server import ServerManager
from .search.manager import SearchManager
from .search.model import SearchRequest, SearchResult
from .settings import Settings
from .transfer.cache import TransferCache, TransferNullCache
from .transfer.manager import TransferManager
from .transfer.model import Transfer, TransferDirection
from .user.manager import UserManager
from .user.model import User, TrackingFlag
from .utils import ticket_generator


CLIENT_VERSION = 157


logger = logging.getLogger(__name__)


class SoulSeekClient:
    """SoulSeek client class"""

    def __init__(
            self, settings: Settings,
            shares_cache: Optional[SharesCache] = None, transfer_cache: Optional[TransferCache] = None,
            event_bus: Optional[EventBus] = None):
        self.settings: Settings = settings

        self._ticket_generator = ticket_generator()
        self._stop_event: Optional[asyncio.Event] = None

        self.events: EventBus = event_bus or EventBus()
        self._internal_events: InternalEventBus = InternalEventBus()

        # self.network: Network = network
        # self.distributed_network: DistributedNetwork = distributed_network

        # self.user_manager: UserManager = user_manager
        # self.room_manager: RoomManager = room_manager

        # self.shares_manager: SharesManager = shares_manager
        # self.transfer_manager: TransferManager = transfer_manager
        # self.peer_manager: PeerManager = peer_manager
        # self.search_manager: SearchManager = search_manager
        # self.server_manager: ServerManager = server_manager

        self.network: Network = self.create_network()
        self.distributed_network: DistributedNetwork = self.create_distributed_network()

        self.user_manager: UserManager = self.create_user_manager()
        self.room_manager: RoomManager = self.create_room_manager()

        self.shares_manager: SharesManager = self.create_shares_manager(
            shares_cache or SharesNullCache()
        )
        self.transfer_manager: TransferManager = self.create_transfer_manager(
            transfer_cache or TransferNullCache()
        )
        self.peer_manager: PeerManager = self.create_peer_manager()
        self.search_manager: SearchManager = self.create_search_manager()
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
        await self.execute(LoginCommand(
            self.settings.get('credentials.username'),
            self.settings.get('credentials.password')
        ).response())

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
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    async def execute(self, command: BaseCommand):
        if command.response_future:
            self.network.register_response_future(
                command.response_future
            )

        try:
            await command.send(self)
        except Exception:
            if command.response_future:
                command.response_future.cancel()
            raise

        if command.response_future:
            _, response = await asyncio.wait_for(
                command.response_future, timeout=10)
            return command.process_response(self, response)

    async def download(self, user: Union[str, User], filename: str) -> Transfer:
        """Requests to start a downloading the file from the given user

        :param user: User from which to download the file
        :param filename: Name of the file to download. This should be the full
            path to the file as returned in the search results
        :return: a `Transfer` object from which the status of the transfer can
            be requested. If the transfer already exists in the client then this
            transfer will be returned
        """
        username = user.name if isinstance(user, User) else user
        transfer = await self.transfer_manager.add(
            Transfer(
                username,
                filename,
                TransferDirection.DOWNLOAD
            )
        )
        await self.transfer_manager.queue(transfer)
        return transfer

    def get_uploads(self) -> List[Transfer]:
        """Returns a list of uploads tracked by the client"""
        return self.transfer_manager.get_uploads()

    def get_downloads(self) -> List[Transfer]:
        """Returns a list of downloads tracked by the client"""
        return self.transfer_manager.get_downloads()

    async def get_recommendations(self):
        """Request a list of recommendation for you from the server"""
        await self.server_manager.get_recommendations()

    async def get_global_recommendations(self):
        """Request a global list of recommendation from the server"""
        await self.server_manager.get_global_recommendations()

    async def get_item_recommendations(self, item: str):
        """Request a list of recommendation from the server for a specific item

        :param item: Item to request recommendations for
        """
        await self.server_manager.get_item_recommendations(item)

    async def get_similar_users(self, item: Optional[str] = None):
        """Get a list of similar users to you or optionally an item"""
        await self.server_manager.get_similar_users(item=item)

    async def get_user_interests(self, user: Union[str, User]):
        """List all interest of a user

        :param user: User to request interests of
        """
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_interests(username)

    async def add_interest(self, interest: str):
        """Add a new interest

        :param interest: Interest to add
        """
        await self.server_manager.add_interest(interest)

    async def remove_interest(self, interest: str):
        """Removes an interest

        :param interest: Interest to add
        """
        await self.server_manager.remove_interest(interest)

    async def add_hated_interest(self, hated_interest: str):
        """Add a hated interest

        :param hated_interest: Hated interest to add
        """
        await self.server_manager.add_hated_interest(hated_interest)

    async def remove_hated_interest(self, hated_interest: str):
        """Remove a hated interest

        :param hated_interest: Hated interest to remove
        """
        await self.server_manager.remove_hated_interest(hated_interest)

    async def remove_transfer(self, transfer: Transfer):
        """Aborts and removes a transfer completely from the client

        :param transfer: Transfer to remove
        """
        await self.transfer_manager.remove(transfer)

    async def abort_transfer(self, transfer: Transfer):
        """Aborts a running transfer. This action will do nothing on transfers
        that have already been completed.

        :param transfer: Transfer to abort
        """
        await self.transfer_manager.abort(transfer)

    async def queue_transfer(self, transfer: Transfer):
        """Requeues a transfer. This only has effect on transfers that have been
        completed, failed or incomplete.

        :param transfer: Transfer to (re)queue
        """
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
        """Joins a public or private room. If the room does not exist yet it
        will be created

        :param room: Room object or name to join
        :param private: Whether this room should be private or public
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.join_room(room_name, private=private)

    async def leave_room(self, room: Union[str, Room]):
        """Leaves a room we are currently in

        :param room: Room object or name to leave
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.leave_room(room_name)

    async def add_user_to_room(self, room: Union[str, Room], user: Union[str, User]):
        """Invites a user to a private room

        :param room: Private room to add the user to
        :param user: User to add to the private room
        """
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.add_user_to_room(room_name, username)

    async def remove_user_from_room(self, room: Union[str, Room], user: Union[str, User]):
        """Remove a user from a private room

        :param room: Private room to remove the user from
        :param user: User to remove from the private room
        """
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.remove_user_from_room(room_name, username)

    async def grant_operator(self, room: Union[str, Room], user: Union[str, User]):
        """Grants operator to a user in a private room. This can only be done if
        the logged in user is owner of the privateroom

        :param room: Room in which to grant the user operator
        :param user: User object or name to grant operator to
        """
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.grant_operator(room_name, username)

    async def revoke_operator(self, room: Union[str, Room], user: Union[str, User]):
        """Revoke operator from a user in a private room. This can only be done
        if the logged in user is owner of the private room

        :param room: Room in which to revoke the user operator
        :param user: User object or name to revoke operator from
        """
        room_name = room.name if isinstance(room, Room) else room
        username = user.name if isinstance(user, User) else user
        await self.server_manager.revoke_operator(room_name, username)

    async def drop_room_membership(self, room: Union[str, Room]):
        """Drop membership from the given private room

        :param room: Room from which the current user no longer wants to be
            member of
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.drop_room_membership(room_name)

    async def drop_room_ownership(self, room: Union[str, Room]):
        """Drop ownership from the given private room. This will effectively
        disband the entire private room

        :param room: Room from which to drop ownership
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.drop_room_ownership(room_name)

    async def set_room_ticker(self, room: Union[str, Room], ticker: str):
        """Set a message on the room "wall"

        :param room: Room from which to drop ownership
        :param ticker: Message to post on the "wall"
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.set_room_ticker(room_name, ticker)

    async def send_private_message(self, user: Union[str, User], message: str):
        """Sends a private message to a user

        :param user: User to send the private message to
        :param message: Message to send to the user
        """
        username = user.name if isinstance(user, User) else user
        await self.server_manager.send_private_message(username, message)

    async def send_room_message(self, room: Union[str, Room], message: str):
        """Sends a message to a room

        :param room: Room to send the message to
        :param message: Message to send to the room
        """
        room_name = room.name if isinstance(room, Room) else room
        await self.server_manager.send_room_message(room_name, message)

    async def search(self, query: str) -> SearchRequest:
        """Performs a global search. The results generated by this query will
        stored in the returned object or can be listened to through the
        `SearchResultEvent` event

        :param query: The search query
        :return: An object containing the search request details and results
        """
        logger.info(f"Starting search for query: {query}")
        return await self.search_manager.search(query)

    async def search_user(self, user: Union[str, User], query: str) -> SearchRequest:
        """Performs a search request on the specific user. The results generated
        by this query will stored in the returned object or can be listened to
        through the `SearchResultEvent` event

        :param user: User object or name to query
        :param query: The search query
        :return: An object containing the search request details and results
        """
        username = user.name if isinstance(user, User) else user
        return await self.search_manager.search_user(username, query)

    async def search_room(self, room: Union[str, Room], query: str) -> SearchRequest:
        """Performs a search request on the specific user. The results generated
        by this query will stored in the returned object or can be listened to
        through the `SearchResultEvent` event

        :param room: Room object or name to query
        :param query: The search query
        :return: An object containing the search request details and results
        """
        room_name = room.name if isinstance(room, Room) else room
        return await self.search_manager.search_room(room_name, query)

    def get_search_request_by_ticket(self, ticket: int) -> SearchRequest:
        """Returns a search request with given ticket"""
        return self.search_manager.search_requests[ticket]

    def get_search_results_by_ticket(self, ticket: int) -> List[SearchResult]:
        """Returns all search results for given ticket"""
        return self.search_manager.search_requests[ticket].results

    def remove_search_request_by_ticket(self, ticket: int) -> SearchRequest:
        """Removes a search request for given ticket

        :return: The `SearchRequest` object this search belonged to
        """
        return self.search_manager.search_requests.pop(ticket)

    def remove_search_request(self, request: SearchRequest):
        """Removes the search request from the client. Incoming results after
        the request has been removed will be ignored

        :param request: `SearchRequest` object to remove
        """
        self.remove_search_request_by_ticket(request.ticket)

    async def get_user_stats(self, user: Union[str, User]):
        """Request user stats

        :param user: User to request the stats for
        """
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_stats(username)

    async def get_user_status(self, user: Union[str, User]):
        """Request the current status of the user

        :param user: User to request the status for
        """
        username = user.name if isinstance(user, User) else user
        await self.server_manager.get_user_status(username)

    # Peer requests
    async def get_user_info(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_info(username)

    async def get_user_shares(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_shares(username)

    async def get_user_directory(self, user: Union[str, User], directory: str):
        username = user.name if isinstance(user, User) else user
        await self.peer_manager.get_user_directory(username, directory)

    # Creation methods

    def create_network(self) -> Network:
        return Network(
            self.settings,
            self._internal_events
        )

    def create_user_manager(self) -> UserManager:
        return UserManager(
            self.settings,
            self.events,
            self._internal_events,
            self.network
        )

    def create_room_manager(self) -> RoomManager:
        return RoomManager(
            self.settings,
            self.events,
            self._internal_events,
            self.user_manager,
            self.network
        )

    def create_shares_manager(self, cache: SharesCache) -> SharesManager:
        return SharesManager(
            self.settings,
            self._internal_events,
            cache=cache
        )

    def create_transfer_manager(self, cache: TransferCache) -> TransferManager:
        return TransferManager(
            self.settings,
            self.events,
            self._internal_events,
            self.user_manager,
            self.shares_manager,
            self.network,
            cache=cache
        )

    def create_search_manager(self) -> SearchManager:
        return SearchManager(
            self.settings,
            self.events,
            self._internal_events,
            self.user_manager,
            self.shares_manager,
            self.transfer_manager,
            self.network
        )

    def create_server_manager(self) -> ServerManager:
        return ServerManager(
            self.settings,
            self.events,
            self._internal_events,
            self.shares_manager,
            self.network
        )

    def create_peer_manager(self) -> PeerManager:
        return PeerManager(
            self.settings,
            self.events,
            self._internal_events,
            self.user_manager,
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
