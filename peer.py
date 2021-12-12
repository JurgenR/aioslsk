import logging
import queue

from connection import PeerConnection, PeerConnectionType, ConnectionState
import messages
from network_manager import NetworkManager
from search import SearchResult
from state import State


logger = logging.getLogger()


class Peer:

    def __init__(self, username):
        self.connections = []
        self.username = username
        self.messages = queue.Queue()
        self.is_parent = False
        self.branch_level = None
        self.branch_root = None

    def get_connections(self, typ: str):
        return self.get_connections(typ)[-1]

    def get_connections(self, typ: str):
        return list(filter(lambda c: c.connection_type == typ, self.connections))

    def remove_connection(self, connection):
        self.connections.pop(connection)


class PeerManager:

    def __init__(self, state: State, network_manager: NetworkManager):
        self.state = state
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

    def _create_peer(self, username, connection):
        """Creates a new peer object and adds it to our list of peers"""
        peer = self.peers.get(
            username,
            Peer(username)
        )
        if connection.connection_type == PeerConnectionType.PEER:
            # Need to check if we already have a connection of this type, request
            # to close that connection
            peer_connections = peer.get_connections(PeerConnectionType.PEER)
            for peer_connection in peer_connections:
                peer.remove_connection(peer_connection)
                peer_connection.state = ConnectionState.SHOULD_CLOSE

        peer.connections.append(connection)

    def on_unknown_message(self, message, connection):
        """Method called for messages that have no handler"""
        logger.warning(f"Don't know how to handle message {message!r}")

    def on_peer_message(self, message, connection):
        """Method called upon receiving a message from a peer/distributed socket"""

        message_map = {
            PeerConnectionType.PEER: self.peer_message_map,
            PeerConnectionType.DISTRIBUTED: self.distributed_message_map
        }.get(connection.connection_type)

        message_func = message_map.get(message.MESSAGE_ID, self.on_unknown_message)

        logger.debug(f"Handling peer message {message!r}")
        message_func(message, connection)

    # Peer messages
    def on_peer_pierce_firewall(self, message, connection):
        username, typ, ip, port, token, privileged = message.parse()

        connection.connection_type = typ.decode('utf-8')

        self._create_peer(username, connection)

    def on_peer_init(self, message, connection):
        username, typ, token = message.parse()
        logger.info(f"PeerInit from {username}, {typ}, {token}")

        # Maybe this is misplaced?
        connection.connection_type = typ.decode('utf-8')

        self._create_peer(username, connection)

    def on_peer_search_reply(self, message, connection):
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
    def on_distributed_ping(self, message, connection):
        unknown = message.parse()
        logger.info(f"Ping request with number {unknown!r}")

    def on_distributed_search_request(self, message, connection):
        _, username, ticket, query = message.parse()
        logger.info(f"Search request from {username!r}, query: {query!r}")

    def on_distributed_branch_level(self, message, connection):
        level = message.parse()
        logger.info(f"Branch level {level!r}")

    def on_distributed_branch_root(self, message, connection):
        root = message.parse()
        logger.info(f"Branch root {root!r}")

    def on_peer_disconnected(self, connection):
        for peer in self.peers.values():
            if connection in peer.connections:
                peer.connections.remove(connection)
                break

    def on_peer_connected(self, connection):
        pass

    def on_peer_accepted(self, connection):
        pass
