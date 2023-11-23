import asyncio
from collections import deque
from dataclasses import dataclass
from functools import partial
import logging
from typing import Deque, List, Optional, Union, Tuple

from .base_manager import BaseManager
from .constants import POTENTIAL_PARENTS_CACHE_SIZE
from .events import (
    on_message,
    build_message_map,
    ConnectionStateChangedEvent,
    EventBus,
    PeerInitializedEvent,
    MessageReceivedEvent,
    SessionDestroyedEvent,
    SessionInitializedEvent,
)
from .protocol.messages import (
    AcceptChildren,
    BranchLevel,
    BranchRoot,
    DistributedAliveInterval,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedChildDepth,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    GetUserStats,
    MessageDataclass,
    MinParentsInCache,
    ParentInactivityTimeout,
    ParentMinSpeed,
    ParentSpeedRatio,
    PotentialParents,
    ResetDistributed,
    ServerSearchRequest,
    ToggleParentSearch,
)
from .network.connection import (
    CloseReason,
    ConnectionState,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from .network.network import Network
from .session import Session
from .settings import Settings
from .utils import task_counter, ticket_generator


logger = logging.getLogger(__name__)


@dataclass
class DistributedPeer:
    """Represents a distributed peer and its values in the distributed network"""
    username: str
    connection: Optional[PeerConnection] = None
    """Distributed connection (type=D) associated with the peer. A `None` value
    indicates the peer represents the current client
    """
    branch_level: Optional[int] = None
    branch_root: Optional[str] = None
    child_depth: Optional[int] = None


class DistributedNetwork(BaseManager):
    """Class responsible for handling the distributed network"""

    def __init__(self, settings: Settings, event_bus: EventBus, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network

        self._ticket_generator = ticket_generator()
        self._session: Optional[Session] = None

        self.parent: Optional[DistributedPeer] = None
        """Distributed parent. This variable is `None` if we are looking for a
        parent
        """
        self.children: List[DistributedPeer] = []
        self.potential_parents: Deque[str] = deque(
            maxlen=POTENTIAL_PARENTS_CACHE_SIZE)
        self.distributed_peers: List[DistributedPeer] = []

        # State parameters sent by the server
        self.parent_min_speed: Optional[int] = None
        self.parent_speed_ratio: Optional[int] = None
        self.min_parents_in_cache: Optional[int] = None
        self.parent_inactivity_timeout: Optional[int] = None
        self.distributed_alive_interval: Optional[int] = None
        self._max_children: int = 5
        self._accept_children: bool = True

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

        self._potential_parent_tasks: List[asyncio.Task] = []

    def register_listeners(self):
        self._event_bus.register(
            PeerInitializedEvent, self._on_peer_connection_initialized)
        self._event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)
        self._event_bus.register(
            SessionDestroyedEvent, self._on_session_destroyed)

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
        username = self._session.user.name
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

    async def reset(self):
        """Disconnects all parent and child connections"""
        await self._disconnect_children()
        await self._disconnect_parent()

    def _reset_server_values(self):
        self.parent_min_speed = None
        self.parent_speed_ratio = None
        self.distributed_alive_interval = None
        self.min_parents_in_cache = None
        self.parent_inactivity_timeout = None

    async def _set_parent(self, peer: DistributedPeer):
        """Sets the given peer to be our parent.

        :param peer: Peer that should become our parent
        """
        logger.info(f"set parent : {peer}")
        self.parent = peer

        await asyncio.gather(
            *self._cancel_potential_parent_tasks(), return_exceptions=True)
        # Cancel all tasks related to potential parents and disconnect all other
        # distributed connections except for children and the parent connection
        # Other distributed connection from the parent that we have should also
        # be disconnected
        distributed_connections = [
            dpeer.connection for dpeer in self.distributed_peers
            if dpeer in [self.parent, ] + self.children and dpeer.connection is not None
        ]

        disconnect_tasks = []
        for peer_connection in self._network.peer_connections:
            if peer_connection.connection_type == PeerConnectionType.DISTRIBUTED:
                if peer_connection not in distributed_connections:
                    disconnect_tasks.append(
                        peer_connection.disconnect(reason=CloseReason.REQUESTED)
                    )
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)

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
                if peer.connection:
                    await peer.connection.disconnect(reason=CloseReason.REQUESTED)

    async def _disconnect_children(self):
        await asyncio.gather(
            *[self._disconnect_child(child) for child in self.children],
            return_exceptions=True
        )

    async def _disconnect_child(self, peer: DistributedPeer):
        if peer.connection:
            await peer.connection.disconnect(CloseReason.REQUESTED)

    async def _disconnect_parent(self):
        if self.parent:
            if self.parent.connection:
                await self.parent.connection.disconnect(CloseReason.REQUESTED)
            else:
                await self._unset_parent()

    async def _unset_parent(self):
        logger.debug(f"unset parent {self.parent!r}")

        self.parent = None

        if not self._session:
            logger.warning("not advertising branch levels : session is destroyed")
            return

        username = self._session.user.name
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

        await self._network.send_server_messages(*[
            BranchLevel.Request(level),
            BranchRoot.Request(root),
            ToggleParentSearch.Request(False if self.parent else True)
        ])

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

        if not self._accept_children:
            logger.debug(f"not accepting children, rejecting peer as child: {peer}")
            await peer.connection.disconnect(CloseReason.REQUESTED)
            return

        if len(self.children) >= self._max_children:
            logger.debug(
                f"maximum amount of children reached ({len(self.children)} / {self._max_children}), "
                f"rejecting peer as child: {peer}"
            )
            await peer.connection.disconnect(CloseReason.REQUESTED)
            return

        await self._add_child(peer)

    async def _add_child(self, peer: DistributedPeer):
        if not peer.connection:
            return

        logger.debug(f"adding distributed connection as child : {peer!r}")
        self.children.append(peer)
        # Let the child know where we are in the distributed tree
        root, level = self._get_advertised_branch_values()

        await peer.connection.send_message(DistributedBranchLevel.Request(level))
        await peer.connection.send_message(DistributedBranchRoot.Request(root))

    def _remove_child(self, peer: DistributedPeer):
        logger.info(f"removing child : {peer!r}")
        self.children.remove(peer)

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

    # Server messages

    @on_message(ParentMinSpeed.Response)
    async def _on_parent_min_speed(
            self, message: ParentMinSpeed.Response, connection: ServerConnection):
        self.parent_min_speed = message.speed
        await self._request_user_stats()

    @on_message(ParentSpeedRatio.Response)
    async def _on_parent_speed_ratio(
            self, message: ParentSpeedRatio.Response, connection: ServerConnection):
        self.parent_speed_ratio = message.ratio
        await self._request_user_stats()

    @on_message(MinParentsInCache.Response)
    async def _on_min_parents_in_cache(
            self, message: MinParentsInCache.Response, connection: ServerConnection):
        self.min_parents_in_cache = message.amount

    @on_message(DistributedAliveInterval.Response)
    async def _on_ditributed_alive_interval(
            self, message: DistributedAliveInterval.Response, connection: ServerConnection):
        self.distributed_alive_interval = message.interval

    @on_message(ParentInactivityTimeout.Response)
    async def _on_parent_inactivity_timeout(
            self, message: ParentInactivityTimeout.Response, connection: ServerConnection):
        self.parent_inactivity_timeout = message.timeout

    @on_message(PotentialParents.Response)
    async def _on_potential_parents(
            self, message: PotentialParents.Response, connection: ServerConnection):
        if not self._settings.debug.search_for_parent:
            logger.debug("ignoring PotentialParents message : searching for parent is disabled")
            return

        self.potential_parents.extend(
            entry.username for entry in message.entries
        )

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
        if not self._session:
            logger.warning("got server search request without a valid session")

        else:
            username = self._session.user.name
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

        await self.send_messages_to_children(message)

    @on_message(ResetDistributed.Response)
    async def _on_reset_distributed(self, message: ResetDistributed.Response, connection: ServerConnection):
        await self.reset()

    # Distributed messages

    @on_message(DistributedBranchLevel.Request)
    async def _on_distributed_branch_level(
            self, message: DistributedBranchLevel.Request, connection: PeerConnection):
        logger.info(f"branch level {message.level!r}: {connection!r}")

        if not connection.username:
            logger.warning(
                "got DistributedBranchLevel for a connection that wasn't properly initialized")
            return

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
    async def _on_distributed_branch_root(
            self, message: DistributedBranchRoot.Request, connection: PeerConnection):
        logger.info(f"branch root {message.username!r}: {connection!r}")

        if not connection.username:
            logger.warning(
                "got DistributedBranchRoot for a connection that wasn't properly initialized")
            return

        peer = self.get_distributed_peer(connection.username, connection)

        # When we receive branch level 0 we automatically assume the root is the
        # peer who sent the sender
        # Don't do anything if the branch root is what we expected it to be
        if peer.branch_root == message.username:
            return

        peer.branch_root = message.username
        if peer != self.parent:
            await self._check_if_new_parent(peer)
        else:
            logger.info(f"parent advertised new branch root : {message.username}")
            await self._notify_children_of_branch_values()

    @on_message(DistributedChildDepth.Request)
    async def _on_distributed_child_depth(
            self, message: DistributedChildDepth.Request, connection: PeerConnection):
        if not connection.username:
            logger.warning(
                "got DistributedChildDepth for a connection that wasn't properly initialized")
            return

        peer = self.get_distributed_peer(connection.username, connection)
        peer.child_depth = message.depth

    @on_message(DistributedSearchRequest.Request)
    async def _on_distributed_search_request(
            self, message: DistributedSearchRequest.Request, connection: PeerConnection):
        await self.send_messages_to_children(message)

    @on_message(DistributedServerSearchRequest.Request)
    async def _on_distributed_server_search_request(
            self, message: DistributedServerSearchRequest.Request, connection: PeerConnection):
        if message.distributed_code != DistributedSearchRequest.Request.MESSAGE_ID:
            logger.warning(f"no handling for server search request with code {message.distributed_code}")
            return

        dmessage = DistributedSearchRequest.Request(
            unknown=0x31,
            username=message.username,
            ticket=message.ticket,
            query=message.query
        )
        await self.send_messages_to_children(dmessage)

    @on_message(GetUserStats.Response)
    async def _on_get_user_stats(self, message: GetUserStats.Response, connection: ServerConnection):
        if self._session and message.username == self._session.user.name:
            speed = message.user_stats.avg_speed

            if self.parent_min_speed is None or self.parent_speed_ratio is None:
                logger.debug(
                    "got user stats without having received ParentMinSpeed and ParentSpeedRatio "
                    "from the server, using defaults"
                )

            elif speed < self.parent_min_speed * 1024:
                self._accept_children = False
                self._max_children = 0

            else:
                self._accept_children = True
                self._max_children = self._calculate_max_children(speed)

            logger.debug(
                f"adjusting distributed children values: "
                f"accept={self._accept_children}, max_children={self._max_children}"
            )
            await self._network.send_server_messages(
                AcceptChildren.Request(self._accept_children)
            )

    def _has_parent_speed_values(self) -> bool:
        """Returns `True` if `ParentMinSpeed` and `ParentSpeedRatio` has been
        received from the server
        """
        return self.parent_min_speed is not None and self.parent_speed_ratio is not None

    async def _request_user_stats(self):
        """Requests the user stats for the currently logged on user a valid
        session is available and parent speed values have been received
        """
        if self._session is None:
            return

        if self._has_parent_speed_values():
            await self._network.send_server_messages(
                GetUserStats.Request(self._session.user.name)
            )

    def _calculate_max_children(self, upload_speed: int) -> int:
        """Calculates the maximum number of children based on the given upload
        speed
        """
        divider = (self.parent_speed_ratio / 10) * 1024
        return int(upload_speed / divider)

    async def _on_peer_connection_initialized(self, event: PeerInitializedEvent):
        if event.connection.connection_type == PeerConnectionType.DISTRIBUTED:
            peer = DistributedPeer(event.connection.username, event.connection)  # type: ignore
            self.distributed_peers.append(peer)

            # Only check if the peer is a potential child if the connection
            # was not requested by us
            if not event.requested:
                await self._check_if_new_child(peer)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        self._session = event.session
        await self._notify_server_of_parent()

    async def _on_session_destroyed(self, event: SessionDestroyedEvent):
        self._session = None

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        connection = event.connection
        if isinstance(connection, PeerConnection):
            if connection.connection_type != PeerConnectionType.DISTRIBUTED:
                return

            if event.state == ConnectionState.CLOSED:
                peer = self.get_distributed_peer(connection.username, connection)
                if not peer:
                    logger.warning(
                        f"connection was not registered with the distributed network : {connection!r}")
                    return

                # Check if it was the parent or child that was disconnected
                if self.parent and peer == self.parent:
                    await self._unset_parent()

                if peer in self.children:
                    self._remove_child(peer)

                # Remove from the distributed connections
                self.distributed_peers.remove(peer)

        elif isinstance(connection, ServerConnection):

            # When the client itself is branch root it means that the server is
            # our "parent" and must be unset here
            if self.parent and self.parent.connection is None:
                await self._unset_parent()

            self._reset_server_values()

    async def send_messages_to_children(self, *messages: Union[MessageDataclass, bytes]):
        for child in self.children:
            if child.connection:
                child.connection.queue_messages(*messages)

    async def stop(self) -> List[asyncio.Task]:
        """Cancels all pending tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        return self._cancel_potential_parent_tasks()

    def _cancel_potential_parent_tasks(self) -> List[asyncio.Task]:
        cancelled_tasks = []

        for task in self._potential_parent_tasks:
            task.cancel()
            cancelled_tasks.append(task)

        return cancelled_tasks
