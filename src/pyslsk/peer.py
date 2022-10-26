import logging
from typing import List, Union

from .connection import (
    ConnectionState,
    PeerConnection,
    PeerConnectionType,
    ProtocolMessage,
)
from .events import (
    on_message,
    build_message_map,
    EventBus,
    InternalEventBus,
    ConnectionStateChangedEvent,
    PeerInitializedEvent,
    MessageReceivedEvent,
    UserInfoReplyEvent,
    UserSharesReplyEvent,
    SearchResultEvent,
)
from .shares import SharesManager
from .protocol.messages import (
    AcceptChildren,
    BranchLevel,
    BranchRoot,
    ToggleParentSearch,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    PeerSearchReply,
    PeerSharesRequest,
    PeerSharesReply,
    PeerUserInfoReply,
    PeerUserInfoRequest,
    PeerUploadQueueNotification,
)
from .network import Network
from .search import ReceivedSearch, SearchResult
from .settings import Settings
from .state import DistributedPeer, State
from .transfer import TransferManager


logger = logging.getLogger()


class PeerManager:

    def __init__(
            self, state: State, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, transfer_manager: TransferManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self.shares_manager: SharesManager = shares_manager
        self.transfer_manager: TransferManager = transfer_manager
        self.network: Network = network

        self._distributed_peers: List[DistributedPeer] = []

        self._internal_event_bus.register(
            PeerInitializedEvent, self._on_peer_connection_initialized)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)

        self.MESSAGE_MAP = build_message_map(self)

    # External methods
    def get_user_info(self, username: str):
        self.network.send_peer_messages(username, PeerUserInfoRequest.create())

    def get_user_shares(self, username: str):
        self.network.send_peer_messages(username, PeerSharesRequest.create())

    def get_distributed_peer(self, username: str, connection: PeerConnection) -> DistributedPeer:
        for peer in self._distributed_peers:
            if peer.username == username and peer.connection == connection:
                return peer

    def set_parent(self, peer: DistributedPeer):
        logger.info(f"set parent : {peer!r}")

        self._state.parent = peer

        logger.info(f"notifying server of our parent : level={peer.branch_level} root={peer.branch_root}")
        # The original Windows client sends out the child depth (=0) and the
        # ParentIP
        self.network.send_server_messages(
            BranchLevel.Request(peer.branch_level + 1).serialize(),
            BranchRoot.Request(peer.branch_root).serialize(),
            ToggleParentSearch.Request(False).serialize(),
            AcceptChildren.Request(True).serialize()
        )

        # Remove all other distributed connections except for children and the
        # current
        # Even the distributed connections from the parent should be removed
        distributed_peers_to_remove = [
            distributed_peer for distributed_peer in self._distributed_peers
            if distributed_peer not in [self._state.parent, ] + self._state.children
        ]

        for distributed_peer in distributed_peers_to_remove:
            distributed_peer.connection.set_state(ConnectionState.SHOULD_CLOSE)

        # Notify children of new parent
        self.send_messages_to_children(
            DistributedBranchLevel.Request(peer.branch_level + 1).serialize(),
            DistributedBranchRoot.Request(peer.branch_root).serialize(),
        )

    def _check_if_new_parent(self, peer: DistributedPeer):
        """Called after BranchRoot or BranchLevel, checks if all information is
        complete for this peer/connection to become a parent and makes it a
        parent if we don't have one, otherwise just close the connection.
        """
        # Explicit None checks because we can get 0 as branch level
        if peer.branch_level is not None and peer.branch_root is not None:
            if self._state.parent is None:
                self.set_parent(peer)
            else:
                peer.connection.set_state(ConnectionState.SHOULD_CLOSE)

    def unset_parent(self):
        logger.debug(f"unset parent {self._state.parent!r}")

        self._state.parent = None

        username = self._settings.get('credentials.username')
        self.network.send_server_messages(
            BranchLevel.Request(0).serialize(),
            BranchRoot.Request(username).serialize(),
            ToggleParentSearch.Request(True).serialize()
        )

        # TODO: What happens to the children when we lose our parent is still
        # unclear
        self.send_messages_to_children(
            DistributedBranchLevel.Request(0).serialize(),
            DistributedBranchRoot.Request(username).serialize()
        )

    def add_potential_child(self, peer: DistributedPeer):
        """Potentially adds a distributed connection to our list of children.
        """
        if peer.username in self._state.potential_parents:
            return

        # Make child
        logger.debug(f"adding distributed connection as child : {peer!r}")
        self._state.children.append(peer)
        # Let the child know where it is in the distributed tree
        self.network.send_peer_messages(
            peer.username,
            DistributedBranchLevel.Request(self._state.parent.branch_level + 1).serialize(),
            DistributedBranchRoot.Request(self._state.parent.branch_root).serialize(),
            connection=peer.connection
        )

    # Peer messages

    @on_message(PeerSharesRequest.Request)
    def _on_peer_shares_request(self, message: PeerSharesRequest.Request, connection: PeerConnection):
        reply = PeerSharesReply.Request(self.shares_manager.create_shares_reply()).serialize()
        connection.queue_messages(reply)

    @on_message(PeerSharesReply.Request)
    def _on_peer_shares_reply(self, message: PeerSharesReply.Request, connection: PeerConnection):
        logger.info(f"PeerSharesReply : from username {connection.username}, got {len(message.directories)} directories")

        user = self._state.get_or_create_user(connection.username)
        self._event_bus.emit(UserSharesReplyEvent(user, message.directories))

    @on_message(PeerSearchReply.Request)
    def _on_peer_search_reply(self, message: PeerSearchReply.Request, connection: PeerConnection):
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
            query = self._state.search_queries[message.ticket]
        except KeyError:
            logger.warning(f"search reply ticket '{message.ticket}' does not match any search query")
        else:
            query.results.append(search_result)
            self._event_bus.emit(SearchResultEvent(query, search_result))
        connection.set_state(ConnectionState.SHOULD_CLOSE)

    @on_message(PeerUserInfoReply.Request)
    def _on_peer_user_info_reply(self, message: PeerUserInfoReply.Request, connection: PeerConnection):
        user = self._state.get_or_create_user(connection.username)
        user.description = message
        user.picture = message.picture
        user.total_uploads = message.upload_slots
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free

        self._event_bus.emit(UserInfoReplyEvent(user))

    @on_message(PeerUserInfoRequest.Request)
    def _on_peer_user_info_request(self, message: PeerUserInfoRequest.Request, connection: PeerConnection):
        logger.info("PeerUserInfoRequest")
        connection.queue_messages(
            PeerUserInfoReply.Request(
                "No description",
                self.transfer_manager.upload_slots,
                self.transfer_manager.get_free_upload_slots(),
                self.transfer_manager.has_slots_free()
            ).serialize()
        )

    @on_message(PeerUploadQueueNotification.Request)
    def _on_peer_upload_queue_notification(self, message: PeerUploadQueueNotification.Request, connection: PeerConnection):
        logger.info("PeerUploadQueueNotification")
        connection.queue_messages(
            PeerUploadQueueNotification.Request().serialize()
        )

    # Distributed messages

    @on_message(DistributedSearchRequest.Request)
    def _on_distributed_search_request(self, message: DistributedSearchRequest.Request, connection: PeerConnection):
        results = self.shares_manager.query(message.query)

        self._state.received_searches.append(
            ReceivedSearch(
                username=message.username,
                query=message.query,
                matched_files=len(results)
            )
        )

        if len(results) == 0:
            return

        logger.info(f"got {len(results)} results for query {message.query} (username={message.username})")

        self.network.send_peer_messages(
            message.username,
            PeerSearchReply.Request(
                username=self._settings.get('credentials.username'),
                ticket=message.ticket,
                results=self.shares_manager.convert_items_to_file_data(results, use_full_path=True),
                has_slots_free=self.transfer_manager.has_slots_free(),
                avg_speed=int(self.transfer_manager.get_average_upload_speed()),
                queue_size=self.transfer_manager.get_queue_size()
            ).serialize()
        )

        self.send_messages_to_children(message.serialize())

    @on_message(DistributedBranchLevel.Request)
    def _on_distributed_branch_level(self, message: DistributedBranchLevel.Request, connection: PeerConnection):
        logger.info(f"branch level {message.level!r}: {connection!r}")

        peer = self.get_distributed_peer(connection.username, connection)
        peer.branch_level = message.level

        # Branch root is not always sent in case the peer advertises branch
        # level 0 because he himself is the root
        if message.level == 0:
            peer.branch_root = peer.username

        if peer != self._state.parent:
            self._check_if_new_parent(peer)
        else:
            self.send_messages_to_children(
                DistributedBranchLevel.Request(message.level + 1).serialize())

    @on_message(DistributedBranchRoot.Request)
    def _on_distributed_branch_root(self, message: DistributedBranchRoot.Request, connection: PeerConnection):
        logger.info(f"branch root {message.username!r}: {connection!r}")

        peer = self.get_distributed_peer(connection.username, connection)
        peer.branch_root = message.username

        if peer != self._state.parent:
            self._check_if_new_parent(peer)
        else:
            self.send_messages_to_children(
                DistributedBranchRoot.Request(message.username).serialize())

    @on_message(DistributedServerSearchRequest.Request)
    def _on_distributed_server_search_request(self, message: DistributedServerSearchRequest.Request, connection: PeerConnection):
        if message.distributed_code != DistributedSearchRequest.Request.MESSAGE_ID:
            logger.warning(f"no handling for server search request with code {message.distributed_code}")
            return

        dmessage = DistributedSearchRequest.Request(
            unknown=0x31,
            username=message.username,
            ticket=message.ticket,
            query=message.query
        ).serialize()
        self.send_messages_to_children(dmessage)

    def _on_peer_connection_initialized(self, event: PeerInitializedEvent):
        if event.connection.connection_type == PeerConnectionType.DISTRIBUTED:
            peer = DistributedPeer(event.connection.username, event.connection)
            self._distributed_peers.append(peer)
            self.add_potential_child(peer)

    def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            self.MESSAGE_MAP[message.__class__](message, event.connection)

    # Connection state changes
    def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, PeerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            if event.connection.connection_type == PeerConnectionType.DISTRIBUTED:
                # Check if it was the parent that was disconnected
                parent = self._state.parent
                if parent and event.connection == parent.connection:
                    self.unset_parent()
                    return

                # Check if it was a child
                new_children = []
                for child in self._state.children:
                    if child.connection == event.connection:
                        logger.debug(f"removing child {child!r}")
                    else:
                        new_children.append(child)
                self._state.children = new_children

                # Remove from the distributed connections
                self._distributed_peers = [
                    peer for peer in self._distributed_peers
                    if peer.connection != event.connection
                ]

    def send_messages_to_children(self, *messages: Union[ProtocolMessage, bytes]):
        for child in self._state.children:
            child.connection.queue_messages(*messages)
