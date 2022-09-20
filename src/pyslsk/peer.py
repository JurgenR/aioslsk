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
    EventBus,
    UserInfoReplyEvent,
    UserSharesReplyEvent,
    SearchResultEvent,
)
from .filemanager import FileManager
from .messages import (
    pack_int,
    AcceptChildren,
    BranchLevel,
    BranchRoot,
    HaveNoParent,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    PeerPlaceInQueueReply,
    PeerPlaceInQueueRequest,
    PeerSearchReply,
    PeerSharesRequest,
    PeerSharesReply,
    PeerTransferReply,
    PeerTransferRequest,
    PeerTransferQueue,
    PeerTransferQueueFailed,
    PeerUploadFailed,
    PeerUserInfoReply,
    PeerUserInfoRequest,
)
from .network import Network
from .search import ReceivedSearch, SearchResult
from .settings import Settings
from .state import DistributedPeer, State
from .transfer import Transfer, TransferDirection, TransferManager, TransferState


logger = logging.getLogger()


class PeerManager:

    def __init__(self, state: State, settings: Settings, event_bus: EventBus, file_manager: FileManager, transfer_manager: TransferManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self.file_manager: FileManager = file_manager
        self.transfer_manager: TransferManager = transfer_manager
        self.network: Network = network
        self.network.peer_listener = self

        self._distributed_peers: List[DistributedPeer] = []

    # External methods
    def get_user_info(self, username: str):
        self.network.send_peer_messages(
            username,
            PeerUserInfoRequest.create()
        )

    def get_user_shares(self, username: str):
        self.network.send_peer_messages(
            username,
            PeerSharesRequest.create()
        )

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
            BranchLevel.create(peer.branch_level + 1),
            BranchRoot.create(peer.branch_root),
            HaveNoParent.create(False),
            AcceptChildren.create(True)
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
            self._distributed_peers.remove(distributed_peer)

        # Notify children of new parent
        self.send_messages_to_children(
            DistributedBranchLevel.create(peer.branch_level + 1),
            DistributedBranchRoot.create(peer.branch_root),
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
            BranchLevel.create(0),
            BranchRoot.create(username),
            HaveNoParent.create(True)
        )

        # TODO: What happens to the children when we lose our parent is still
        # unclear
        self.send_messages_to_children(
            DistributedBranchLevel.create(0),
            DistributedBranchRoot.create(username)
        )

    def add_potential_child(self, peer: DistributedPeer):
        if peer.username in self._state.potential_parents:
            return

        # Make child
        logger.debug(f"adding distributed connection as child : {peer!r}")
        self._state.children.append(peer)
        # Let the child know where it is in the distributed tree
        self.network.send_peer_messages(
            peer.username,
            BranchLevel.create(self._state.parent.branch_level + 1),
            BranchRoot.create(self._state.parent.branch_root),
            connection=peer.connection
        )

    # Transfer

    @on_message(PeerTransferQueue)
    def on_peer_transfer_queue(self, message, connection: PeerConnection):
        """Initial message received in the transfer process. The peer is
        requesting to download a file from us.
        """
        filename = message.parse()
        logger.info(f"PeerTransferQueue : {filename}")

        username = self.network.get_peer_by_connection(connection)

        transfer_ticket = next(self._state.ticket_generator)
        transfer = Transfer(
            username=username,
            remote_path=filename,
            ticket=transfer_ticket,
            direction=TransferDirection.UPLOAD
        )

        try:
            shared_item = self.file_manager.get_shared_item(filename)
            transfer.local_path = self.file_manager.resolve_path(shared_item)
            transfer.filesize = self.file_manager.get_filesize(transfer.local_path)
        except LookupError:
            self.transfer_manager.queue_transfer(transfer, state=None)
            transfer.fail(reason="File not shared.")
            self.network.send_peer_messages(
                username,
                PeerTransferQueueFailed.create(filename, transfer.fail_reason),
                connection=connection
            )
        else:
            self.transfer_manager.queue_transfer(transfer)

    @on_message(PeerTransferRequest)
    def on_peer_transfer_request(self, message, connection: PeerConnection):
        """The PeerTransferRequest message is sent when the peer is ready to
        transfer the file. The message contains more information about the
        transfer.

        We also handle situations here where the other peer sends this message
        without sending PeerTransferQueue first
        """
        direction, ticket, filename, filesize = message.parse()
        logger.info(f"PeerTransferRequest : {filename} {direction} (filesize={filesize}, ticket={ticket})")

        username = self.network.get_peer_by_connection(connection)
        try:
            transfer = self.transfer_manager.get_transfer(
                username, filename, TransferDirection(direction)
            )
        except LookupError:
            transfer = None

        if TransferDirection(direction) == TransferDirection.UPLOAD:
            if transfer is None:
                # Got a request to upload, possibly without prior PeerTransferQueue
                # message. Kindly put it in queue
                transfer = Transfer(
                    username,
                    filename,
                    TransferDirection.UPLOAD,
                    ticket=ticket
                )
                # Send before queueing: queueing will trigger the transfer
                # manager to re-asses the tranfers and possibly immediatly start
                # the upload
                self.network.send_peer_messages(
                    username,
                    PeerTransferReply.create(ticket, False, reason='Queued'),
                    connection=connection
                )
                self.transfer_manager.queue_transfer(transfer)
            else:
                # Possibly needs a check for state here, perhaps:
                # - QUEUED : Queued
                # - ABORTED : Aborted (or Cancelled?)
                # - COMPLETE : Should go back to QUEUED (reset values for transfer)?
                # - INCOMPLETE : Should go back to QUEUED?
                self.network.send_peer_messages(
                    username,
                    PeerTransferReply.create(ticket, False, reason='Queued'),
                    connection=connection
                )

        else:
            if transfer is None:
                # A download which we don't have in queue, assume we removed it
                self.network.send_peer_messages(
                    username,
                    PeerTransferReply.create(ticket, False, reason='Cancelled'),
                    connection=connection
                )
            else:
                # All clear to upload
                # Possibly needs a check to see if there's any inconsistencies
                # normally we get this response when we were the one requesting
                # to upload so ideally all should be fine here.
                transfer.ticket = ticket
                transfer.filesize = filesize

                logger.debug(f"PeerTransferRequest : sending PeerTransferReply (ticket={ticket})")
                self.network.send_peer_messages(
                    username,
                    PeerTransferReply.create(ticket, True),
                    connection=connection
                )

    @on_message(PeerTransferReply)
    def on_peer_transfer_reply(self, message, connection: PeerConnection):
        ticket, allowed, filesize, reason = message.parse()
        logger.info(f"PeerTransferReply : allowed={allowed}, filesize={filesize}, reason={reason!r} (ticket={ticket})")

        transfer = self.transfer_manager.get_transfer_by_ticket(ticket)
        if not allowed:
            if reason == 'Queued':
                transfer.set_state(TransferState.QUEUED)
            else:
                transfer.fail(reason=reason)
            return

        # Init the file connection for transfering the file
        connection_ticket = next(self._state.ticket_generator)
        self.network.init_peer_connection(
            connection_ticket,
            transfer.username,
            typ=PeerConnectionType.FILE,
            transfer=transfer,
            messages=[pack_int(ticket)]
        )

    @on_message(PeerPlaceInQueueRequest)
    def on_peer_place_in_queue_request(self, message, connection: PeerConnection):
        filename = message.parse()
        logger.info(f"{message.__class__.__name__}: {filename}")

        username = self.network.get_peer_by_connection(connection)
        try:
            transfer = self.transfer_manager.get_transfer(
                username,
                filename,
                TransferDirection.UPLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueRequest : could not find transfer (upload) for {filename} from {username}")
        else:
            place = self.transfer_manager.get_place_in_queue(transfer)
            if place > 0:
                self.network.send_peer_messages(
                    username,
                    PeerPlaceInQueueReply.create(filename, place),
                    connection=connection
                )

    @on_message(PeerPlaceInQueueReply)
    def on_peer_place_in_queue_reply(self, message, connection: PeerConnection):
        filename, place = message.parse()
        logger.info(f"{message.__class__.__name__}: filename={filename}, place={place}")

        username = self.network.get_peer_by_connection(connection)
        try:
            transfer = self.transfer_manager.get_transfer(
                username,
                filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueReply : could not find transfer (download) for {filename} from {username}")
        else:
            transfer.place_in_queue = place

    @on_message(PeerUploadFailed)
    def on_peer_upload_failed(self, message, connection: PeerConnection):
        filename = message.parse()
        logger.info(f"PeerUploadFailed : upload failed for {filename}")

        username = self.network.get_peer_by_connection(connection)
        try:
            transfer = self.transfer_manager.get_transfer(
                username,
                filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerUploadFailed : could not find transfer (download) for {filename} from {username}")
        else:
            transfer.fail()

    @on_message(PeerTransferQueueFailed)
    def on_peer_transfer_queue_failed(self, message, connection: PeerConnection):
        filename, reason = message.parse()
        logger.info(f"PeerTransferQueueFailed : upload failed for {filename}, reason={reason}")

        username = self.network.get_peer_by_connection(connection)
        try:
            transfer = self.transfer_manager.get_transfer_by_connection(connection)
        except LookupError:
            logger.error(f"PeerTransferQueueFailed : could not find transfer for {filename} from {username}")
        else:
            transfer.fail(reason=reason)

    # Peer messages

    @on_message(PeerSharesRequest)
    def on_peer_shares_request(self, message, connection: PeerConnection):
        _ = message.parse()

        reply = PeerSharesReply.create(self.file_manager.create_shares_reply())
        connection.queue_message(reply)

    @on_message(PeerSharesReply)
    def on_peer_shares_reply(self, message, connection: PeerConnection):
        directories = message.parse()

        username = self.network.get_peer_by_connection(connection)

        logger.info(f"PeerSharesReply : from username {username}, got {len(directories)} directories")

        user = self._state.get_or_create_user(username)
        self._event_bus.emit(UserSharesReplyEvent(user, directories))

    @on_message(PeerSearchReply)
    def on_peer_search_reply(self, message, connection: PeerConnection):
        contents = message.parse()
        username, ticket, shared_items, has_free_slots, avg_speed, queue_size, locked_results = contents

        search_result = SearchResult(
            ticket=ticket,
            username=username,
            has_free_slots=has_free_slots,
            avg_speed=avg_speed,
            queue_size=queue_size,
            shared_items=shared_items,
            locked_results=locked_results
        )
        try:
            query = self._state.search_queries[ticket]
        except KeyError:
            logger.warning(f"search reply ticket '{ticket}' does not match any search query")
        else:
            query.results.append(search_result)
            self._event_bus.emit(SearchResultEvent(query, search_result))

    @on_message(PeerUserInfoReply)
    def on_peer_user_info_reply(self, message, connection: PeerConnection):
        contents = message.parse()
        description, picture, upload_slots, queue_size, has_slots_free = contents
        logger.info(f"PeerUserInfoReply : {contents!r}")

        username = self.network.get_peer_by_connection(connection)

        user = self._state.get_or_create_user(username)
        user.description = description
        user.picture = picture
        user.total_uploads = upload_slots
        user.queue_length = queue_size
        user.has_slots_free = has_slots_free

        self._event_bus.emit(UserInfoReplyEvent(user))

    @on_message(PeerUserInfoRequest)
    def on_peer_user_info_request(self, message, connection: PeerConnection):
        logger.info("PeerUserInfoRequest")
        connection.queue_message(
            PeerUserInfoReply.create(
                "No description",
                self.transfer_manager.upload_slots,
                self.transfer_manager.get_free_upload_slots(),
                self.transfer_manager.has_slots_free()
            )
        )

    # Distributed messages

    @on_message(DistributedSearchRequest)
    def on_distributed_search_request(self, message, connection: PeerConnection):
        _, username, search_ticket, query = message.parse()
        # logger.info(f"search request from {username!r}, query: {query!r}")
        results = self.file_manager.query(query)

        self._state.received_searches.append(
            ReceivedSearch(username=username, query=query, matched_files=len(results))
        )

        if len(results) == 0:
            return

        logger.info(f"got {len(results)} results for query {query}")

        self.network.send_peer_messages(
            username,
            PeerSearchReply.create(
                self._settings.get('credentials.username'),
                search_ticket,
                self.file_manager.convert_items_to_file_data(results, use_full_path=True),
                self.transfer_manager.has_slots_free(),
                int(self.transfer_manager.get_average_upload_speed()),
                self.transfer_manager.get_queue_size()
            )
        )

    @on_message(DistributedBranchLevel)
    def on_distributed_branch_level(self, message, connection: PeerConnection):
        level = message.parse()
        logger.info(f"branch level {level!r}: {connection!r}")

        username = self.network.get_peer_by_connection(connection)
        peer = self.get_distributed_peer(username, connection)
        peer.branch_level = level

        # Branch root is not always sent in case the peer advertises branch
        # level 0 because he himself is the root
        if level == 0:
            peer.branch_root = peer.username

        if peer != self._state.parent:
            self._check_if_new_parent(peer)
        else:
            self.send_messages_to_children(DistributedBranchLevel.create(level + 1))

    @on_message(DistributedBranchRoot)
    def on_distributed_branch_root(self, message, connection: PeerConnection):
        root = message.parse()
        logger.info(f"branch root {root!r}: {connection!r}")

        username = self.network.get_peer_by_connection(connection)
        peer = self.get_distributed_peer(username, connection)
        peer.branch_root = root

        if peer != self._state.parent:
            self._check_if_new_parent(peer)
        else:
            self.send_messages_to_children(DistributedBranchRoot.create(root))

    @on_message(DistributedServerSearchRequest)
    def on_distributed_server_search_request(self, message, connection: PeerConnection):
        distrib_code, distrib_message = message.parse()
        logger.info(f"distributed server search request: {distrib_code} {distrib_message}")

        if distrib_code != DistributedSearchRequest.MESSAGE_ID:
            logger.warning(f"no handling for server search request with code {distrib_code}")

        for child in self._state.children:
            child.connection.queue_message(
                DistributedSearchRequest.create_from_body(distrib_message)
            )

    def on_peer_connection_initialized(self, username: str, connection: PeerConnection):
        if connection.connection_type == PeerConnectionType.DISTRIBUTED:
            peer = DistributedPeer(username, connection)
            self._distributed_peers.append(peer)
            self.add_potential_child(peer)

    # Connection state changes
    def on_state_changed(self, state, connection: PeerConnection, close_reason=None):
        if state == ConnectionState.CLOSED:
            if connection.connection_type == PeerConnectionType.DISTRIBUTED:
                # Check if it was the parent that was disconnected
                parent = self._state.parent
                if parent and connection == parent.connection:
                    self.unset_parent()
                    return

                # Check if it was a child
                new_children = []
                for child in self._state.children:
                    if child.connection == connection:
                        logger.debug(f"removing child {child!r}")
                    else:
                        new_children.append(child)
                self._state.children = new_children

                # Remove from the distributed connections
                self._distributed_peers = [
                    peer for peer in self._distributed_peers
                    if peer.connection != connection
                ]

            # Check if it was a file transfer
            elif connection.connection_type == PeerConnectionType.FILE:
                self.transfer_manager.on_transfer_connection_closed(connection, close_reason=close_reason)

    def send_messages_to_children(self, *messages: Union[ProtocolMessage, bytes]):
        for child in self._state.children:
            child.connection.queue_messages(*messages)
