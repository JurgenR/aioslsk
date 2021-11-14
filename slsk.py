from connection import (
    PeerConnection,
    PeerConnectionType,
)
import messages
import state
from search import SearchQuery, SearchResult
from utils import ticket_generator, get_directories_absolute_paths, get_file_count

import logging
import time

logger = logging.getLogger()


class SoulSeek:

    def __init__(self, network, server_connection, settings):
        self.network = network
        self.server_connection = server_connection
        self.settings = settings
        self.state = state.State()
        self.peers = []
        self.ticket_generator = ticket_generator()
        self.search_queries = {}

        self._create_message_mappings()

    def _create_message_mappings(self):
        self._server_message_map = {
            messages.AddUser.MESSAGE_ID: self.on_add_user,
            messages.CheckPrivileges.MESSAGE_ID: self.on_check_privileges,
            messages.ConnectToPeer.MESSAGE_ID: self.on_connect_to_peer,
            messages.Login.MESSAGE_ID: self.on_login,
            messages.NetInfo.MESSAGE_ID: self.on_net_info,
            messages.ParentMinSpeed.MESSAGE_ID: self.on_parent_min_speed,
            messages.ParentSpeedRatio.MESSAGE_ID: self.on_parent_speed_ratio,
            messages.PrivilegedUsers.MESSAGE_ID: self.on_privileged_users,
            messages.RoomList.MESSAGE_ID: self.on_room_list,
            messages.WishlistInterval.MESSAGE_ID: self.on_wish_list_interval,
        }
        self._peer_message_map = {
            messages.PeerInit.MESSAGE_ID: self.on_peer_init,
            messages.PeerPierceFirewall.MESSAGE_ID: self.on_peer_pierce_firewall,
            messages.PeerSearchReply.MESSAGE_ID: self.on_peer_search_reply
        }
        self._distributed_message_map = {
            messages.DistributedPing.MESSAGE_ID: self.on_distributed_ping,
            messages.DistributedBranchLevel.MESSAGE_ID: self.on_distributed_branch_level,
            messages.DistributedBranchRoot.MESSAGE_ID: self.on_distributed_branch_root,
            messages.DistributedSearchRequest.MESSAGE_ID: self.on_distributed_search_request
        }

    def get_file_sharing_stats(self):
        """Returns the amount of files and directories shared"""
        directories = get_directories_absolute_paths(self.settings.directories)
        count = 0
        for directory in directories:
            count += get_file_count(directory)
        return len(directories), count

    def login(self):
        """Perform a login request with the username and password found in
        L{self.settings} and waits until L{self.state.logged_in} is set.
        """
        username = self.settings.username
        password = self.settings.password
        logger.info(f"Logging on with credentials: {username}:{password}")
        self.server_connection.messages.put(
            messages.Login.create(username, password, 157)
        )
        while not self.state.logged_in:
            time.sleep(1)

    def search(self, query):
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.ticket_generator)
        self.server_connection.messages.put(
            messages.FileSearch.create(ticket, query))
        self.search_queries[ticket] = SearchQuery(ticket, query)
        return ticket

    def on_peer_message(self, message, connection=None):
        """Method called upon receiving a message from a peer/distributed socket"""
        if connection.connection_type == PeerConnectionType.PEER:
            message_map = self._peer_message_map
        else:
            # Distributed
            message_map = self._distributed_message_map

        message_func = message_map.get(message.MESSAGE_ID, self.on_unknown_message)

        logger.debug(f"Handling peer message {message!r}")
        message_func(message, connection=connection)

    def on_message(self, message):
        """Method called upon receiving a message from the server socket

        This method will call L{on_unknown_message} if the message has no
        handler method
        """
        message_func = self._server_message_map.get(smessage.MESSAGE_ID, self.on_unknown_message)
        logger.debug(f"Handling message {message!r}")
        message_func(message)

    def on_login(self, message):
        """Called when a response is received to a logon call

        @param message: L{Message} object
        """
        login_values = message.parse()
        # The first value should be 0 or 1 depending on failure or succes
        if login_values[0] == 1:
            self.state.logged_in = True
            result, greet, ip, md5hash, unknown = login_values
            logger.info(
                f"Successfully logged on. Greeting message: {greet!r}. Your IP: {ip!r}")
        else:
            result, reason = login_values
            logger.error("Failed to login, reason: {reason!r}")

        # Make setup calls
        dir_count, file_count = self.get_file_sharing_stats()
        self.server_connection.messages.put(
            messages.CheckPrivileges.create())
        # Advertise listening port including obfuscated
        self.server_connection.messages.put(
            messages.SetListenPort.create(
                self.settings.listening_port,
                self.settings.listening_port + 1
            )
        )
        # Advertise listening port excluding obfuscated
        # self.server_connection.messages.put(
        #     messages.SetListenPort.create(
        #         self.settings.listening_port
        #     )
        # )
        self.server_connection.messages.put(
            messages.SetStatus.create(2)) # Available
        self.server_connection.messages.put(
            messages.HaveNoParents.create(True))
        self.server_connection.messages.put(
            messages.BranchRoot.create(self.settings.username))
        self.server_connection.messages.put(
            messages.BranchLevel.create(0))
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")
        # self.server_connection.messages.put(
        #     messages.SharedFoldersFiles.create(dir_count, file_count))
        self.server_connection.messages.put(
            messages.SharedFoldersFiles.create(5, 1000))
        # GetUserStats on self? message ID 36
        self.server_connection.messages.put(
            messages.AddUser.create(self.settings.username))
        self.server_connection.messages.put(
            messages.AcceptChildren.create(True))

    def on_connect_to_peer(self, message):
        contents = message.parse()
        logger.info("ConnectToPeer message contents: {!r}".format(contents))
        username, typ, ip, port, token, privileged = contents

        if self.network._is_already_connected(ip):
            logger.debug(
                f"ConnectToPeer: IP address {ip} already connected, not opening "
                "a new connection")
            return

        peer_connection = PeerConnection(hostname=ip, port=port, listener=self)
        peer_connection.listener = self
        peer_connection.connect(self.network.selector)
        peer_connection.messages.put(
            messages.PeerPierceFirewall.create(token))

    def on_peer_pierce_firewall(self, message, connection=None):
        username, typ, ip, port, token, privileged = message.parse()
        peer_connection = PeerConnection(
            hostname=ip, port=port, listener=self, connection_type=typ.decode('utf-8'))
        peer_connection.connect(self.network.selector)

    def on_net_info(self, message):
        net_info_list = message.parse()

        idx = 1
        for username, ip, port in net_info_list:
            logger.info(f"NetInfo user {idx}: {username!r} : {ip}:{port}")
            idx += 1
            self.state.net_info[username] = (ip, port, )
            peer_connection = PeerConnection(
                hostname=ip, port=port,
                listener=self,
                connection_type=PeerConnectionType.DISTRIBUTED
            )
            # peer_connection.connect(self.network.selector)
            # self.server_connection.messages.put(
            #     messages.ConnectToPeer.create(
            #         next(self.ticket_generator),
            #         username,
            #         PeerConnectionType.DISTRIBUTED
            #     )
            # )

    # State related messages
    def on_check_privileges(self, message):
        self.state.privileges_time_left = message.parse()

    def on_room_list(self, message):
        self.state.room_list = message.parse()

    def on_parent_min_speed(self, message):
        self.state.parent_min_speed = message.parse()

    def on_parent_speed_ratio(self, message):
        self.state.parent_speed_ratio = message.parse()

    def on_privileged_users(self, message):
        self.state.privileged_users = message.parse()

    def on_wish_list_interval(self, message):
        self.state.wishlist_interval = message.parse()

    def on_add_user(self, message):
        add_user_info = message.parse()
        logger.info(f"Add user info: {add_user_info}")

    # Peer messages
    def on_peer_init(self, message, connection=None):
        username, typ, token = message.parse()
        logger.info(f"PeerInit from {username}, {typ}, {token}")
        connection.connection_type = typ.decode('utf-8')

    def on_peer_search_reply(self, message, connection=None):
        contents = message.parse()
        user, token, results, free_slots, avg_speed, queue_len, locked_results = contents
        search_result = SearchResult(
            user, token, results, free_slots, avg_speed, queue_len, locked_results)
        try:
            self.search_queries[token].results.append(search_result)
        except KeyError:
            # This happens if we close then re-open too quickly
            logger.warning(f"Search reply token '{token}' does not match any search query we have made")

    # Distributed messages
    def on_distributed_ping(self, message, connection=None):
        unknown = message.parse()
        logger.info(f"Ping request with number {unknown!r}")

    def on_distributed_search_request(self, message, connection=None):
        _, username, ticket, query = message.parse()
        logger.info(f"Search request from {username!r}, query: {query!r}")

    def on_distributed_branch_level(self, message, connection=None):
        level = message.parse()
        logger.info(f"Branch level {level!r}")

    def on_distributed_branch_root(self, message, connection=None):
        root = message.parse()
        logger.info(f"Branch root {root!r}")

    def on_unknown_message(self, message, connection=None):
        """Method called for messages that have no handler"""
        logger.warning(f"Don't know how to handle message {message!r}")
