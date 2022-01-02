from dataclasses import dataclass
import enum
import logging

from connection import PeerConnection, PeerConnectionType
import messages
from scheduler import Job
from state import ConnectionRequest, State
from utils import get_stats


logger = logging.getLogger()


class UserState(enum.Enum):
    UNKNOWN = -1
    OFFLINE = 0
    AWAY = 1
    ONLINE = 2


@dataclass
class User:
    name: str
    status: int = 0
    country: str = None
    avg_speed: int = 0
    downloads: int = 0
    files: int = 0
    directories: int = 0


class ServerManager:

    def __init__(self, state: State, cache_lock, settings, network_manager):
        self.state = state
        self.cache_lock = cache_lock
        self.settings = settings
        self.network_manager = network_manager
        self.network_manager.server_listener = self

        self._ping_job = Job(5 * 60, self.send_ping)

        self.message_map = {
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
            messages.CannotConnect.MESSAGE_ID: self.on_cannot_connect,
        }

    def send_ping(self):
        self.network_manager.send_server_messages(messages.Ping.create())

    def on_server_message(self, message):
        """Method called upon receiving a message from the server socket

        This method will call L{on_unhandled_message} if the message has no
        handler method
        """
        message_func = self.message_map.get(message.MESSAGE_ID, self.on_unhandled_message)
        logger.debug(f"handling message of type {message.__class__.__name__!r}")
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
        dir_count, file_count = get_stats(self.settings['sharing']['directories'])
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")

        self.network_manager.send_server_messages(
            messages.CheckPrivileges.create(),
            messages.SetListenPort.create(
                self.settings['network']['listening_port'],
                self.settings['network']['listening_port'] + 1
            ),
            messages.SetStatus.create(UserState.ONLINE.value),
            messages.HaveNoParents.create(True),
            messages.BranchRoot.create(self.settings['credentials']['username']),
            messages.BranchLevel.create(0),
            messages.AcceptChildren.create(False),
            messages.SharedFoldersFiles.create(dir_count, file_count),
            messages.AddUser.create(self.settings['credentials']['username'])
        )

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
        logger.info(f"Added user info: {add_user_info}")
        name, exists, status, avg_speed, downloads, files, directories, country = add_user_info
        if exists:
            user = User(
                name=name,
                status=status,
                avg_speed=avg_speed,
                downloads=downloads,
                files=files,
                directories=directories,
                country=country
            )

    def on_connect_to_peer(self, message):
        contents = message.parse()
        logger.info("ConnectToPeer message contents: {!r}".format(contents))
        username, typ, ip, port, ticket, privileged, unknown, obfuscated_port = contents

        peer_connection = PeerConnection(
            hostname=ip,
            port=port,
            connection_type=typ
        )
        peer_connection.messages.put(
            messages.PeerPierceFirewall.create(ticket))
        with self.cache_lock:
            self.state.connection_requests[ticket] = ConnectionRequest(
                ticket=ticket,
                username=username,
                ip=ip,
                port=port,
                typ=typ,
                connection=peer_connection,
                is_requested_by_us=False
            )
        self.network_manager.connect_to_peer(peer_connection, username)

    def on_net_info(self, message):
        net_info_list = message.parse()

        for idx, (username, ip, port) in enumerate(net_info_list, 1):
            ticket = next(self.state.ticket_generator)
            logger.info(f"netinfo user {idx}: {username!r} : {ip}:{port} (ticket={ticket})")
            with self.cache_lock:
                self.state.connection_requests[ticket] = ConnectionRequest(
                    ticket=ticket,
                    username=username,
                    ip=ip,
                    port=port,
                    typ=PeerConnectionType.DISTRIBUTED,
                    connection=None,
                    is_requested_by_us=True
                )
            # self.network_manager.send_server_messages(
            #     messages.ConnectToPeer.create(
            #         ticket,
            #         username,
            #         PeerConnectionType.DISTRIBUTED
            #     )
            # )

            peer_connection = PeerConnection(
                hostname=ip,
                port=port,
                connection_type=PeerConnectionType.DISTRIBUTED
            )
            self.network_manager.connect_to_peer(peer_connection, username)
            peer_connection.messages.put(
                messages.PeerInit.create(
                    self.settings['credentials']['username'],
                    PeerConnectionType.DISTRIBUTED,
                    ticket
                )
            )

    def on_cannot_connect(self, message):
        ticket, username = message.parse()
        logger.debug(f"got CannotConnect: {ticket} , {username}")
        with self.cache_lock:
            try:
                self.state.connection_requests.pop(ticket)
            except KeyError:
                logger.warning(
                    f"CannotConnect : ticket {ticket} (username={username}) was not found in cache")
            else:
                logger.debug(f"CannotConnect : removed ticket {ticket} (username={username}) from cache")

    def on_unhandled_message(self, message):
        """Method called for messages that have no handler"""
        logger.warning(f"don't know how to handle message {message!r}")

    # Connection state listeners
    def on_connecting(self):
        pass

    def on_connected(self):
        self.state.scheduler.add_job(self._ping_job)

    def on_closed(self, reason=None):
        self.state.scheduler.remove(self._ping_job)
