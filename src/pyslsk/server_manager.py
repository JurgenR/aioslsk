import logging
from os import stat
import time

from .connection import ConnectionState, CloseReason, PeerConnectionType
from .events import (
    on_message,
    EventBus,
    PrivateMessageEvent,
    RoomMessageEvent,
    RoomListEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomTickersEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    UserAddEvent,
    UserJoinedRoomEvent,
    UserLeftRoomEvent,
)
from .filemanager import FileManager
from .messages import (
    AcceptChildren,
    AddUser,
    BranchRoot,
    BranchLevel,
    ChatPrivateRoomUsers,
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
    GetUserStatus,
    GetUserStats,
    HaveNoParent,
    Login,
    NetInfo,
    ParentMinSpeed,
    ParentSpeedRatio,
    Ping,
    PrivilegedUsers,
    RoomList,
    ServerSearchRequest,
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
    WishlistInterval,
    DistributedServerSearchRequest,
)
from .model import ChatMessage, Room, RoomMessage, User, UserStatus
from .network import Network
from .scheduler import Job
from .state import State


logger = logging.getLogger()


class ServerManager:

    def __init__(self, state: State, settings, event_bus: EventBus, file_manager: FileManager, network: Network):
        self._state: State = state
        self._settings = settings
        self._event_bus: EventBus = event_bus
        self.file_manager: FileManager = file_manager
        self.network: Network = network
        self.network.server_listeners.append(self)

        self._ping_job = Job(5 * 60, self.send_ping)

    @property
    def connection_state(self) -> ConnectionState:
        return self.network.server.state

    def send_ping(self):
        self.network.send_server_messages(Ping.create())

    def login(self, username: str, password: str):
        logger.info(f"sending request to login: username={username}, password={password}")
        self.network.send_server_messages(
            Login.create(username, password, 157)
        )

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

    @on_message(Login)
    def on_login(self, message, connection):
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
                self._settings['network']['listening_port'],
                self._settings['network']['listening_port'] + 1
            ),
            SetStatus.create(UserStatus.ONLINE.value),
            HaveNoParent.create(True),
            BranchRoot.create(self._settings['credentials']['username']),
            BranchLevel.create(0),
            AcceptChildren.create(False),
            SharedFoldersFiles.create(dir_count, file_count),
            AddUser.create(self._settings['credentials']['username'])
        )

    @on_message(ChatRoomMessage)
    def on_chat_room_message(self, message, connection):
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
    def on_user_joined_room(self, message, connection):
        room_name, username, status, avg_speed, download_num, file_count, dir_count, slots_free, country = message.parse()
        logger.debug(f"user {username} joined room {room_name}")

        user = self._state.get_or_create_user(username)
        user.status = UserStatus(status)
        user.avg_speed = avg_speed
        user.downloads = download_num
        user.files = file_count
        user.directories = dir_count
        user.has_slots_free = slots_free
        user.country = country

        room = self._state.get_or_create_room(room_name)
        room.users.append(user)

        self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))

    @on_message(ChatUserLeftRoom)
    def on_user_left_room(self, message, connection):
        room_name, username = message.parse()
        logger.info(f"user {username} left room {room_name}")
        user = self._state.get_or_create_user(username)
        room = self._state.get_or_create_room(room_name)

        self._event_bus.emit(UserLeftRoomEvent(user=user, room=room))

    @on_message(ChatJoinRoom)
    def on_join_room(self, message, connection):
        room_name, users, users_status, users_data, users_has_slots_free, users_countries, owner, operators = message.parse()

        room = Room(
            name=room_name,
            owner=owner,
            operators=operators,
            joined=True
        )
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

            room.users.append(user)
        room = self._state.upsert_room(room)

        self._event_bus.emit(RoomJoinedEvent(room=room))

    @on_message(ChatLeaveRoom)
    def on_leave_room(self, message, connection):
        room_name = message.parse()
        room = self._state.get_or_create_room(room_name)
        room.joined = False

        self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(ChatRoomTickers)
    def on_chat_room_tickers(self, message, connection):
        room_name, tickers = message.parse()
        logger.debug(f"room tickers {len(tickers)}")

        room = self._state.get_or_create_room(room_name)
        tickers = [(self._state.get_or_create_user(username), ticker, )
                   for username, ticker in tickers]
        self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(ChatRoomTickerAdd)
    def on_chat_room_ticker_add(self, message, connection):
        contents = message.parse()
        room_name, username, ticker = contents
        logger.debug(f"room ticker add : {contents!r}")

        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)

        self._event_bus.emit(RoomTickerAddedEvent(room, user, ticker))

    @on_message(ChatRoomTickerRemove)
    def on_chat_room_ticker_removed(self, message, connection):
        contents = message.parse()
        room_name, username = contents
        logger.debug(f"room ticker removed : {contents!r}")

        room = self._state.get_or_create_room(room_name)
        user = self._state.get_or_create_user(username)

        self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(ChatPrivateMessage)
    def on_private_message(self, message, connection):
        chat_id, timestamp, username, chat_msg, is_admin = message.parse()
        user = self._state.get_or_create_user(username)
        chat_message = ChatMessage(
            id=chat_id,
            timestamp=timestamp,
            user=username,
            message=chat_msg,
            is_admin=is_admin
        )
        self._state.private_messages[chat_id] = chat_message

        self.network.send_server_messages(
            ChatAckPrivateMessage.create(chat_id)
        )

        self._event_bus.emit(PrivateMessageEvent(user, chat_message))

    @on_message(ServerSearchRequest)
    def on_server_search_request(self, message, connection):
        contents = message.parse()
        code, unknown, username, ticket, query = contents
        logger.info(f"ServerSearchRequest : {contents!r}")

        message_to_send = DistributedServerSearchRequest.create(
            code, username, ticket, query, unknown=unknown
        )
        for child in self._state.children:
            child.connection.queue_message(message_to_send)

    # State related messages
    @on_message(CheckPrivileges)
    def on_check_privileges(self, message, connection):
        self._state.privileges_time_left = message.parse()

    @on_message(RoomList)
    def on_room_list(self, message, connection):
        room_infos, rooms_private_owned, rooms_private, rooms_private_operated = message.parse()
        for room_name, user_count in room_infos.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count

        for room_name, user_count in rooms_private_owned.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count
            room.is_private = True
            room.owner = self._settings['credentials']['username']

        for room_name, user_count in rooms_private.items():
            room = self._state.get_or_create_room(room_name)
            room.user_count = user_count
            room.is_private = True

        self._event_bus.emit(RoomListEvent(rooms=self._state.rooms.values()))

    @on_message(ChatPrivateRoomUsers)
    def on_private_room_users(self, message, connection):
        room_name, usernames = message.parse()

    @on_message(ParentMinSpeed)
    def on_parent_min_speed(self, message, connection):
        self._state.parent_min_speed = message.parse()

    @on_message(ParentSpeedRatio)
    def on_parent_speed_ratio(self, message, connection):
        self._state.parent_speed_ratio = message.parse()

    @on_message(PrivilegedUsers)
    def on_privileged_users(self, message, connection):
        privileged_users = message.parse()
        for privileged_user in privileged_users:
            user = self._state.get_or_create_user(privileged_user)
            user.privileged = True

    @on_message(WishlistInterval)
    def on_wish_list_interval(self, message, connection):
        self._state.wishlist_interval = message.parse()

    @on_message(AddUser)
    def on_add_user(self, message, connection):
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
    def on_get_user_status(self, message, connection):
        username, status, privileged = message.parse()
        logger.info(f"GetUserStatus : username={username}, status={status}, privileged={privileged}")

        user = self._state.get_or_create_user(username)
        user.status = UserStatus(status)
        user.status = privileged

    @on_message(GetUserStats)
    def on_get_user_stats(self, message, connection):
        contents = message.parse()
        username, avg_speed, download_num, files, dirs = contents
        logger.info(f"GetUserStats : {contents}")

        user = self._state.get_or_create_user(username)
        user.avg_speed = avg_speed
        user.downloads = download_num
        user.files = files
        user.directories = dirs

    @on_message(NetInfo)
    def on_net_info(self, message, connection):
        net_info_list = message.parse()

        if not self._settings['debug']['search_for_parent']:
            logger.debug("ignoring NetInfo message : searching for parent is disabled")
            return

        self._state.potential_parents = net_info_list

        for idx, (username, ip, port) in enumerate(net_info_list, 1):
            ticket = next(self._state.ticket_generator)
            logger.debug(f"netinfo user {idx}: {username!r} : {ip}:{port} (ticket={ticket})")

            self.network.init_peer_connection(
                ticket,
                username,
                PeerConnectionType.DISTRIBUTED,
                ip=ip,
                port=port
            )

    # Connection state listeners
    def on_state_changed(self, state, connection, close_reason: CloseReason = None):
        if state == ConnectionState.CONNECTED:
            self._state.scheduler.add_job(self._ping_job)

        elif state == ConnectionState.CLOSED:
            self._state.scheduler.remove(self._ping_job)
