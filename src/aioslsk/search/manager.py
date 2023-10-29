import asyncio
from collections import deque
from functools import partial
import logging
from typing import Deque, Dict, List, Optional, Union

from ..base_manager import BaseManager
from ..events import (
    on_message,
    build_message_map,
    EventBus,
    InternalEventBus,
    ConnectionStateChangedEvent,
    MessageReceivedEvent,
    UserInfoEvent,
    SearchRequestReceivedEvent,
    SearchResultEvent,
    SessionDestroyedEvent,
    SessionInitializedEvent,
)
from ..protocol.messages import (
    RoomSearch,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    FileSearch,
    PeerSearchReply,
    SearchInactivityTimeout,
    ServerSearchRequest,
    UserSearch,
    WishlistInterval,
    WishlistSearch,
)
from ..network.connection import (
    CloseReason,
    ConnectionState,
    PeerConnection,
    ServerConnection,
)
from ..network.network import Network
from ..room.model import Room
from ..settings import Settings
from ..shares.manager import SharesManager
from ..shares.utils import convert_items_to_file_data
from ..session import Session
from ..transfer.interface import UploadInfoProvider
from ..user.manager import UserManager
from ..user.model import User
from ..utils import task_counter, ticket_generator
from .model import ReceivedSearch, SearchResult, SearchRequest, SearchType


logger = logging.getLogger(__name__)


class SearchManager(BaseManager):
    """Handler for searches requests"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            user_manager: UserManager, shares_manager: SharesManager,
            upload_info_provider: UploadInfoProvider,
            network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network
        self._user_manager: UserManager = user_manager
        self._shares_manager: SharesManager = shares_manager
        self._upload_info_provider: UploadInfoProvider = upload_info_provider

        self._ticket_generator = ticket_generator()
        self._session: Optional[Session] = None

        self.received_searches: Deque[ReceivedSearch] = deque(list(), 500)
        self.requests: Dict[int, SearchRequest] = {}

        # Server variables
        self.search_inactivity_timeout: Optional[int] = None
        self.wishlist_interval: Optional[int] = None

        self.register_listeners()

        self._MESSAGE_MAP = build_message_map(self)

        self._search_reply_tasks: List[asyncio.Task] = []
        self._wishlist_task: Optional[asyncio.Task] = None

    def register_listeners(self):
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)
        self._internal_event_bus.register(
            SessionDestroyedEvent, self._on_session_destroyed)

    def remove_request(self, request: Union[SearchRequest, int]):
        """Removes the search request from the client. Incoming results after
        the request has been removed will be ignored

        :param request: `SearchRequest` object or ticket number to remove
        """
        ticket = request if isinstance(request, int) else request.ticket
        self.requests.pop(ticket)

    async def search(self, query: str) -> SearchRequest:
        """Performs a global search. The results generated by this query will
        stored in the returned object or can be listened to through the
        `SearchResultEvent` event

        :param query: The search query
        :return: An object containing the search request details and results
        """
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            FileSearch.Request(ticket, query)
        )
        self.requests[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.NETWORK
        )
        return self.requests[ticket]

    async def search_room(self, room: Union[str, Room], query: str) -> SearchRequest:
        """Performs a search request on the specific user. The results generated
        by this query will stored in the returned object or can be listened to
        through the `SearchResultEvent` event

        :param room: Room object or name to query
        :param query: The search query
        :return: An object containing the search request details and results
        """
        room_name = room.name if isinstance(room, Room) else room
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            RoomSearch.Request(room_name, ticket, query)
        )
        self.requests[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.ROOM,
            room=room_name
        )
        return self.requests[ticket]

    async def search_user(self, user: Union[str, User], query: str) -> SearchRequest:
        """Performs a search request on the specific user. The results generated
        by this query will stored in the returned object or can be listened to
        through the `SearchResultEvent` event

        :param user: User object or name to query
        :param query: The search query
        :return: An object containing the search request details and results
        """
        username = user.name if isinstance(user, User) else user
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            UserSearch.Request(username, ticket, query)
        )
        self.requests[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.USER,
            username=username
        )
        return self.requests[ticket]

    async def _query_shares_and_reply(self, ticket: int, username: str, query: str):
        """Performs a query on the shares manager and reports the results to the
        user
        """
        visible, locked = self._shares_manager.query(query, username=username)

        result_count = len(visible) + len(locked)
        self.received_searches.append(
            ReceivedSearch(
                username=username,
                query=query,
                result_count=result_count
            )
        )
        await self._event_bus.emit(
            SearchRequestReceivedEvent(
                username=username,
                query=query,
                result_count=result_count
            )
        )

        if len(visible) + len(locked) == 0:
            return

        logger.info(f"found {len(visible)}/{len(locked)} results for query {query!r} (username={username!r})")

        task = asyncio.create_task(
            self._network.send_peer_messages(
                username,
                PeerSearchReply.Request(
                    username=self._session.user.name,
                    ticket=ticket,
                    results=convert_items_to_file_data(visible, use_full_path=True),
                    has_slots_free=self._upload_info_provider.has_slots_free(),
                    avg_speed=int(self._upload_info_provider.get_average_upload_speed()),
                    queue_size=self._upload_info_provider.get_queue_size(),
                    locked_results=convert_items_to_file_data(locked, use_full_path=True)
                )
            ),
            name=f'search-reply-{task_counter()}'
        )
        task.add_done_callback(
            partial(self._search_reply_task_callback, ticket, username, query))
        self._search_reply_tasks.append(task)

    def _search_reply_task_callback(self, ticket: int, username: str, query: str, task: asyncio.Task):
        """Callback for a search reply task. This callback simply logs the
        results and removes the task from the list
        """
        try:
            task.result()

        except asyncio.CancelledError:
            logger.debug(
                f"cancelled delivery of search results (ticket={ticket}, username={username}, query={query})")
        except Exception as exc:
            logger.warning(
                f"failed to deliver search results : {exc!r} (ticket={ticket}, username={username}, query={query})")
        else:
            logger.info(
                f"delivered search results (ticket={ticket}, username={username}, query={query})")
        finally:
            self._search_reply_tasks.remove(task)

    async def _wishlist_job(self, interval: int):
        """Job handling wishlist queries, this method is intended to be run as
        a task. This method will run at the given `interval` (returned by the
        server on start up).
        """
        while True:
            items = self._settings.searches.wishlist

            # Remove all current wishlist searches
            self.requests = {
                ticket: qry for ticket, qry in self.requests.items()
                if qry.search_type != SearchType.WISHLIST
            }

            logger.info(f"starting wishlist search of {len(items)} items")
            # Recreate
            for item in filter(lambda item: item.enabled, items):
                ticket = next(self._ticket_generator)
                self.requests[ticket] = SearchRequest(
                    ticket,
                    item.query,
                    search_type=SearchType.WISHLIST
                )
                self._network.queue_server_messages(
                    WishlistSearch.Request(ticket, item.query)
                )

            await asyncio.sleep(interval)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    @on_message(SearchInactivityTimeout.Response)
    async def _on_search_inactivity_timeout(self, message: SearchInactivityTimeout.Response, connection):
        self.search_inactivity_timeout = message.timeout

    @on_message(DistributedSearchRequest.Request)
    async def _on_distributed_search_request(
            self, message: DistributedSearchRequest.Request, connection: PeerConnection):

        await self._query_shares_and_reply(message.ticket, message.username, message.query)

    @on_message(DistributedServerSearchRequest.Request)
    async def _on_distributed_server_search_request(
            self, message: DistributedServerSearchRequest.Request, connection: PeerConnection):

        if message.distributed_code != DistributedSearchRequest.Request.MESSAGE_ID:
            logger.warning(f"no handling for server search request with code {message.distributed_code}")
            return

        await self._query_shares_and_reply(message.ticket, message.username, message.query)

    @on_message(ServerSearchRequest.Response)
    async def _on_server_search_request(self, message: ServerSearchRequest.Response, connection):
        username = self._session.user.name
        if message.username == username:
            return

        await self._query_shares_and_reply(
            message.ticket, message.username, message.query)

    @on_message(PeerSearchReply.Request)
    async def _on_peer_search_reply(self, message: PeerSearchReply.Request, connection: PeerConnection):
        search_result = SearchResult(
            ticket=message.ticket,
            username=message.username,
            has_free_slots=message.has_slots_free,
            avg_speed=message.avg_speed,
            queue_size=message.queue_size,
            shared_items=message.results,
            locked_results=message.locked_results or []
        )
        try:
            query = self.requests[message.ticket]
        except KeyError:
            logger.warning(f"search reply ticket does not match any search query : {message.ticket}")
        else:
            query.results.append(search_result)
            await self._event_bus.emit(SearchResultEvent(query, search_result))

        await connection.disconnect(reason=CloseReason.REQUESTED)

        # Update the user info
        user = self._user_manager.get_or_create_user(message.username)
        user.avg_speed = message.avg_speed
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free
        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(WishlistInterval.Response)
    async def _on_wish_list_interval(self, message: WishlistInterval.Response, connection):
        self.wishlist_interval = message.interval
        self._cancel_wishlist_task()

        self._wishlist_task = asyncio.create_task(
            self._wishlist_job(message.interval),
            name=f'wishlist-job-{task_counter()}'
        )

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSING:
            self._cancel_wishlist_task()

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        logger.debug(f"search : session initialized : {event.session}")
        self._session = event.session

    async def _on_session_destroyed(self, event: SessionDestroyedEvent):
        self._session = None

    def _cancel_wishlist_task(self) -> Optional[asyncio.Task]:
        task = self._wishlist_task
        if self._wishlist_task is not None:
            self._wishlist_task.cancel()
            self._wishlist_task = None
            return task
        return None

    async def stop(self) -> List[asyncio.Task]:
        """Cancels all pending tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        cancelled_tasks = []

        for task in self._search_reply_tasks:
            task.cancel()
            cancelled_tasks.append(task)

        if (wishlist_task := self._cancel_wishlist_task()) is not None:
            cancelled_tasks.append(wishlist_task)

        return cancelled_tasks