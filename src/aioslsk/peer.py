import asyncio
from dataclasses import dataclass
from functools import partial
import logging
from typing import List, Union, Tuple

from .network.connection import (
    CloseReason,
    ConnectionState,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from .events import (
    on_message,
    build_message_map,
    EventBus,
    InternalEventBus,
    ConnectionStateChangedEvent,
    LoginSuccessEvent,
    PeerInitializedEvent,
    MessageReceivedEvent,
    UserDirectoryEvent,
    UserInfoEvent,
    UserSharesReplyEvent,
    SearchResultEvent,
)
from .protocol.messages import (
    AcceptChildren,
    BranchLevel,
    BranchRoot,
    ToggleParentSearch,
    DistributedChildDepth,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    MessageDataclass,
    PeerDirectoryContentsRequest,
    PeerDirectoryContentsReply,
    PeerSearchReply,
    PeerSharesRequest,
    PeerSharesReply,
    PeerUserInfoReply,
    PeerUserInfoRequest,
    PeerUploadQueueNotification,
    PotentialParents,
    ServerSearchRequest,
)
from .network.network import Network
from .search import ReceivedSearch, SearchResult
from .settings import Settings
from .shares.manager import SharesManager
from .shares.utils import convert_items_to_file_data
from .state import State
from .transfer.manager import TransferManager
from .utils import task_counter, ticket_generator


logger = logging.getLogger(__name__)


@dataclass
class DistributedPeer:
    username: str
    connection: PeerConnection
    branch_level: int = None
    branch_root: str = None
    child_depth: int = None


class PeerManager:
    """Peer manager is responsible for handling peer messages and the
    distributed network
    """

    def __init__(
            self, state: State, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, transfer_manager: TransferManager,
            network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network
        self._shares_manager: SharesManager = shares_manager
        self._transfer_manager: TransferManager = transfer_manager

        self._ticket_generator = ticket_generator()

        self.parent: DistributedPeer = None
        """Distributed parent. This variable is `None` if we are looking for
        parents
        """
        self.children: List[DistributedPeer] = []
        self.potential_parents: List[str] = []
        self.distributed_peers: List[DistributedPeer] = []

        self._internal_event_bus.register(
            PeerInitializedEvent, self._on_peer_connection_initialized)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            LoginSuccessEvent, self._on_login_success)

        self.MESSAGE_MAP = build_message_map(self)

        self._potential_parent_tasks: List[asyncio.Task] = []
        self._search_reply_tasks: List[asyncio.Task] = []

    # External methods
    async def get_user_info(self, username: str):
        await self._network.send_peer_messages(
            username, PeerUserInfoRequest.Request())

    async def get_user_shares(self, username: str):
        await self._network.send_peer_messages(
            username, PeerSharesRequest.Request())

    async def get_user_directory(self, username: str, directory: str) -> int:
        ticket = next(self._ticket_generator)
        await self._network.send_peer_messages(
            username,
            PeerDirectoryContentsRequest.Request(
                ticket=ticket,
                directory=directory
            )
        )
        return ticket

    def _get_advertised_branch_values(self) -> Tuple[str, int]:
        """Returns the advertised branch values. These values are to be sent to
        the children and the server to let them know where we are in the
        distributed tree.

        If no parent:
            * level = 0
            * root = our own username

        If we are the root:
            * level = 0
            * root = our own username

        If we have a parent:
            * level = level parent advertised + 1
            * root = whatever our parent sent us initially
        """
        username = self._settings.get('credentials.username')
        if self.parent:
            # We are the branch root
            if self.parent.branch_root == username:
                return username, 0
            else:
                return self.parent.branch_root, self.parent.branch_level + 1

        return username, 0

    def get_distributed_peer(self, username: str, connection: PeerConnection) -> DistributedPeer:
        for peer in self.distributed_peers:
            if peer.username == username and peer.connection == connection:
                return peer

    async def _set_parent(self, peer: DistributedPeer):
        logger.info(f"set parent : {peer}")
        self.parent = peer

        self._cancel_potential_parent_tasks()
        # Cancel all tasks related to potential parents and disconnect all other
        # distributed connections except for children and the parent connection
        # Other distributed connection from the parent that we have should also
        # be disconnected
        distributed_connections = [
            distributed_peer.connection for distributed_peer in self.distributed_peers
            if distributed_peer in [self.parent, ] + self.children
        ]
        for peer_connection in self._network.peer_connections:
            if peer_connection.connection_type == PeerConnectionType.DISTRIBUTED:
                if peer_connection not in distributed_connections:
                    asyncio.create_task(
                        peer_connection.disconnect(reason=CloseReason.REQUESTED),
                        name=f'disconnect-distributed-{task_counter()}'
                    )

        await self._notify_server_of_parent()
        await self._notify_children_of_branch_values()

    async def _check_if_new_parent(self, peer: DistributedPeer):
        """Called after BranchRoot or BranchLevel, checks if all information is
        complete for this peer/connection to become a parent and makes it a
        parent if we don't have one, otherwise just close the connection.
        """
        # Explicit None checks because we can get 0 as branch level
        if peer.branch_level is not None and peer.branch_root is not None:
            if not self.parent:
                await self._set_parent(peer)
            else:
                await peer.connection.disconnect(reason=CloseReason.REQUESTED)
        else:
            logger.debug(f"{self._settings.get('credentials.username')} : not enough info for parent : {peer}")

    async def _unset_parent(self):
        logger.debug(f"unset parent {self.parent!r}")

        self.parent = None

        username = self._settings.get('credentials.username')
        await self._notify_server_of_parent()

        # TODO: What happens to the children when we lose our parent is still
        # unclear
        await self.send_messages_to_children(
            DistributedBranchLevel.Request(0),
            DistributedBranchRoot.Request(username)
        )

    async def _notify_server_of_parent(self):
        """Notifies the server of our parent or if we don't have any, notify the
        server that we are looking for one
        """
        root, level = self._get_advertised_branch_values()
        logger.info(f"notifying server of our parent : level={level} root={root}")

        messages = [
            BranchLevel.Request(level),
            BranchRoot.Request(root)
        ]

        if self.parent:
            logger.info("notifying server we are not looking for parent")
            messages.extend([
                ToggleParentSearch.Request(False),
                AcceptChildren.Request(True)
            ])
        else:
            logger.info("notifying server we are looking for parent")
            # The original Windows client sends out the child depth (=0) and the
            # ParentIP
            messages.extend([
                ToggleParentSearch.Request(True),
                AcceptChildren.Request(True)
            ])

        await self._network.send_server_messages(*messages)

    async def _notify_children_of_branch_values(self):
        root, level = self._get_advertised_branch_values()
        await self.send_messages_to_children(
            DistributedBranchLevel.Request(level),
            DistributedBranchRoot.Request(root)
        )

    async def _check_if_new_child(self, peer: DistributedPeer):
        """Potentially adds a distributed connection to our list of children.
        """
        if peer.username in self.potential_parents:
            return

        await self._add_child(peer)

    async def _add_child(self, peer: DistributedPeer):
        logger.debug(f"adding distributed connection as child : {peer!r}")
        self.children.append(peer)
        # Let the child know where we are in the distributed tree
        root, level = self._get_advertised_branch_values()
        await peer.connection.send_message(DistributedBranchLevel.Request(level))
        await peer.connection.send_message(DistributedBranchRoot.Request(root))

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

    def _potential_parent_task_callback(self, username: str, task: asyncio.Task):
        """Callback for potential parent handling task. This callback simply
        logs the results and removes the task from the list
        """
        try:
            task.result()

        except asyncio.CancelledError:
            logger.debug(f"request for potential parent cancelled (username={username})")
        except Exception as exc:
            logger.warning(f"request for potential parent failed : {exc!r} (username={username})")
        else:
            logger.info(f"request for potential parent successful (username={username})")
        finally:
            self._potential_parent_tasks.remove(task)

    async def _query_shares_and_reply(self, ticket: int, username: str, query: str):
        """Performs a query on the shares manager and reports the results to the
        user
        """
        visible, locked = self._shares_manager.query(query, username=username)

        self._state.received_searches.append(
            ReceivedSearch(
                username=username,
                query=query,
                matched_files=len(visible) + len(locked)
            )
        )

        if len(visible) + len(locked) == 0:
            return

        logger.info(f"found {len(visible)}/{len(locked)} results for query {query!r} (username={username!r})")

        task = asyncio.create_task(
            self._network.send_peer_messages(
                username,
                PeerSearchReply.Request(
                    username=self._settings.get('credentials.username'),
                    ticket=ticket,
                    results=convert_items_to_file_data(visible, use_full_path=True),
                    has_slots_free=self._transfer_manager.has_slots_free(),
                    avg_speed=int(self._transfer_manager.get_average_upload_speed()),
                    queue_size=self._transfer_manager.get_queue_size(),
                    locked_results=convert_items_to_file_data(locked, use_full_path=True)
                )
            ),
            name=f'search-reply-{task_counter()}'
        )
        task.add_done_callback(
            partial(self._search_reply_task_callback, ticket, username, query))
        self._search_reply_tasks.append(task)

    # Server messages

    @on_message(PotentialParents.Response)
    async def _on_potential_parents(self, message: PotentialParents.Response, connection: ServerConnection):
        if not self._settings.get('debug.search_for_parent'):
            logger.debug("ignoring PotentialParents message : searching for parent is disabled")
            return

        self.potential_parents = [
            entry.username for entry in message.entries
        ]

        for entry in message.entries:
            task = asyncio.create_task(
                self._network.create_peer_connection(
                    entry.username,
                    PeerConnectionType.DISTRIBUTED,
                    ip=entry.ip,
                    port=entry.port
                ),
                name=f'potential-parent-{task_counter()}'
            )
            task.add_done_callback(
                partial(self._potential_parent_task_callback, entry.username)
            )
            self._potential_parent_tasks.append(task)

    @on_message(ServerSearchRequest.Response)
    async def _on_server_search_request(self, message: ServerSearchRequest.Response, connection):
        username = self._settings.get('credentials.username')
        if message.username == username:
            return

        if not self.parent:
            # Set ourself as parent
            parent = DistributedPeer(
                username,
                None,
                branch_root=username,
                branch_level=0
            )
            await self._set_parent(parent)

        await self._query_shares_and_reply(
            message.ticket, message.username, message.query)

        for child in self.children:
            child.connection.queue_messages(message)

    # Peer messages

    @on_message(PeerSharesRequest.Request)
    async def _on_peer_shares_request(self, message: PeerSharesRequest.Request, connection: PeerConnection):
        visible, locked = self._shares_manager.create_shares_reply(connection.username)
        connection.queue_message(
            PeerSharesReply.Request(
                directories=visible,
                locked_directories=locked
            )
        )

    @on_message(PeerSharesReply.Request)
    async def _on_peer_shares_reply(self, message: PeerSharesReply.Request, connection: PeerConnection):
        logger.info(f"PeerSharesReply : from username {connection.username}, got {len(message.directories)} directories")

        user = self._state.get_or_create_user(connection.username)
        locked_directories = message.locked_directories or []

        await self._event_bus.emit(
            UserSharesReplyEvent(user, message.directories, locked_directories)
        )

    @on_message(PeerDirectoryContentsRequest.Request)
    async def _on_peer_directory_contents_req(self, message: PeerDirectoryContentsRequest.Request, connection: PeerConnection):
        directories = self._shares_manager.create_directory_reply(message.directory)
        connection.queue_message(
            PeerDirectoryContentsReply.Request(
                ticket=message.ticket,
                directory=message.directory,
                directories=directories
            )
        )

    @on_message(PeerDirectoryContentsReply.Request)
    async def _on_peer_directory_contents_reply(self, message: PeerDirectoryContentsReply.Request, connection: PeerConnection):
        user = self._state.get_or_create_user(connection.username)
        await self._event_bus.emit(
            UserDirectoryEvent(user, message.directory, message.directories)
        )

    @on_message(PeerSearchReply.Request)
    async def _on_peer_search_reply(self, message: PeerSearchReply.Request, connection: PeerConnection):
        search_result = SearchResult(
            ticket=message.ticket,
            username=message.username,
            has_free_slots=message.has_slots_free,
            avg_speed=message.avg_speed,
            queue_size=message.queue_size,
            shared_items=message.results,
            locked_results=message.locked_results
        )
        try:
            query = self._state.search_requests[message.ticket]
        except KeyError:
            logger.warning(f"search reply ticket does not match any search query : {message.ticket}")
        else:
            query.results.append(search_result)
            await self._event_bus.emit(SearchResultEvent(query, search_result))

        await connection.disconnect(reason=CloseReason.REQUESTED)

        # Update the user info
        user = self._state.get_or_create_user(message.username)
        user.avg_speed = message.avg_speed
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free
        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(PeerUserInfoReply.Request)
    async def _on_peer_user_info_reply(self, message: PeerUserInfoReply.Request, connection: PeerConnection):
        user = self._state.get_or_create_user(connection.username)
        user.description = message
        user.picture = message.picture
        user.upload_slots = message.upload_slots
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free

        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(PeerUserInfoRequest.Request)
    async def _on_peer_user_info_request(self, message: PeerUserInfoRequest.Request, connection: PeerConnection):
        try:
            description = self._settings.get('credentials.info.description')
        except KeyError:
            description = ""

        try:
            picture = self._settings.get('credentials.info.picture')
        except KeyError:
            picture = None

        await connection.send_message(
            PeerUserInfoReply.Request(
                description=description,
                has_picture=bool(picture),
                picture=picture,
                upload_slots=self._transfer_manager.upload_slots,
                queue_size=self._transfer_manager.get_queue_size(),
                has_slots_free=self._transfer_manager.has_slots_free()
            )
        )

    @on_message(PeerUploadQueueNotification.Request)
    async def _on_peer_upload_queue_notification(self, message: PeerUploadQueueNotification.Request, connection: PeerConnection):
        logger.info("PeerUploadQueueNotification")
        await connection.send_message(
            PeerUploadQueueNotification.Request(),
        )

    # Distributed messages

    @on_message(DistributedBranchLevel.Request)
    async def _on_distributed_branch_level(self, message: DistributedBranchLevel.Request, connection: PeerConnection):
        logger.info(f"branch level {message.level!r}: {connection!r}")

        peer = self.get_distributed_peer(connection.username, connection)
        peer.branch_level = message.level

        # Branch root is not always sent in case the peer advertises branch
        # level 0 because he himself is the root
        if message.level == 0:
            peer.branch_root = peer.username

        if peer != self.parent:
            await self._check_if_new_parent(peer)
        else:
            logger.info(f"parent advertised new branch level : {message.level}")
            await self._notify_children_of_branch_values()

    @on_message(DistributedBranchRoot.Request)
    async def _on_distributed_branch_root(self, message: DistributedBranchRoot.Request, connection: PeerConnection):
        logger.info(f"branch root {message.username!r}: {connection!r}")

        peer = self.get_distributed_peer(connection.username, connection)

        # When we receive branch level 0 we automatically assume the root is the
        # peer who sent the sender
        # Don't do anything if the branch root is what we expected it to be
        if peer.branch_root == message.username:
            logger.debug(f"{self._settings.get('credentials.username')} : skipping parent check")
            return

        peer.branch_root = message.username
        if peer != self.parent:
            await self._check_if_new_parent(peer)
        else:
            logger.info(f"parent advertised new branch root : {message.username}")
            await self._notify_children_of_branch_values()

    @on_message(DistributedChildDepth)
    async def _on_distributed_child_depth(self, message: DistributedChildDepth.Request, connection: PeerConnection):
        peer = self.get_distributed_peer(connection.username, connection)
        peer.child_depth = message.depth

    @on_message(DistributedSearchRequest.Request)
    async def _on_distributed_search_request(self, message: DistributedSearchRequest.Request, connection: PeerConnection):
        await self._query_shares_and_reply(message.ticket, message.username, message.query)

        await self.send_messages_to_children(message)

    @on_message(DistributedServerSearchRequest.Request)
    async def _on_distributed_server_search_request(self, message: DistributedServerSearchRequest.Request, connection: PeerConnection):
        if message.distributed_code != DistributedSearchRequest.Request.MESSAGE_ID:
            logger.warning(f"no handling for server search request with code {message.distributed_code}")
            return

        await self._query_shares_and_reply(message.ticket, message.username, message.query)

        dmessage = DistributedSearchRequest.Request(
            unknown=0x31,
            username=message.username,
            ticket=message.ticket,
            query=message.query
        )
        await self.send_messages_to_children(dmessage)

    async def _on_peer_connection_initialized(self, event: PeerInitializedEvent):
        if event.connection.connection_type == PeerConnectionType.DISTRIBUTED:
            peer = DistributedPeer(event.connection.username, event.connection)
            self.distributed_peers.append(peer)

            # Only check if the peer is a potential child if the connection
            # was not requested by us
            if not event.requested:
                await self._check_if_new_child(peer)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, PeerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            if event.connection.connection_type == PeerConnectionType.DISTRIBUTED:
                # Check if it was the parent that was disconnected
                parent = self.parent
                if parent and event.connection == parent.connection:
                    await self._unset_parent()
                    return

                # Check if it was a child
                new_children = []
                for child in self.children:
                    if child.connection == event.connection:
                        logger.debug(f"removing child {child!r}")
                    else:
                        new_children.append(child)
                self.children = new_children

                # Remove from the distributed connections
                self.distributed_peers = [
                    peer for peer in self.distributed_peers
                    if peer.connection != event.connection
                ]

    async def _on_login_success(self, event: LoginSuccessEvent):
        await self._notify_server_of_parent()

    async def send_messages_to_children(self, *messages: Union[MessageDataclass, bytes]):
        for child in self.children:
            child.connection.queue_messages(*messages)

    def stop(self) -> List[asyncio.Task]:
        """Cancels all pending tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        search_tasks = self._cancel_search_reply_tasks()
        potential_parent_tasks = self._cancel_potential_parent_tasks()
        return search_tasks + potential_parent_tasks

    def _cancel_search_reply_tasks(self) -> List[asyncio.Task]:
        cancelled_tasks = []

        for task in self._search_reply_tasks:
            task.cancel()
            cancelled_tasks.append(task)

        return cancelled_tasks

    def _cancel_potential_parent_tasks(self) -> List[asyncio.Task]:
        cancelled_tasks = []

        for task in self._potential_parent_tasks:
            task.cancel()
            cancelled_tasks.append(task)

        return cancelled_tasks
