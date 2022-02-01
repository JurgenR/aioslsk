from dataclasses import dataclass
import enum
import logging
from typing import List

from connection import PeerConnectionType, ConnectionState
from filemanager import FileManager
from listeners import on_message
from messages import (
    AcceptChildren,
    AddUser,
    BranchRoot,
    BranchLevel,
    CannotConnect,
    CheckPrivileges,
    ConnectToPeer,
    GetPeerAddress,
    HaveNoParents,
    Login,
    NetInfo,
    ParentMinSpeed,
    ParentSpeedRatio,
    Ping,
    PrivilegedUsers,
    RoomList,
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
    WishlistInterval,
)
from network_manager import NetworkManager
from scheduler import Job
from state import State


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

    def __init__(self, state: State, settings, file_manager: FileManager, network_manager: NetworkManager):
        self.state: State = state
        self.settings = settings
        self.file_manager: FileManager = file_manager
        self.network_manager: NetworkManager = network_manager
        self.network_manager.server_listener = self

        self._ping_job = Job(5 * 60, self.send_ping)
        self.users: List[User] = []

    def send_ping(self):
        self.network_manager.send_server_messages(Ping.create())

    def get_user(self, name: str):
        for user in self.users:
            if user.name == name:
                return user
        raise LookupError(f"user with name {name!r} not found in list of users")

    @on_message(Login)
    def on_login(self, message):
        """Called when a response is received to a logon call"""
        login_values = message.parse()
        # First value indicates success
        if login_values[0]:
            self.state.logged_in = True
            success, greet, ip, md5hash, _ = login_values
            logger.info(
                f"Successfully logged on. Greeting message: {greet!r}. Your IP: {ip!r}")
        else:
            success, reason = login_values
            logger.error(f"Failed to login, reason: {reason!r}")

        # Make setup calls
        dir_count, file_count = self.file_manager.get_stats()
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")

        self.network_manager.send_server_messages(
            CheckPrivileges.create(),
            SetListenPort.create(
                self.settings['network']['listening_port'],
                self.settings['network']['listening_port'] + 1
            ),
            SetStatus.create(UserState.ONLINE.value),
            HaveNoParents.create(True),
            BranchRoot.create(self.settings['credentials']['username']),
            BranchLevel.create(0),
            AcceptChildren.create(False),
            SharedFoldersFiles.create(dir_count, file_count),
            AddUser.create(self.settings['credentials']['username'])
        )

    # State related messages
    @on_message(CheckPrivileges)
    def on_check_privileges(self, message):
        self.state.privileges_time_left = message.parse()

    @on_message(RoomList)
    def on_room_list(self, message):
        self.state.room_list = message.parse()

    @on_message(ParentMinSpeed)
    def on_parent_min_speed(self, message):
        self.state.parent_min_speed = message.parse()

    @on_message(ParentSpeedRatio)
    def on_parent_speed_ratio(self, message):
        self.state.parent_speed_ratio = message.parse()

    @on_message(PrivilegedUsers)
    def on_privileged_users(self, message):
        self.state.privileged_users = message.parse()

    @on_message(WishlistInterval)
    def on_wish_list_interval(self, message):
        self.state.wishlist_interval = message.parse()

    @on_message(AddUser)
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
            try:
                user = self.get_user(name)
            except LookupError:
                self.users.append(user)
            else:
                self.users.pop(user)
                self.users.append(user)

    @on_message(NetInfo)
    def on_net_info(self, message):
        net_info_list = message.parse()

        if not self.settings['debug']['search_for_parent']:
            logger.debug(f"ignoring NetInfo message : searching for parent is disabled")
            return

        for idx, (username, ip, port) in enumerate(net_info_list, 1):
            ticket = next(self.state.ticket_generator)
            logger.info(f"netinfo user {idx}: {username!r} : {ip}:{port} (ticket={ticket})")

            self.network_manager.init_peer_connection(
                ticket,
                username,
                PeerConnectionType.DISTRIBUTED,
                ip=ip,
                port=port
            )

    # Connection state listeners
    def on_state_changed(self, state, connection, close_reason=None):
        if state == ConnectionState.CONNECTED:
            self.state.scheduler.add_job(self._ping_job)

        elif state == ConnectionState.CLOSED:
            self.state.scheduler.remove(self._ping_job)
