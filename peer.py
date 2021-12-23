import logging
import queue
from typing import List

from connection import PeerConnection, PeerConnectionType, ConnectionState
import messages
from network_manager import NetworkManager
from search import SearchResult
from state import Parent, State


logger = logging.getLogger()


class Peer:

    def __init__(self, username: str):
        self.connections: List[PeerConnection] = []
        self.username: str = username
        self.branch_level: int = None
        self.branch_root: str = None

    def reset_branch_values(self):
        self.branch_level = None
        self.branch_root = None

    def get_connections(self, typ: str):
        return self.get_connections(typ)[-1]

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

    def __init__(self, state: State, settings, network_manager: NetworkManager):
        self.state = state
        self.settings = settings
        self.network_manager = network_manager
        self.network_manager.peer_listener = self

        self.peers = {}

        self.peer_message_map = {
            messages.PeerInit.MESSAGE_ID: self.on_peer_init,
            messages.PeerPierceFirewall.MESSAGE_ID: self.on_peer_pierce_firewall,
            messages.PeerSearchReply.MESSAGE_ID: self.on_peer_search_reply
        }
        self.distributed_message_map = {
            messages.DistributedPing.MESSAGE_ID: self.on_distributed_ping,
            messages.DistributedBranchLevel.MESSAGE_ID: self.on_distributed_branch_level,
            messages.DistributedBranchRoot.MESSAGE_ID: self.on_distributed_branch_root,
            messages.DistributedSearchRequest.MESSAGE_ID: self.on_distributed_search_request
        }

    def _create_peer(self, username, connection: PeerConnection):
        """Creates a new peer object and adds it to our list of peers"""
        if username not in self.peers:
            self.peers[username] = Peer(username)

        peer = self.peers[username]

        if connection.connection_type == PeerConnectionType.PEER:
            # Need to check if we already have a connection of this type, request
            # to close that connection
            peer_connections = peer.get_connections(PeerConnectionType.PEER)
            for peer_connection in peer_connections:
                peer_connection.set_state(ConnectionState.SHOULD_CLOSE)

        peer.connections.append(connection)

    def get_peer(self, connection: PeerConnection):
        for peer in self.peers.values():
            if connection in peer.connections:
                return peer
        return None

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
        self.state.parent = parent

        # The original Windows client sends out the child depth (=0) and the
        # ParentIP
        self.network_manager.send_server_messages(
            messages.BranchLevel.create(parent.branch_level),
            messages.BranchRoot.create(parent.branch_root),
            messages.HaveNoParents.create(False),
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
        if peer.branch_level and peer.branch_root:
            if self.state.parent is None:
                self.set_parent(connection)
            else:
                connection.set_state(ConnectionState.SHOULD_CLOSE)

    def unset_parent(self):
        logger.debug(f"unset parent {self.state.parent!r}")

        self.state.parent = None

        self.network_manager.send_server_messages(
            messages.BranchLevel.create(0),
            messages.BranchRoot.create(self.settings['credentials']['username']),
            messages.HaveNoParents.create(True)
        )

    def on_unhandled_message(self, message, connection: PeerConnection):
        """Method called for messages that have no handler"""
        logger.warning(f"Don't know how to handle message {message!r}")

    def on_peer_message(self, message_data, connection: PeerConnection):
        """Method called upon receiving a message from a peer/distributed socket"""
        message_parsers = {
            PeerConnectionType.PEER: (messages.parse_peer_message, self.peer_message_map, ),
            PeerConnectionType.DISTRIBUTED: (messages.parse_distributed_message, self.distributed_message_map, )
        }

        try:
            parser_function, callback_map = message_parsers[connection.connection_type]
        except KeyError:
            raise NotImplementedError(f"No message parser implemented for {connection.connection_type}")

        # Parse the message_data
        try:
            message = parser_function(message_data)
        except Exception as exc:
            logger.exception(
                f"failed to parse peer ({connection.connection_type}) message data {message_data}")
            return

        # Run the callback
        message_callback = callback_map.get(message.MESSAGE_ID, self.on_unhandled_message)
        logger.debug(f"handling peer message of type {message.__class__.__name__!r}")
        try:
            message_callback(message, connection)
        except Exception:
            logger.exception(f"failed to handle peer message {message}")

    # Peer messages
    def on_peer_pierce_firewall(self, message, connection: PeerConnection):
        ticket = message.parse()
        logger.debug(f"PeerPierceFirewall (connection={connection}, ticket={ticket})")

        requests = list(filter(lambda r: r.ticket == ticket, self.state.connection_requests))

        if len(requests) == 0:
            logger.warning(f"received PeerPierceFirewall with unknown ticket {ticket}")
            return

        elif len(requests) == 1:
            request = requests[0]
            connection.connection_type = request.type
            self._create_peer(request.username, connection)
            logger.debug(f"handled ticket {ticket}")
            requests.remove(request)

            # I'm seeing connections that go from obfuscated to non-obfuscated
            # for some reason
            if connection.obfuscated:
                logger.debug(f"setting connection to unobfuscated : {connection}")
                connection.obfuscated = False

        else:
            logger.error(f"got multiple tickets with number {ticket} in cache")

    def on_peer_init(self, message, connection: PeerConnection):
        username, typ, token = message.parse()
        logger.info(f"PeerInit from {username}, {typ}, {token}")

        # Maybe this is misplaced?
        connection.connection_type = typ.decode('utf-8')

        self._create_peer(username, connection)

    def on_peer_search_reply(self, message, connection: PeerConnection):
        contents = message.parse()
        user, token, results, free_slots, avg_speed, queue_len, locked_results = contents
        search_result = SearchResult(
            user, token, results, free_slots, avg_speed, queue_len, locked_results)
        try:
            self.state.search_queries[token].results.append(search_result)
        except KeyError:
            # This happens if we close then re-open too quickly
            logger.warning(f"Search reply token '{token}' does not match any search query we have made")

    # Distributed messages
    def on_distributed_ping(self, message, connection: PeerConnection):
        unknown = message.parse()
        logger.info(f"Ping request with number {unknown!r}")

    def on_distributed_search_request(self, message, connection: PeerConnection):
        _, username, ticket, query = message.parse()
        logger.info(f"Search request from {username!r}, query: {query!r}")

    def on_distributed_branch_level(self, message, connection: PeerConnection):
        level = message.parse()
        logger.info(f"branch level {level!r}: {connection!r}")

        peer = self.get_peer(connection)
        peer.branch_level = level
        self._check_if_parent(peer, connection)

    def on_distributed_branch_root(self, message, connection: PeerConnection):
        root = message.parse()
        logger.info(f"branch root {root!r}: {connection!r}")

        peer = self.get_peer(connection)
        peer.branch_root = root
        self._check_if_parent(peer, connection)

    def on_connect_to_peer(self, connection: PeerConnection, username):
        self._create_peer(username, connection)

    # State changes
    def on_connecting(self, connection: PeerConnection):
        pass

    def on_closed(self, connection: PeerConnection):
        # Specific reference for parent peer
        parent = self.state.parent
        if parent and connection == parent.connection:
            parent.peer.remove_connection(connection)
            self.unset_parent()
            return

        # I wish there was a better way
        for peer in self.peers.values():
            if connection in peer.connections:
                peer.remove_connection(connection)
                break

    def on_connected(self, connection: PeerConnection):
        pass

    def on_accepted(self, connection: PeerConnection):
        logger.debug(f"accepted {connection}")
