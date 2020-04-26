import connection
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
        self.ticket_generator = ticket_generator()
        self.search_queries = {}

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
        logger.info(
            f"Logging on with username: {self.settings.username} and password: "
            f"{self.settings.password}")
        self.server_connection.messages.put(
            messages.Login.create(
                self.settings.username, self.settings.password, 157))
        while not self.state.logged_in:
            time.sleep(1)

    def search(self, query):
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.ticket_generator, query)
        self.server_connection.messages.put(
            messages.FileSearch.create(ticket, query))
        self.search_queries[ticket] = SearchQuery(ticket, query)
        return ticket

    def on_peer_message(self, message):
        message_map = {
            messages.PeerInit.MESSAGE_ID: self.on_peer_init,
            messages.PeerPierceFirewall.MESSAGE_ID: self.on_peer_pierce_firewall,
            messages.PeerSearchReply.MESSAGE_ID: self.on_peer_search_reply
        }
        message_func = message_map.get(
            message.MESSAGE_ID, self.on_unknown_message)
        message_func(message)

    def on_message(self, message):
        message_map = {
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
        message_func = message_map.get(
            message.MESSAGE_ID, self.on_unknown_message)
        message_func(message)

    def on_login(self, message):
        """
        @param message: Message object
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
            logger.error("Failed to login, reason: {reason!r}")\
        # Make setup calls
        dir_count, file_count = self.get_file_sharing_stats()
        self.server_connection.messages.put(
            messages.CheckPrivileges.create())
        # Advertise listening port including obfuscated
        self.server_connection.messages.put(
            messages.SetListenPort.create(
                self.settings.listening_port,
                self.settings.listening_port + 1))
        # Advertise listening port excluding obfuscated
        # self.server_connection.messages.put(
        #     messages.SetListenPort.create(
        #         self.settings.listening_port))
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
        # logger.debug(f"Handling ConnectToPeer message: {message!r}")
        contents = message.parse()
        logger.debug("ConnectToPeer message contents: {!r}".format(contents))
        username, typ, ip, port, token, privileged = contents
        if self.network._is_already_connected(ip):
            logger.debug(
                f"ConnectToPeer: IP address {ip} already connected, not opening "
                "a new connection")
            return
        try:
            peer_connection = connection.PeerConnection(hostname=ip, port=port)
            peer_connection.listener = self
            peer_connection.connect(self.network.selector)
        except Exception as exc:
            logger.error(f"Failed to connect to {ip}:{port}", exc_info=True)
        else:
            logger.debug(
                "Send message to {}:{} : PeerPierceFirewall"
                .format(peer_connection.hostname, peer_connection.port))
            peer_connection.messages.put(
                messages.PeerPierceFirewall.create(token))

    def on_peer_pierce_firewall(self, message):
        logger.debug(f"Handling PeerPierceFirewall message: {message!r}")
        username, typ, ip, port, token, privileged = message.parse()
        try:
            peer_connection = connection.PeerConnection(hostname=ip, port=port)
            peer_connection.listener = self
            peer_connection.connect(self.network.selector)
            # peer_connection.messages.put(
            #     messages.PeerPierceFirewall.create(token))
        except Exception as exc:
            logger.error(f"Failed to connect to {ip}:{port}", exc_info=True)

    def on_check_privileges(self, message):
        logger.debug(f"Handling CheckPrivileges message: {message!r}")
        self.state.privileges_time_left = message.parse()

    def on_net_info(self, message):
        logger.debug(f"Handling NetInfo message: {message!r}")
        net_info_list = message.parse()
        for user, ip, port in net_info_list:
            self.state.net_info[user] = (ip, port, )

    def on_room_list(self, message):
        logger.debug(f"Handling RoomList message: {message!r}")
        self.state.room_list = message.parse()

    def on_parent_min_speed(self, message):
        logger.debug(f"Handling ParentMinSpeed message: {message!r}")
        self.state.parent_min_speed = message.parse()

    def on_parent_speed_ratio(self, message):
        logger.debug(f"Handling ParentSpeedRatio message: {message!r}")
        self.state.parent_speed_ratio = message.parse()

    def on_privileged_users(self, message):
        logger.debug(f"Handling PrivilegedUsers message: {message!r}")
        self.state.privileged_users = message.parse()

    def on_wish_list_interval(self, message):
        logger.debug(f"Handling WishlistInterval message: {message!r}")
        self.state.wishlist_interval = message.parse()

    def on_add_user(self, message):
        logger.debug(f"Handling WishlistInterval message: {message!r}")
        add_user_info = message.parse()
        logger.debug(f"Add user info: {add_user_info}")

    # Peer messages
    def on_peer_init(self, message):
        logger.debug(f"Handling PeerInit message: {message!r}")
        username, typ, token = message.parse()
        logger.debug(f"PeerInit from {username}, {typ}, {token}")

    def on_peer_search_reply(self, message):
        logger.debug(f"Handling PeerSearchReply message: {message!r}")
        contents = message.parse()
        user, token, results, free_slots, avg_speed, queue_len, locked_results = contents
        search_result = SearchResult(
            user, token, results, free_slots, avg_speed, queue_len, locked_results)
        try:
            self.search_queries[token].results.append(search_result)
        except KeyError:
            logger.debug(f"Token {token} does not exist")
        # logger.debug(f"Query Results: {contents}")

    def on_unknown_message(self, message):
        """Method called for messages that have no handler"""
        logger.warning(f"Don't know how to handle message {message!r}")
