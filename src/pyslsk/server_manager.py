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
    MessageReceivedEvent,
    UserAddEvent,
    UserJoinedRoomEvent,
    UserJoinedPrivateRoomEvent,
    UserLeftRoomEvent,
    UserLeftPrivateRoomEvent,
    UserStatsEvent,
    UserStatusEvent,
)
from .shares import SharesManager
from .protocol.primitives import calc_md5
from .protocol.messages import (
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
    ChatRoomTickerAdded,
    ChatRoomTickerRemoved,
    ChatRoomTickerSet,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    CheckPrivileges,
    DistributedAliveInterval,
    GetUserStatus,
    GetUserStats,
    ToggleParentSearch,
    Login,
    MinParentsInCache,
    PotentialParents,
    ParentInactivityTimeout,
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
    TogglePrivateRooms,
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
)
from .model import ChatMessage, RoomMessage, UserStatus
from .network import Network
from .scheduler import Job
from .settings import Settings
from .state import State


logger = logging.getLogger()


LOGIN_TIMEOUT = 30


class ServerManager:

    def __init__(self, state: State, settings: Settings, event_bus: EventBus, internal_event_bus: InternalEventBus, shares_manager: SharesManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self.shares_manager: SharesManager = shares_manager
        self.network: Network = network

        self._ping_job = Job(5 * 60, self.send_ping)
        self._report_shares_job = Job(30, self.report_shares)

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    @property
    def connection_state(self) -> ConnectionState:
        return self.network.server.state

    def send_ping(self):
        """Send ping to the server"""
        self.network.send_server_messages(Ping.Request().serialize())

    def report_shares(self):
        """Reports the shares amount to the server"""
        dir_count, file_count = self.shares_manager.get_stats()
        logger.debug(f"reporting shares to the server (dirs={dir_count}, file_count={file_count})")
        self.network.send_server_messages(
            SharedFoldersFiles.Request(
                directory_count=dir_count,
                file_count=file_count
            ).serialize()
        )

    def login(self, username: str, password: str, version: int = 157):
        logger.info(f"sending request to login: username={username}, password={password}")
        self.network.send_server_messages(
            Login.Request(
                username=username,
                password=password,
                client_version=157,
                md5hash=calc_md5(username + password),
                minor_version=100
            ).serialize()
        )

    def add_user(self, username: str):
        self.network.send_server_messages(
            AddUser.Request(username).serialize()
        )

    def remove_user(self, username: str):
        self.network.send_server_messages(
            RemoveUser.Request(username).serialize()
        )

    def get_user_stats(self, username: str):
        self.network.send_server_messages(
            GetUserStats.Request(username).serialize()
        )

    def get_user_status(self, username: str):
        self.network.send_server_messages(
            GetUserStatus.Request(username).serialize()
        )

    def get_room_list(self):
        self.network.send_server_messages(RoomList.Request().serialize())

    def join_room(self, name: str):
        self.network.send_server_messages(
            ChatJoinRoom.Request(name).serialize()
        )

    def leave_room(self, name: str):
        self.network.send_server_messages(
            ChatLeaveRoom.Request(name).serialize()
        )

    def set_room_ticker(self, room_name: str, ticker: str):
        # No need to update the ticker in the model, a ChatRoomTickerAdded will
        # be sent back to us
        self.network.send_server_messages(
            ChatRoomTickerSet.Request(room=room_name, ticker=ticker).serialize()
        )

    def send_private_message(self, username: str, message: str):
        self.network.send_server_messages(
            ChatPrivateMessage.Request(username, message).serialize()
        )

    def send_room_message(self, room_name: str, message: str):
        self.network.send_server_messages(
            ChatRoomMessage.Request(room_name, message).serialize()
        )

    def drop_private_room_ownership(self, room_name: str):
        self.network.send_server_messages(
            PrivateRoomDropOwnership.Request(room_name).serialize()
        )

    def drop_private_room_membership(self, room_name: str):
        self.network.send_server_messages(
            PrivateRoomDropMembership.Request(room_name).serialize()
        )

    @on_message(Login.Response)
    def _on_login(self, message: Login.Response, connection):
        """Called when a response is received to a logon call"""
        # First value indicates success
        if message.success:
            self._state.logged_in = True
            logger.info("Successfully logged on")
        else:
            logger.error(f"Failed to login, reason: {message.reason!r}")

        # Make setup calls
        dir_count, file_count = self.shares_manager.get_stats()
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")

        self.network.send_server_messages(
            CheckPrivileges.Request().serialize(),
            SetListenPort.Request(
                self._settings.get('network.listening_port'),
                obfuscated_port_amount=1,
                obfuscated_port=self._settings.get('network.listening_port') + 1
            ).serialize(),
            SetStatus.Request(UserStatus.ONLINE.value).serialize(),
            ToggleParentSearch.Request(True).serialize(),
            BranchRoot.Request(self._settings.get('credentials.username')).serialize(),
            BranchLevel.Request(0).serialize(),
            AcceptChildren.Request(False).serialize(),
            SharedFoldersFiles.Request(dir_count, file_count).serialize(),
            AddUser.Request(self._settings.get('credentials.username')).serialize(),
            TogglePrivateRooms.Request(self._settings.get('chats.private_room_invites')).serialize()
        )

        # Perform AddUser for all in the friendlist
        self.network.send_server_messages(
            *[
                AddUser.Request(friend).serialize()
                for friend in self._settings.get('users.friends')
            ]
        )

        # Auto-join rooms
        if self._settings.get('chats.auto_join'):
            rooms = self._settings.get('chats.rooms')
            logger.info(f"automatically rejoining {len(rooms)} rooms")
            self.network.send_server_messages(
                *[ChatJoinRoom.Request(room).serialize() for room in rooms]
            )

        self._internal_event_bus.emit(LoginEvent(success=message.success))

    @on_message(ChatRoomMessage.Response)
    def _on_chat_room_message(self, message: ChatRoomMessage.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )
        room.messages.append(room_message)

        self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(ChatUserJoinedRoom.Response)
    def _on_user_joined_room(self, message: ChatUserJoinedRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.avg_speed = message.user_data.avg_speed
        user.downloads = message.user_data.download_num
        user.files = message.user_data.file_count
        user.directories = message.user_data.dir_count
        user.has_slots_free = message.slots_free
        user.country = message.country_code

        room = self._state.get_or_create_room(message.username)
        room.add_user(user)

        self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))

    @on_message(ChatUserLeftRoom.Response)
    def _on_user_left_room(self, message: ChatUserLeftRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)

        self._event_bus.emit(UserLeftRoomEvent(user=user, room=room))

    @on_message(ChatJoinRoom.Response)
    def _on_join_room(self, message: ChatJoinRoom.Response, connection):
        room = self._state.get_or_create_room(message.room)
        for idx, name in enumerate(message.users):
            user_data = message.users_data[idx]

            user = self._state.get_or_create_user(name)
            user.status = UserStatus(message.users_status[idx])
            user.avg_speed = user_data.avg_speed
            user.downloads = user_data.download_num
            user.files = user_data.file_count
            user.directories = user_data.dir_count
            user.country = message.users_countries[idx]
            user.has_slots_free = message.users_slots_free[idx]

            room.add_user(user)

        room.owner = message.owner
        for operator in message.operators:
            room.add_operator(self._state.get_or_create_user(operator))

        self._event_bus.emit(RoomJoinedEvent(room=room))

    @on_message(ChatLeaveRoom.Response)
    def _on_leave_room(self, message: ChatLeaveRoom.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = False

        self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(ChatRoomTickers.Response)
    def _on_chat_room_tickers(self, message: ChatRoomTickers.Response, connection):
        room = self._state.get_or_create_room(message.room)
        tickers = {}
        for ticker in message.tickers:
            self._state.get_or_create_user(ticker.username)
            tickers[ticker.username] = ticker.ticker

        # Just replace all tickers instead of modifying the existing dict
        room.tickers = tickers

        self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(ChatRoomTickerAdded.Response)
    def _on_chat_room_ticker_added(self, message: ChatRoomTickerAdded.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        room.tickers[user.name] = message.ticker

        self._event_bus.emit(RoomTickerAddedEvent(room, user, message.ticker))

    @on_message(ChatRoomTickerRemoved.Response)
    def _on_chat_room_ticker_removed(self, message: ChatRoomTickerRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        try:
            del room.tickers[user.name]
        except KeyError:
            logger.warning(
                f"attempted to remove room ticker for user {user.name} in room {room.name} "
                "but it wasn't present")

        self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(TogglePrivateRooms.Response)
    def _on_private_room_toggle(self, message, connection):
        logger.debug(f"private rooms enabled : {message.enabled}")

    @on_message(PrivateRoomAdded.Response)
    def _on_private_room_added(self, message: PrivateRoomAdded.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = True
        room.is_private = True

        self._event_bus.emit(UserJoinedPrivateRoomEvent(room))

    @on_message(PrivateRoomRemoved.Response)
    def _on_private_room_removed(self, message: PrivateRoomRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = False
        room.is_private = True

        self._event_bus.emit(UserLeftPrivateRoomEvent(room))

    @on_message(PrivateRoomUsers.Response)
    def _on_private_room_users(self, message: PrivateRoomUsers.Response, connection):
        room = self._state.get_or_create_room(message.room)
        for username in message.usernames:
            room.add_user(self._state.get_or_create_user(username))

    @on_message(PrivateRoomAddUser.Response)
    def _on_private_room_add_user(self, message: PrivateRoomAddUser.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        room.add_user(user)

    @on_message(PrivateRoomOperators.Response)
    def _on_private_room_operators(self, message: PrivateRoomOperators.Response, connection):
        room = self._state.get_or_create_room(message.room)
        for operator in message.usernames:
            room.add_operator(self._state.get_or_create_user(operator))

    @on_message(PrivateRoomOperatorAdded.Response)
    def _on_private_room_operator_added(self, message: PrivateRoomOperatorAdded.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.is_operator = True

    @on_message(PrivateRoomOperatorRemoved.Response)
    def _on_private_room_operator_removed(self, message: PrivateRoomOperatorRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.is_operator = False

    @on_message(PrivateRoomAddOperator.Response)
    def _on_private_room_add_operator(self, message: PrivateRoomAddOperator.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)
        room.add_operator(user)

    @on_message(PrivateRoomRemoveOperator.Response)
    def _on_private_room_remove_operators(self, message: PrivateRoomRemoveOperator.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)
        room.operators.remove(user)

    @on_message(ChatPrivateMessage.Response)
    def _on_private_message(self, message: ChatPrivateMessage.Response, connection):
        user = self._state.get_or_create_user(message.username)
        chat_message = ChatMessage(
            id=message.chat_id,
            timestamp=message.timestamp,
            user=user,
            message=message.message,
            is_admin=message.is_admin
        )
        self._state.private_messages[message.chat_id] = chat_message

        self.network.send_server_messages(
            ChatAckPrivateMessage.Request(message.chat_id).serialize()
        )

        self._event_bus.emit(PrivateMessageEvent(user, chat_message))

    @on_message(ServerSearchRequest.Response)
    def _on_server_search_request(self, message: ServerSearchRequest.Response, connection):
        message_to_send = message.serialize()
        for child in self._state.children:
            child.connection.queue_messages(message_to_send)

    # State related messages
    @on_message(CheckPrivileges.Response)
    def _on_check_privileges(self, message: CheckPrivileges.Response, connection):
        self._state.privileges_time_left = message.time_left

    @on_message(RoomList.Response)
    def _on_room_list(self, message: RoomList.Response, connection):
        for idx, room_name in enumerate(message.rooms):
            room = self._state.get_or_create_room(room_name)
            room.user_count = message.rooms_user_count[idx]

        for idx, room_name in enumerate(message.rooms_private_owned):
            room = self._state.get_or_create_room(room_name)
            room.user_count = message.rooms_private_owned_user_count[idx]
            room.is_private = True
            room.owner = self._settings.get('credentials.username')

        for idx, room_name in enumerate(message.rooms_private):
            room = self._state.get_or_create_room(room_name)
            room.user_count = message.rooms_private_user_count[idx]
            room.is_private = True

        for room_name in message.rooms_private_operated:
            room = self._state.get_or_create_room(room_name)
            room.is_private = True
            room.is_operator = True

        self._event_bus.emit(RoomListEvent(rooms=self._state.rooms.values()))

    @on_message(ParentMinSpeed.Response)
    def _on_parent_min_speed(self, message: ParentMinSpeed.Response, connection):
        self._state.parent_min_speed = message.speed

    @on_message(ParentSpeedRatio.Response)
    def _on_parent_speed_ratio(self, message: ParentSpeedRatio.Response, connection):
        self._state.parent_speed_ratio = message.ratio

    @on_message(MinParentsInCache.Response)
    def _on_min_parents_in_cache(self, message: MinParentsInCache.Response, connection):
        self._state.min_parents_in_cache = message.amount

    @on_message(DistributedAliveInterval.Response)
    def _on_ditributed_alive_interval(self, message: DistributedAliveInterval.Response, connection):
        self._state.distributed_alive_interval = message.interval

    @on_message(ParentInactivityTimeout.Response)
    def _on_parent_inactivity_timeout(self, message: ParentInactivityTimeout.Response, connection):
        self._state.parent_inactivity_timeout = message.timeout

    @on_message(SearchInactivityTimeout.Response)
    def _on_search_inactivity_timeout(self, message: SearchInactivityTimeout.Response, connection):
        self._state.search_inactivity_timeout = message.timeout

    @on_message(PrivilegedUsers.Response)
    def _on_privileged_users(self, message: PrivilegedUsers.Response, connection):
        for username in message.users:
            user = self._state.get_or_create_user(username)
            user.privileged = True

    @on_message(AddPrivilegedUser.Response)
    def _on_add_privileged_user(self, message: AddPrivilegedUser.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.privileged = True

    @on_message(WishlistInterval.Response)
    def _on_wish_list_interval(self, message: WishlistInterval.Response, connection):
        self._state.wishlist_interval = message.interval

    @on_message(AddUser.Response)
    def _on_add_user(self, message: AddUser.Response, connection):
        if message.exists:
            user = self._state.get_or_create_user(message.username)
            user.name = message.username
            user.status = UserStatus(message.status)
            user.avg_speed = message.avg_speed
            user.downloads = message.download_num
            user.files = message.file_count
            user.directories = message.dir_count
            user.country = message.country_code

            self._event_bus.emit(UserAddEvent(user))

    @on_message(GetUserStatus.Response)
    def _on_get_user_status(self, message: GetUserStatus.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.privileged = message.privileged

        self._event_bus.emit(UserStatusEvent(user))

    @on_message(GetUserStats.Response)
    def _on_get_user_stats(self, message: GetUserStats.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.avg_speed = message.avg_speed
        user.downloads = message.download_num
        user.files = message.file_count
        user.directories = message.dir_count

        self._event_bus.emit(UserStatsEvent(user))

    @on_message(PotentialParents.Response)
    def _on_net_info(self, message: PotentialParents.Response, connection):
        if not self._settings.get('debug.search_for_parent'):
            logger.debug("ignoring NetInfo message : searching for parent is disabled")
            return

        self._state.potential_parents = [
            entry.username for entry in message.entries
        ]

        for entry in message.entries:
            self.network.init_peer_connection(
                entry.username,
                PeerConnectionType.DISTRIBUTED,
                ip=entry.ip,
                port=entry.port
            )

    def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
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
