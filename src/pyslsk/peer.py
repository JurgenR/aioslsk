import logging
from typing import Dict, List

from .connection import (
    PeerConnection,
    PeerConnectionType,
    ConnectionState
)
from .events import on_message, EventBus
from .filemanager import convert_to_results, FileManager
from .messages import (
    pack_int,
    parse_distributed_message,
    BranchLevel,
    BranchRoot,
    HaveNoParents,
    DistributedBranchLevel,
    DistributedBranchRoot,
    DistributedSearchRequest,
    DistributedServerSearchRequest,
    PeerPlaceInQueueReply,
    PeerPlaceInQueueRequest,
    PeerSearchReply,
    PeerTransferReply,
    PeerTransferRequest,
    PeerTransferQueue,
    PeerTransferQueueFailed,
    PeerUploadFailed,
    PeerUserInfoRequest,
    PeerUserInfoReply,
)
from .network_manager import NetworkManager
from .search import ReceivedSearch, SearchResult
from .state import Parent, State
from .transfer import Transfer, TransferDirection, TransferManager


logger = logging.getLogger()


class Peer:

    def __init__(self, username: str):
        self.connections: List[PeerConnection] = []
        self.username: str = username

        self.is_potential_parent: bool = False

        self.branch_level: int = None
        self.branch_root: str = None

    def reset_branch_values(self):
        self.branch_level = None
        self.branch_root = None

    def get_connections(self, typ: str):
        return list(filter(lambda c: c.connection_type == typ, self.connections))

    def remove_connection(self, connection):
        self.connections.remove(connection)

    def __repr__(self):
        return (
            f"Peer(username={self.username!r}, "
            f"branch_root={self.branch_root!r}, branch_level={self.branch_level}, "
            f"connections={self.connections!r})"
        )


class PeerManager:

    def __init__(self, state: State, settings, event_bus: EventBus, file_manager: FileManager, transfer_manager: TransferManager, network_manager: NetworkManager):
        self._state: State = state
        self._settings = settings
        self._event_bus: EventBus = event_bus
        self.file_manager: FileManager = file_manager
        self.transfer_manager: TransferManager = transfer_manager
        self.network_manager: NetworkManager = network_manager
        self.network_manager.peer_listener = self

        self.peers: Dict[str, Peer] = {}

    def download(self, username: str, filename: str) -> Transfer:
        """Initiate downloading of a file"""
        logger.info(f"queueing download from {username} : {filename}")
        transfer = Transfer(
            username=username,
            filename=filename,
            direction=TransferDirection.DOWNLOAD
        )
        self.transfer_manager.queue_transfer(transfer)

        return transfer

    def create_peer(self, username: str, connection: PeerConnection) -> Peer:
        """Creates a new peer object and adds it to our list of peers, if a peer
        already exists with the given L{username} the connection will be added
        to the existing peer

        @rtype: L{Peer}
        @return: created/updated L{Peer} object
        """
        if username not in self.peers:
            self.peers[username] = Peer(username)

        peer = self.peers[username]

        # if connection.connection_type == PeerConnectionType.PEER:
        #     # Need to check if we already have a connection of this type, request
        #     # to close that connection
        #     # peer_connections = peer.get_connections(PeerConnectionType.PEER)
        #     for peer_connection in peer_connections:
        #         peer_connection.set_state(ConnectionState.SHOULD_CLOSE)

        peer.connections.append(connection)
        return peer

    def get_peer(self, connection: PeerConnection) -> Peer:
        for peer in self.peers.values():
            if connection in peer.connections:
                return peer

    def set_parent(self, parent_connection: PeerConnection):
        peer = self.get_peer(parent_connection)
        if peer is None:
            logger.error(
                f"parent connection was not found in the list of peers (connection={parent_connection!r})")
            return

        logger.info(f"set parent {peer.username!r}: {parent_connection!r}")

        parent = Parent(
            peer.branch_level + 1,
            peer.branch_root,
            peer,
            parent_connection
        )
        self._state.parent = parent

        logger.info(f"notifying server of our parent : level={parent.branch_level} root={parent.branch_root}")
        # The original Windows client sends out the child depth (=0) and the
        # ParentIP
        self.network_manager.send_server_messages(
            BranchLevel.create(parent.branch_level),
            BranchRoot.create(parent.branch_root),
            HaveNoParents.create(False)
        )

        # Remove all other distributed connections
        # Even the distributed connections from the parent should be removed
        for potential_parent_peer in self.peers.values():
            connections = potential_parent_peer.get_connections(PeerConnectionType.DISTRIBUTED)
            # Reset branch values
            # NOTE: I saw a situation where a parent stopped sending us anything
            # for a while. Then suddenly readvertised its branch level, we
            # never unset branch root so it kind of messed up because we already
            # had a value for this peer and passed through the _check_if_parent.
            # Therefor we also unset the branch values for the parent itself
            for connection in connections:
                if connection != parent_connection:
                    connection.set_state(ConnectionState.SHOULD_CLOSE)

                    # TODO: There might be a possibility that we still read
                    # some data before closing the connections
                    potential_parent_peer.reset_branch_values()

    def _check_if_parent(self, peer, connection):
        """Called after BranchRoot or BranchLevel, checks if all information is
        complete for this peer/connection to become a parent and makes it a
        parent if we don't have one, otherwise just close the connection.
        """
        # Explicit None checks because we can get 0 as branch level
        if peer.branch_level is not None and peer.branch_root is not None:
            if self._state.parent is None:
                self.set_parent(connection)
            else:
                connection.set_state(ConnectionState.SHOULD_CLOSE)
                peer = self.get_peer(connection)
                if peer is not None:
                    peer.reset_branch_values()

    def unset_parent(self):
        logger.debug(f"unset parent {self._state.parent!r}")

        self._state.parent = None

        self.network_manager.send_server_messages(
            BranchLevel.create(0),
            BranchRoot.create(self._settings['credentials']['username']),
            HaveNoParents.create(True)
        )

    # Transfer

    @on_message(PeerTransferQueue)
    def on_peer_transfer_queue(self, message, connection: PeerConnection):
        """Initial message received in the transfer process. The peer is
        requesting to download a file from us here. The proper response is to
        ignore it.
        """
        filename = message.parse()
        logger.info(f"PeerTransferQueue : {filename}")

        peer = self.get_peer(connection)

        transfer_ticket = next(self._state.ticket_generator)
        transfer = Transfer(
            username=peer.username,
            filename=filename,
            ticket=transfer_ticket,
            direction=TransferDirection.UPLOAD
        )

        try:
            self.file_manager.get_shared_item(filename.decode('utf-8'))
            transfer.filesize = self.file_manager.get_filesize(filename.decode('utf-8'))
        except LookupError:
            self.transfer_manager.queue_transfer(transfer, state=None)
            transfer.fail(reason="File not shared.")
            connection.queue_message(
                PeerTransferQueueFailed.create(filename, transfer.fail_reason)
            )
        else:
            self.transfer_manager.queue_transfer(transfer)

    @on_message(PeerTransferRequest)
    def on_peer_transfer_request(self, message, connection: PeerConnection):
        """The PeerTransferRequest message is sent when the peer is ready to
        transfer the file. The message contains more information about the
        transfer.
        """
        direction, ticket, filename, filesize = message.parse()
        logger.info(f"PeerTransferRequest : {filename} {direction} (filesize={filesize}, ticket={ticket})")

        try:
            transfer = self.transfer_manager.get_transfer(filename, TransferDirection(direction))
        except LookupError:
            logger.error("PeerTransferRequest : unknown transfer")
            # Should we somehow tell the peer we want to cancel?
            return

        transfer.ticket = ticket
        transfer.filesize = filesize

        logger.debug(f"PeerTransferRequest : sending PeerTransferReply (ticket={ticket})")
        connection.queue_message(
            PeerTransferReply.create(ticket, True)
        )

    @on_message(PeerTransferReply)
    def on_peer_transfer_reply(self, message, connection: PeerConnection):
        """The PeerTransferReply is a reponse to PeerTransferRequest"""
        ticket, allowed, filesize, reason = message.parse()
        logger.info(f"PeerTransferReply : allowed={allowed}, filesize={filesize}, reason={reason!r} (ticket={ticket})")

        transfer = self.transfer_manager.get_transfer_by_ticket(ticket)
        if not allowed:
            transfer.fail(reason=reason)
            return

        connection_ticket = next(self._state.ticket_generator)
        self.network_manager.init_peer_connection(
            connection_ticket,
            transfer.username,
            typ=PeerConnectionType.FILE,
            transfer=transfer,
            messages=[pack_int(ticket)]
        )

    @on_message(PeerPlaceInQueueRequest)
    def on_peer_place_in_queue_request(self, message, connection: PeerConnection):
        contents = message.parse()
        logger.info(f"{message.__class__.__name__}: {contents}")

    @on_message(PeerPlaceInQueueReply)
    def on_peer_place_in_queue_reply(self, message, connection: PeerConnection):
        contents = message.parse()
        logger.info(f"{message.__class__.__name__}: {contents}")

    @on_message(PeerUploadFailed)
    def on_peer_upload_failed(self, message, connection: PeerConnection):
        filename = message.parse()
        logger.info(f"PeerUploadFailed : upload failed for {filename}")
        peer = self.get_peer(connection)
        if peer is not None:
            try:
                transfer = self.transfer_manager.get_transfer_by_connection(connection)
            except LookupError:
                logger.error(f"PeerUploadFailed : could not find transfer for {filename} from {peer.username}")
            else:
                transfer.fail()
        else:
            logger.error(f"PeerUploadFailed : no peer for {peer.username}")

    @on_message(PeerTransferQueueFailed)
    def on_peer_transfer_queue_failed(self, message, connection: PeerConnection):
        filename, reason = message.parse()
        logger.info(f"PeerTransferQueueFailed : upload failed for {filename}, reason={reason}")

        peer = self.get_peer(connection)
        if peer is not None:
            try:
                transfer = self.transfer_manager.get_transfer_by_connection(connection)
            except LookupError:
                logger.error(f"PeerTransferQueueFailed : could not find transfer for {filename} from {peer.username}")
            else:
                transfer.fail(reason=reason)
        else:
            logger.error(f"PeerTransferQueueFailed : no peer for {peer.username}")

    # Peer messages

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
            self._state.search_queries[ticket].results.append(search_result)
        except KeyError:
            logger.warning(f"search reply ticket '{ticket}' does not match any search query")

    @on_message(PeerUserInfoRequest)
    def on_peer_user_info_request(self, message, connection: PeerConnection):
        pass
        # connection.queue_message(
        #     PeerUserInfoReply.create()
        # )

    # Distributed messages

    @on_message(DistributedSearchRequest)
    def on_distributed_search_request(self, message, connection: PeerConnection):
        _, username, search_ticket, query = message.parse()
        logger.info(f"search request from {username!r}, query: {query!r}")
        results = self.file_manager.query(query.decode('utf-8'))

        self._state.received_searches.append(
            ReceivedSearch(username=username, query=query, matched_files=len(results))
        )

        if len(results) == 0:
            return

        logger.debug(f"got {len(results)} results for query {query}")

        connection_ticket = next(self._state.ticket_generator)
        self.network_manager.init_peer_connection(
            connection_ticket,
            username,
            PeerConnectionType.PEER,
            messages=[
                PeerSearchReply.create(
                    self._settings['credentials']['username'],
                    search_ticket,
                    convert_to_results(results),
                    self.transfer_manager.has_slots_free(),
                    int(self.transfer_manager.get_average_upload_speed()),
                    0 # Queue size
                )
            ]
        )

    @on_message(DistributedBranchLevel)
    def on_distributed_branch_level(self, message, connection: PeerConnection):
        level = message.parse()
        logger.info(f"branch level {level!r}: {connection!r}")

        peer = self.get_peer(connection)
        peer.branch_level = level
        # Branch root is not always sent in case the peer advertises branch
        # level 0 because he himself is the root
        if level == 0:
            peer.branch_root = peer.username
        self._check_if_parent(peer, connection)

    @on_message(DistributedBranchRoot)
    def on_distributed_branch_root(self, message, connection: PeerConnection):
        root = message.parse()
        logger.info(f"branch root {root!r}: {connection!r}")

        peer = self.get_peer(connection)
        peer.branch_root = root
        self._check_if_parent(peer, connection)

    @on_message(DistributedServerSearchRequest)
    def on_distributed_server_search_request(self, message, connection: PeerConnection):
        distrib_code, distrib_message = message.parse()
        logger.info(f"distributed server search request: {distrib_code} {distrib_message}")

        try:
            parsed_message = parse_distributed_message(distrib_message)
            if isinstance(message, DistributedSearchRequest):
                self.on_distributed_search_request(parsed_message, connection)
            else:
                logger.warning(f"no handling for server search request with code {distrib_code}")
        except Exception:
            logger.exception("failed to parse server search request")

        # TODO: Pass on to children

    # Connection state changes

    def on_state_changed(self, state, connection, close_reason=None):
        if state == ConnectionState.CLOSED:
            parent = self._state.parent
            if parent and connection == parent.connection:
                parent.peer.remove_connection(connection)
                self.unset_parent()
                return

            if connection.connection_type == PeerConnectionType.FILE:
                self.transfer_manager.on_transfer_connection_closed(connection, close_reason=close_reason)

            # Remove the peer connection
            for peer in self.peers.values():
                if connection in peer.connections:
                    peer.remove_connection(connection)
                    break
