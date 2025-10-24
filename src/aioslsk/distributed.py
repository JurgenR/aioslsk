import asyncio
from collections import deque
from dataclasses import dataclass
from functools import partial
import logging
from typing import Optional, Union

from .base_manager import BaseManager
from .constants import (
    DEFAULT_PARENT_MIN_SPEED,
    DEFAULT_PARENT_SPEED_RATIO,
    POTENTIAL_PARENTS_CACHE_SIZE,
)
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
    ChildDepth,
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


@dataclass(slots=True)
class DistributedPeer:
    """Represents a distributed peer and its values in the distributed network"""
    username: str
    connection: PeerConnection
    """Distributed connection (type=D) associated with the peer"""
    branch_level: Optional[int] = None
    branch_root: Optional[str] = None


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
        self.children: list[DistributedPeer] = []
        self.potential_parents: deque[str] = deque(
            maxlen=POTENTIAL_PARENTS_CACHE_SIZE)
        self.distributed_peers: list[DistributedPeer] = []

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

        self._potential_parent_tasks: list[asyncio.Task] = []

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

    def _get_advertised_branch_values(self) -> tuple[str, int]:
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
        username = self._session.user.name  # type: ignore[union-attr]
        if self.parent:
            # We are the branch root
            if self.parent.branch_root == username:
                return username, 0
            else:
                return self.parent.branch_root, self.parent.branch_level + 1  # type: ignore

        return username, 0

    def get_distributed_peer(self, connection: PeerConnection) -> Optional[DistributedPeer]:
        """Get the distributed peer object related to the given connection.

        This method will return `None` if the connection was not properly
        initialized (no username set on the connection) or if there is no peer
        object associated with the connection
        """
        if connection.username is None:
            return None

        for peer in self.distributed_peers:
            if peer.username == connection.username and peer.connection == connection:
                return peer

        return None

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
        logger.info("set parent : %s", peer)
        self.parent = peer

        await asyncio.gather(
            *self._cancel_potential_parent_tasks(), return_exceptions=True)
        # Cancel all tasks related to potential parents and disconnect all other
        # distributed connections except for children and the parent connection
        # Other distributed connection from the parent that we have should also
        # be disconnected
        distributed_connections = [
            dpeer.connection for dpeer in self.distributed_peers
            if dpeer in [self.parent, ] + self.children
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
                await peer.connection.disconnect(reason=CloseReason.REQUESTED)

    async def _disconnect_children(self):
        await asyncio.gather(
            *[self._disconnect_child(child) for child in self.children],
            return_exceptions=True
        )

    async def _disconnect_child(self, peer: DistributedPeer):
        await peer.connection.disconnect(CloseReason.REQUESTED)

    async def _disconnect_parent(self):
        if self.parent:
            await self.parent.connection.disconnect(CloseReason.REQUESTED)

    async def _unset_parent(self):
        logger.info("unset parent : %s", self.parent)

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
        logger.info("notifying server of our parent : level=%d root=%s", level, root)

        search_for_parent = False if self.parent else True

        if not self._settings.debug.search_for_parent:
            search_for_parent = False

        await self._network.send_server_messages(*[
            BranchLevel.Request(level),
            BranchRoot.Request(root),
            ToggleParentSearch.Request(search_for_parent)
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
            logger.debug("not accepting children, rejecting peer as child : %s", peer)
            await peer.connection.disconnect(CloseReason.REQUESTED)
            return

        if len(self.children) >= self._max_children:
            logger.debug(
                "maximum amount of children reached (%d / %d), rejecting peer as child : %s",
                len(self.children), self._max_children, peer
            )
            await peer.connection.disconnect(CloseReason.REQUESTED)
            return

        await self._add_child(peer)

    async def _add_child(self, peer: DistributedPeer):
        if not peer.connection:
            return

        self.children.append(peer)
        # Let the child know where we are in the distributed tree
        root, level = self._get_advertised_branch_values()

        await peer.connection.send_message(DistributedBranchLevel.Request(level))
        if level != 0:
            await peer.connection.send_message(DistributedBranchRoot.Request(root))

        logger.debug(
            "added distributed connection as child (%d / %d children) : %s",
            len(self.children), self._max_children, peer
        )

    def _remove_child(self, peer: DistributedPeer):
        logger.info("removing child : %r", peer)
        self.children.remove(peer)

        logger.debug(
            "removed distributed connection as child (%d / %d children) : %s",
            len(self.children), self._max_children, peer
        )

    def _potential_parent_task_callback(self, username: str, task: asyncio.Task):
        """Callback for potential parent handling task. This callback simply
        logs the results and removes the task from the list
        """
        try:
            task.result()

        except asyncio.CancelledError:
            logger.debug("request for potential parent cancelled (username=%s)", username)
        except Exception as exc:
            logger.warning("request for potential parent failed : %r (username=%s)", exc, username)
        else:
            logger.info("request for potential parent successful (username=%s)", username)
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

        await self.send_messages_to_children(message)

    @on_message(ResetDistributed.Response)
    async def _on_reset_distributed(self, message: ResetDistributed.Response, connection: ServerConnection):
        await self.reset()

    # Distributed messages

    @on_message(DistributedBranchLevel.Request)
    async def _on_distributed_branch_level(
            self, message: DistributedBranchLevel.Request, connection: PeerConnection):
        logger.info("branch level %r : %r", message.level, connection)

        peer = self.get_distributed_peer(connection)
        if not peer:
            logger.warning("distributed peer object not found for connection: %s : %s", connection, message)
            return

        peer.branch_level = message.level

        # Branch root is not always sent in case the peer advertises branch
        # level 0 because he himself is the root
        if message.level == 0:
            peer.branch_root = peer.username

        if peer != self.parent:
            await self._check_if_new_parent(peer)
        else:
            logger.info("parent advertised new branch level : %d", message.level)
            await self._notify_children_of_branch_values()

    @on_message(DistributedBranchRoot.Request)
    async def _on_distributed_branch_root(
            self, message: DistributedBranchRoot.Request, connection: PeerConnection):
        logger.info(f"branch root {message.username!r}: {connection!r}")

        peer = self.get_distributed_peer(connection)
        if not peer:
            logger.warning("distributed peer object not found for connection: %s : %s", connection, message)
            return

        # When we receive branch level 0 we automatically assume the root is the
        # peer who sent the sender
        # Don't do anything if the branch root is what we expected it to be
        if peer.branch_root == message.username:
            return

        peer.branch_root = message.username
        if peer != self.parent:
            await self._check_if_new_parent(peer)
        else:
            logger.info("parent advertised new branch root : %s", message.username)
            await self._notify_children_of_branch_values()

    @on_message(DistributedChildDepth.Request)
    async def _on_distributed_child_depth(
            self, message: DistributedChildDepth.Request, connection: PeerConnection):

        peer = self.get_distributed_peer(connection)
        if not peer:
            logger.warning("distributed peer object not found for connection: %s : %s", connection, message)
            return

        # Not essential but might be needed for backward compatibility
        if self.parent and self.parent.connection:
            await self.parent.connection.send_message(
                DistributedChildDepth.Request(message.depth + 1)
            )
        else:
            await self._network.send_server_messages(
                ChildDepth.Request(message.depth + 1)
            )

    @on_message(DistributedSearchRequest.Request)
    async def _on_distributed_search_request(
            self, message: DistributedSearchRequest.Request, connection: PeerConnection):

        await self.send_messages_to_children(message)

    @on_message(DistributedServerSearchRequest.Request)
    async def _on_distributed_server_search_request(
            self, message: DistributedServerSearchRequest.Request, connection: PeerConnection):

        if message.distributed_code != DistributedSearchRequest.Request.MESSAGE_ID:
            logger.warning("no handling for server search request with code : %d", message.distributed_code)
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

            if self.parent_min_speed is None:
                logger.debug("using default parent_min_speed: %d", DEFAULT_PARENT_MIN_SPEED)
                parent_min_speed = DEFAULT_PARENT_MIN_SPEED
            else:
                parent_min_speed = self.parent_min_speed

            if self.parent_speed_ratio is None:
                logger.debug("using default parent_speed_ratio: %d", DEFAULT_PARENT_SPEED_RATIO)
                parent_speed_ratio = DEFAULT_PARENT_SPEED_RATIO
            else:
                parent_speed_ratio = self.parent_speed_ratio

            if speed < parent_min_speed * 1024:
                self._accept_children = False
                self._max_children = 0

            else:
                self._accept_children = True
                self._max_children = self._calculate_max_children(speed, parent_speed_ratio)

            logger.debug(
                "adjusting distributed child values: accept=%d, max_children=%d",
                self._accept_children, self._max_children
            )
            await self._network.send_server_messages(
                AcceptChildren.Request(self._accept_children)
            )

    def _has_parent_speed_values(self) -> bool:
        """Returns ``True`` if :class:`.ParentMinSpeed` and
        :class:`.ParentSpeedRatio` have been received from the server
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

    def _calculate_max_children(self, upload_speed: int, parent_speed_ratio: int) -> int:
        """Calculates the maximum number of children based on the given upload
        speed
        """
        divider = (parent_speed_ratio / 10) * 1024
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
                peer = self.get_distributed_peer(connection)
                # Check if there is a distributed peer registered for this
                # connection. A distributed peer is only registered once the
                # full connection initialization has been complete. When the
                # connection fails before this completion this situation could
                # occur
                if not peer:
                    logger.warning(
                        "connection was not registered with the distributed network : %r", connection)
                    return

                # Check if it was the parent or child that was disconnected
                if self.parent and peer == self.parent:
                    await self._unset_parent()

                if peer in self.children:
                    self._remove_child(peer)

                # Remove from the distributed connections
                self.distributed_peers.remove(peer)

        elif isinstance(connection, ServerConnection):

            self._reset_server_values()

    async def send_messages_to_children(self, *messages: Union[MessageDataclass, bytes]):
        for child in self.children:
            child.connection.queue_messages(*messages)

    async def stop(self) -> list[asyncio.Task]:
        """Cancels all pending tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        return self._cancel_potential_parent_tasks()

    def _cancel_potential_parent_tasks(self) -> list[asyncio.Task]:
        cancelled_tasks = []

        for task in self._potential_parent_tasks:
            task.cancel()
            cancelled_tasks.append(task)

        return cancelled_tasks
