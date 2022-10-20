import copy
import logging
import time

from .connection import ConnectionState, PeerConnectionType, ServerConnection
from .events import (
    build_message_map,
    on_message,
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
    LoginEvent,
    PrivateMessageEvent,
    RoomMessageEvent,
    RoomListEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    ServerDisconnectedEvent,
    ServerMessageEvent,
    UserAddEvent,
    UserJoinedRoomEvent,
    UserJoinedPrivateRoomEvent,
    UserLeftRoomEvent,
    UserLeftPrivateRoomEvent,
    UserStatsEvent,
    UserStatusEvent,
)
from .filemanager import FileManager
from .messages import (
    AcceptChildren,
    AddPrivilegedUser,
    AddUser,
    BranchRoot,
    BranchLevel,
    PrivateRoomAddUser,
    PrivateRoomUsers,
    ChatRoomMessage,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    ChatRoomTickers,
    ChatRoomTickerAdd,
    ChatRoomTickerRemove,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    CheckPrivileges,
    DistributedAliveInterval,
    GetUserStatus,
    GetUserStats,
    HaveNoParent,
    Login,
    MinParentsInCache,
    NetInfo,
    ParentMinSpeed,
    ParentSpeedRatio,
    Ping,
    PrivateRoomAdded,
    PrivateRoomOperators,
    PrivateRoomOperatorAdded,
    PrivateRoomOperatorRemoved,
    PrivateRoomAddOperator,
    PrivateRoomRemoveOperator,
    PrivateRoomRemoved,
    PrivateRoomToggle,
    PrivateRoomDropMembership,
    PrivateRoomDropOwnership,
    PrivilegedUsers,
    RemoveUser,
    RoomList,
    SearchInactivityTimeout,
    ServerSearchRequest,
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
    WishlistInterval,
    DistributedServerSearchRequest,
)
from .model import ChatMessage, RoomMessage, UserStatus
from .network import Network
from .scheduler import Job
from .settings import Settings
from .state import State


logger = logging.getLogger()


LOGIN_TIMEOUT = 30


class ServerManager:

    def __init__(self, state: State, settings: Settings, event_bus: EventBus, internal_event_bus: InternalEventBus, file_manager: FileManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self.file_manager: FileManager = file_manager
        self.network: Network = network

        self._ping_job = Job(5 * 60, self.send_ping)
        self._report_shares_job = Job(30, self.report_shares)

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(
            ServerMessageEvent, self._on_server_message)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    @property
    def connection_state(self) -> ConnectionState:
        return self.network.server.state

    def send_ping(self):
        """Send ping to the server"""
        self.network.send_server_messages(Ping.create())

    def report_shares(self):
        """Reports the shares amount to the server"""
        dir_count, file_count = self.file_manager.get_stats()
        logger.debug(f"reporting shares to the server (dirs={dir_count}, file_count={file_count})")
        self.network.send_server_messages(
            SharedFoldersFiles.create(dir_count, file_count)
        )

    def login(self, username: str, password: str, version: int = 157):
        logger.info(f"sending request to login: username={username}, password={password}")
        self.network.send_server_messages(
            Login.create(username, password, version)
        )

    def add_user(self, username: str):
        logger.info(f"adding user {username}")
        self.network.send_server_messages(
            AddUser.create(username)
        )

    def remove_user(self, username: str):
        logger.info(f"removing user {username}")
        self.network.send_server_messages(
            RemoveUser.create(username)
        )

    def get_user_stats(self, username: str):
        logger.info(f"getting user stats {username}")
        self.network.send_server_messages(
            GetUserStats.create(username)
        )

    def get_user_status(self, username: str):
        logger.info(f"getting user status {username}")
        self.network.send_server_messages(
            GetUserStatus.create(username)
        )

    def get_room_list(self):
        logger.info("sending request for room list")
        self.network.send_server_messages(RoomList.create())

    def join_room(self, name: str):
        logger.info(f"sending request to join room with name {name}")
        self.network.send_server_messages(
            ChatJoinRoom.create(name)
        )

    def leave_room(self, name: str):
        logger.info(f"sending request to leave room with name {name}")
        self.network.send_server_messages(
            ChatLeaveRoom.create(name)
        )

    def send_private_message(self, username: str, message: str):
        self.network.send_server_messages(
            ChatPrivateMessage.create(username, message)
        )

    def send_room_message(self, room_name: str, message: str):
        self.network.send_server_messages(
            ChatRoomMessage.create(room_name, message)
        )

    def drop_private_room_ownership(self, room_name: str):
        self.network.send_server_messages(
            PrivateRoomDropOwnership.create(room_name)
        )

    def drop_private_room_membership(self, room_name: str):
        self.network.send_server_messages(
            PrivateRoomDropMembership.create(room_name)
        )

    @on_message(Login)
    def _on_login(self, message, connection):
        """Called when a response is received to a logon call"""
        login_values = message.parse()
        # First value indicates success
        if login_values[0]:
            self._state.logged_in = True
            success, greet, ip, md5hash, _ = login_values
            logger.info(
                f"Successfully logged on. Greeting message: {greet!r}. Your IP: {ip!r}")
        else:
            success, reason = login_values
            logger.error(f"Failed to login, reason: {reason!r}")

        # Make setup calls
        dir_count, file_count = self.file_manager.get_stats()
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")

        self.network.send_server_messages(
            CheckPrivileges.create(),
            SetListenPort.create(
                self._settings.get('network.listening_port'),
                self._settings.get('network.listening_port') + 1
            ),
            SetStatus.create(UserStatus.ONLINE.value),
            HaveNoParent.create(True),
            BranchRoot.create(self._settings.get('credentials.username')),
            BranchLevel.create(0),
            AcceptChildren.create(False),
            SharedFoldersFiles.create(dir_count, file_count),
            AddUser.create(self._settings.get('credentials.username')),
            PrivateRoomToggle.create(self._settings.get('chats.private_room_invites'))
        )

        # Perform AddUser for all in the friendlist
        self.network.send_server_messages(
            *[
                AddUser.create(friend)
                for friend in self._settings.get('users.friends')
            ]
        )

        # Auto-join rooms
        if self._settings.get('chats.auto_join'):
            self.network.send_server_messages(
                *[
                    ChatJoinRoom.create(room_name)
                    for room_name in self._settings.get('chats.rooms')
                ]
            )

        self._internal_event_bus.emit(LoginEvent(success=success))

    @on_message(ChatRoomMessage)
    def _on_chat_room_message(self, message, connection):
        room_name, username, chat_message = message.parse()

        user = self._state.get_or_create_user(username)
        room = self._state.get_or_create_room(room_name)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=chat_message
        )
        room.messages.append(room_message)

        self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(ChatUserJoinedRoom)
    def _on_user_joined_room(self, message, connection):
        room_name, username, status, avg_speed, download_num, file_count, dir_count, slots_free, country = message.parse()
        logger.info(f"user {username} joined room {room_name}")

        user = self._state.get_or_create_user(username)
        user.status = UserStatus(status)
        user.avg_speed = avg_speed
        user.downloads = download_num
        user.files = file_count
        user.directories = dir_count
        user.has_slots_free = slots_free
        user.country = country

        room = self._state.get_or_create_room(room_name)
        room.add_user(user)

        self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))

    @on_message(ChatUserLeftRoom)
    def _on_user_left_room(self, message, connection):
        room_name, username = message.parse()
        logger.info(f"user {username} left room {room_name}")
        user = self._state.get_or_create_user(username)
        room = self._state.get_or_create_room(room_name)

        self._event_bus.emit(UserLeftRoomEvent(user=user, room=room))

    @on_message(ChatJoinRoom)
    def _on_join_room(self, message, connection):
        room_name, users, users_status, users_data, users_has_slots_free, users_countries, owner, operators = message.parse()

        room = self._state.get_or_create_room(room_name)
        for idx, name in enumerate(users):
            avg_speed, download_num, file_count, dir_count = users_data[idx]
            user = self._state.get_or_create_user(name)
            user.status = UserStatus(users_status[idx])
            user.avg_speed = avg_speed
            user.downloads = download_num
            user.files = file_count
            user.directories = dir_count
            user.country = users_countries[idx]
            user.has_slots_free = users_has_slots_free[idx]

            room.add_user(user)

        room.owner = owner
        for operator in operators:
            room.add_operator(self._state.get_or_create_user(operator))

        self._event_bus.emit(RoomJoinedEvent(room=room))

    @on_message(ChatLeaveRoom)
    def _on_leave_room(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.joined = False

        self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(ChatRoomTickers)
    def _on_chat_room_tickers(self, message, connection):
        room_name, tickers = message.parse()
        logger.debug(f"room tickers {len(tickers)}")

        room = self._state.get_or_create_room(room_name)
        tickers = [(self._state.get_or_create_user(username), ticker, )
                   for username, ticker in tickers]
        self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(ChatRoomTickerAdd)
    def _on_chat_room_ticker_add(self, message, connection):
        contents = message.parse()
        room_name, username, ticker = contents
        logger.debug(f"room ticker add : {contents!r}")

        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)

        self._event_bus.emit(RoomTickerAddedEvent(room, user, ticker))

    @on_message(ChatRoomTickerRemove)
    def _on_chat_room_ticker_removed(self, message, connection):
        contents = message.parse()
        room_name, username = contents
        logger.debug(f"room ticker removed : {contents!r}")

        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)

        self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(PrivateRoomToggle)
    def _on_private_room_toggle(self, message, connection):
        enabled = message.parse()
        logger.debug(f"private rooms enabled : {enabled}")

    @on_message(PrivateRoomAdded)
    def _on_private_room_added(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.joined = True
        room.is_private = True

        self._event_bus.emit(UserJoinedPrivateRoomEvent(room))

    @on_message(PrivateRoomRemoved)
    def _on_private_room_removed(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.joined = False
        room.is_private = True

        self._event_bus.emit(UserLeftPrivateRoomEvent(room))

    @on_message(PrivateRoomUsers)
    def _on_private_room_users(self, message, connection):
        room_name, usernames = message.parse()

        room = self._state.get_or_create_room(room_name)
        for username in usernames:
            room.add_user(self._state.get_or_create_user(username))

    @on_message(PrivateRoomAddUser)
    def _on_private_room_add_user(self, message, connection):
        room_name, username = message.parse()

        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)

        room.add_user(user)

    @on_message(PrivateRoomOperators)
    def _on_private_room_operators(self, message, connection):
        room_name, operators = message.parse()

        room = self._state.get_or_create_room(room_name)
        for operator in operators:
            room.add_operator(self._state.get_or_create_user(operator))

    @on_message(PrivateRoomOperatorAdded)
    def _on_private_room_operator_added(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.is_operator = True

    @on_message(PrivateRoomOperatorRemoved)
    def _on_private_room_operator_removed(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.is_operator = False

    @on_message(PrivateRoomAddOperator)
    def _on_private_room_add_operator(self, message, connection):
        room_name, username = message.parse()
        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)
        room.add_operator(user)

    @on_message(PrivateRoomRemoveOperator)
    def _on_private_room_remove_operators(self, message, connection):
        room_name, username = message.parse()
        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)
        room.operators.remove(user)

    @on_message(ChatPrivateMessage)
    def _on_private_message(self, message, connection):
        chat_id, timestamp, username, chat_msg, is_admin = message.parse()
        user = self._state.get_or_create_user(username)
        chat_message = ChatMessage(
            id=chat_id,
            timestamp=timestamp,
            user=user,
            message=chat_msg,
            is_admin=is_admin
        )
        self._state.private_messages[chat_id] = chat_message

        self.network.send_server_messages(
            ChatAckPrivateMessage.create(chat_id)
        )

        self._event_bus.emit(PrivateMessageEvent(user, chat_message))

    @on_message(ServerSearchRequest)
    def _on_server_search_request(self, message, connection):
        contents = message.parse()
        code, unknown, username, ticket, query = contents
        logger.info(f"ServerSearchRequest : {contents!r}")

        message_to_send = DistributedServerSearchRequest.create(
            code, username, ticket, query, unknown=unknown
        )
        for child in self._state.children:
            child.connection.queue_messages(message_to_send)

    # State related messages
    @on_message(CheckPrivileges)
    def _on_check_privileges(self, message, connection):
        self._state.privileges_time_left = message.parse()

    @on_message(RoomList)
    def _on_room_list(self, message, connection):
        room_infos, rooms_private_owned, rooms_private, rooms_private_operated = message.parse()
        for room_name, user_count in room_infos.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count

        for room_name, user_count in rooms_private_owned.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count
            room.is_private = True
            room.owner = self._settings.get('credentials.username')

        for room_name, user_count in rooms_private.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count
            room.is_private = True

        for room_name in rooms_private_operated:
            room = self._state.get_or_create_room(room_name)
            room.is_private = True
            room.is_operator = True

        self._event_bus.emit(RoomListEvent(rooms=self._state.rooms.values()))

    @on_message(ParentMinSpeed)
    def _on_parent_min_speed(self, message, connection):
        self._state.parent_min_speed = message.parse()

    @on_message(ParentSpeedRatio)
    def _on_parent_speed_ratio(self, message, connection):
        self._state.parent_speed_ratio = message.parse()

    @on_message(MinParentsInCache)
    def _on_min_parents_in_cache(self, message, connection):
        self._state.min_parents_in_cache = message.parse()

    @on_message(DistributedAliveInterval)
    def _on_ditributed_alive_interval(self, message, connection):
        self._state.distributed_alive_interval = message.parse()

    @on_message(SearchInactivityTimeout)
    def _on_search_inactivity_timeout(self, message, connection):
        self._state.search_inactivity_timeout = message.parse()

    @on_message(PrivilegedUsers)
    def _on_privileged_users(self, message, connection):
        privileged_users = message.parse()
        for privileged_user in privileged_users:
            user = self._state.get_or_create_user(privileged_user)
            user.privileged = True

    @on_message(AddPrivilegedUser)
    def _on_add_privileged_user(self, message, connection):
        privileged_user = message.parse()
        user = self._state.get_or_create_user(privileged_user)
        user.privileged = True

    @on_message(WishlistInterval)
    def _on_wish_list_interval(self, message, connection):
        self._state.wishlist_interval = message.parse()

    @on_message(AddUser)
    def _on_add_user(self, message, connection):
        add_user_info = message.parse()
        logger.info(f"AddUser : {add_user_info}")
        name, exists, status, avg_speed, downloads, files, directories, country = add_user_info
        if exists:
            user = self._state.get_or_create_user(name)
            user.name = name
            user.status = UserStatus(status)
            user.avg_speed = avg_speed
            user.downloads = downloads
            user.files = files
            user.directories = directories
            user.country = country

            self._event_bus.emit(UserAddEvent(user))

    @on_message(GetUserStatus)
    def _on_get_user_status(self, message, connection):
        username, status, privileged = message.parse()
        logger.info(f"GetUserStatus : username={username}, status={status}, privileged={privileged}")

        user = self._state.get_or_create_user(username)
        user.status = UserStatus(status)
        user.privileged = privileged

        self._event_bus.emit(UserStatusEvent(user))

    @on_message(GetUserStats)
    def _on_get_user_stats(self, message, connection):
        contents = message.parse()
        username, avg_speed, download_num, files, dirs = contents
        logger.info(f"GetUserStats : {contents}")

        user = self._state.get_or_create_user(username)
        user.avg_speed = avg_speed
        user.downloads = download_num
        user.files = files
        user.directories = dirs

        self._event_bus.emit(UserStatsEvent(user))

    @on_message(NetInfo)
    def _on_net_info(self, message, connection):
        net_info_list = message.parse()

        if not self._settings.get('debug.search_for_parent'):
            logger.debug("ignoring NetInfo message : searching for parent is disabled")
            return

        logger.info(f"received NetInfo list : {net_info_list!r}")

        self._state.potential_parents = [
            username for username, _, _ in net_info_list
        ]

        for username, ip, port in net_info_list:
            self.network.init_peer_connection(
                username,
                PeerConnectionType.DISTRIBUTED,
                ip=ip,
                port=port
            )

    def _on_server_message(self, event: ServerMessageEvent):
        message = copy.deepcopy(event.message)
        if message.__class__ in self.MESSAGE_MAP:
            self.MESSAGE_MAP[message.__class__](message, event.connection)

    # Connection state listeners
    def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            self.login(
                self._settings.get('credentials.username'),
                self._settings.get('credentials.password')
            )
            self._state.scheduler.add_job(self._ping_job)
            self._state.scheduler.add_job(self._report_shares_job)

        elif event.state == ConnectionState.CLOSED:
            self._state.logged_in = False
            self._state.scheduler.remove(self._ping_job)
            self._state.scheduler.remove(self._report_shares_job)
            self._event_bus.emit(ServerDisconnectedEvent())
