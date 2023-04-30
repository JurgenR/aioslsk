import asyncio
import logging
import time

from .network.connection import CloseReason, ConnectionState, ServerConnection
from .constants import (
    SERVER_PING_INTERVAL,
)
from .events import (
    build_message_map,
    on_message,
    AddedToPrivateRoomEvent,
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
    KickedEvent,
    LoginEvent,
    LoginSuccessEvent,
    MessageReceivedEvent,
    PrivateMessageEvent,
    RemovedFromPrivateRoomEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomListEvent,
    RoomMessageEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    RoomTickersEvent,
    ServerDisconnectedEvent,
    ServerMessageEvent,
    TrackUserEvent,
    UntrackUserEvent,
    UserInfoEvent,
    UserJoinedRoomEvent,
    UserLeftRoomEvent,
    UserStatusEvent,
)
from .exceptions import ConnectionFailedError
from .protocol.primitives import calc_md5
from .protocol.messages import (
    AddPrivilegedUser,
    AddUser,
    ChatRoomMessage,
    ChatJoinRoom,
    ChatLeaveRoom,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    ChatRoomSearch,
    ChatRoomTickers,
    ChatRoomTickerAdded,
    ChatRoomTickerRemoved,
    ChatRoomTickerSet,
    ChatUserJoinedRoom,
    ChatUserLeftRoom,
    CheckPrivileges,
    DistributedAliveInterval,
    FileSearch,
    GetPeerAddress,
    GetUserStatus,
    GetUserStats,
    Kicked,
    Login,
    MinParentsInCache,
    ParentInactivityTimeout,
    ParentMinSpeed,
    ParentSpeedRatio,
    Ping,
    PrivateRoomAddUser,
    PrivateRoomRemoveUser,
    PrivateRoomUsers,
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
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
    UserSearch,
    WishlistInterval,
    WishlistSearch,
)
from .model import ChatMessage, RoomMessage, User, UserStatus
from .network.network import Network
from .shares import SharesManager
from .search import SearchRequest, SearchType
from .settings import Settings
from .state import State
from .utils import task_counter, ticket_generator


logger = logging.getLogger()


class ServerManager:

    def __init__(self, state: State, settings: Settings, event_bus: EventBus, internal_event_bus: InternalEventBus, shares_manager: SharesManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network

        self._ticket_generator = ticket_generator()

        self._ping_task: asyncio.Task = None
        self._wishlist_task: asyncio.Task = None
        self._post_login_task: asyncio.Task = None
        self._connection_watchdog_task: asyncio.Task = None

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            TrackUserEvent, self._on_track_user)
        self._internal_event_bus.register(
            UntrackUserEvent, self._on_untrack_user)

    @property
    def connection_state(self) -> ConnectionState:
        return self._network.server.state

    async def send_ping(self):
        """Send ping to the server"""
        await self._network.send_server_messages(Ping.Request())

    async def report_shares(self):
        """Reports the shares amount to the server"""
        dir_count, file_count = self._shares_manager.get_stats()
        logger.debug(f"reporting shares to the server (dirs={dir_count}, file_count={file_count})")
        await self._network.send_server_messages(
            SharedFoldersFiles.Request(
                directory_count=dir_count,
                file_count=file_count
            )
        )

    async def login(self, username: str, password: str, version: int = 157):
        logger.info(f"sending request to login: username={username}, password={password}")
        await self._network.send_server_messages(
            Login.Request(
                username=username,
                password=password,
                client_version=version,
                md5hash=calc_md5(username + password),
                minor_version=100
            )
        )

    async def track_user(self, username: str):
        """Starts tracking a user. The method sends an `AddUser` only if the
        `is_tracking` variable is set to False. Updates to the user will be
        omitted through the `UserInfoEvent`
        """
        user = self._state.get_or_create_user(username)

        if not user.is_tracking:
            await self._network.send_server_messages(AddUser.Request(username))
            user.is_tracking = True

    async def track_friends(self):
        tasks = []
        for friend in self._settings.get('users.friends'):
            tasks.append(asyncio.create_task(self.track_user(friend)))

        asyncio.gather(*tasks, return_exceptions=True)

    async def untrack_user(self, user):
        user = self._state.get_or_create_user(user)
        # Reset user status, this is needed for the transfer manager who
        # will skip attempting to transfer for offline user. But if we don't
        # know if a user is online we will never attempt to start that
        # transfer
        await self._network.send_server_messages(RemoveUser.Request(user.name))
        user.is_tracking = False
        user.status = UserStatus.UNKNOWN

    async def auto_join_rooms(self):
        """Automatically joins rooms stored in the settings. This method will
        do nothing if the `chats.auto_join` setting is not enabled
        """
        if not self._settings.get('chats.auto_join'):
            return

        rooms = self._settings.get('chats.rooms')
        logger.info(f"automatically rejoining {len(rooms)} rooms")
        await self._network.send_server_messages(
            *[ChatJoinRoom.Request(room) for room in rooms]
        )

    async def search_room(self, room: str, query: str) -> SearchRequest:
        """Performs a search query on all users in a room"""
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            ChatRoomSearch.Request(room, ticket, query)
        )
        self._state.search_queries[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.ROOM,
            room=room
        )
        return self._state.search_queries[ticket]

    async def search_user(self, username: str, query: str) -> SearchRequest:
        """Performs a search query on a user"""
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            UserSearch.Request(username, ticket, query)
        )
        self._state.search_queries[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.USER,
            username=username
        )
        return self._state.search_queries[ticket]

    async def search(self, query: str) -> SearchRequest:
        """Performs a global search query"""
        ticket = next(self._ticket_generator)

        await self._network.send_server_messages(
            FileSearch.Request(ticket, query)
        )
        self._state.search_queries[ticket] = SearchRequest(
            ticket=ticket,
            query=query,
            search_type=SearchType.NETWORK
        )
        return self._state.search_queries[ticket]

    async def add_user(self, username: str) -> User:
        """Request the server to track the user. This is similar to `track_user`
        except that this method waits for a response. This method will also set
        `is_tracking` on the user

        :raise asyncio.TimeoutError: raised when the timeout is reached before a
            response is received
        :raise NoSuchUserError: raised when user does not exist
        :return: `User` object
        """
        user = self._state.get_or_create_user(username)

        await self._network.send_server_messages(AddUser.Request(username))
        user.is_tracking = True

    async def get_user_stats(self, username: str):
        await self._network.send_server_messages(GetUserStats.Request(username))

    async def get_user_status(self, username: str):
        await self._network.send_server_messages(GetUserStatus.Request(username))

    async def get_room_list(self):
        """Request the list of chat rooms from the server"""
        await self._network.send_server_messages(RoomList.Request())

    async def join_room(self, room: str, private: bool = False):
        await self._network.send_server_messages(
            ChatJoinRoom.Request(room, is_private=private)
        )

    async def leave_room(self, room: str):
        await self._network.send_server_messages(ChatLeaveRoom.Request(room))

    async def add_user_to_room(self, room: str, username: str):
        """Adds a user to a private room"""
        await self._network.send_server_messages(
            PrivateRoomAddUser.Request(room=room, username=username)
        )

    async def remove_user_from_room(self, room: str, username: str):
        """Removes a user from a private room"""
        await self._network.send_server_messages(
            PrivateRoomRemoveUser.Request(room=room, username=username)
        )

    async def grant_operator(self, room: str, username: str):
        """Grant operator privileges to the given `username` in `room`. This is
        only applicable to private rooms
        """
        await self._network.send_server_messages(
            PrivateRoomAddOperator.Request(room=room, username=username)
        )

    async def revoke_operator(self, room: str, username: str):
        await self._network.send_server_messages(
            PrivateRoomRemoveOperator.Request(room=room, username=username)
        )

    async def set_room_ticker(self, room: str, ticker: str):
        # No need to update the ticker in the model, a ChatRoomTickerAdded will
        # be sent back to us
        await self._network.send_server_messages(
            ChatRoomTickerSet.Request(room=room, ticker=ticker)
        )

    async def send_private_message(self, username: str, message: str):
        await self._network.send_server_messages(
            ChatPrivateMessage.Request(username, message)
        )

    async def send_room_message(self, room: str, message: str):
        await self._network.send_server_messages(
            ChatRoomMessage.Request(room, message)
        )

    async def drop_room_ownership(self, room: str):
        """Drop ownership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropOwnership.Request(room)
        )

    async def drop_room_membership(self, room: str):
        """Drop membership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropMembership.Request(room)
        )

    async def get_peer_address(self, username: str):
        """Requests the IP address/port of the peer from the server

        :param username: username of the peer
        """
        await self._network.send_server_messages(
            GetPeerAddress.Request(username)
        )

    @on_message(Login.Response)
    async def _on_login(self, message: Login.Response, connection):
        if not message.success:
            logger.error(f"failed to login, reason: {message.reason!r}")
            await self._event_bus.emit(
                LoginEvent(is_success=False, reason=message.reason))
            return

        logger.info(f"successfully logged on, greeting : {message.greeting!r}")

        self._network.queue_server_messages(
            CheckPrivileges.Request(),
            SetListenPort.Request(
                self._settings.get('network.listening_port'),
                obfuscated_port_amount=1,
                obfuscated_port=self._settings.get('network.listening_port') + 1
            ),
            SetStatus.Request(UserStatus.ONLINE.value),
            TogglePrivateRooms.Request(self._settings.get('chats.private_room_invites'))
        )

        await self.report_shares()
        await self.track_user(self._settings.get('credentials.username'))

        # Perform AddUser for all in the friendlist
        await self.track_friends()

        # Auto-join rooms
        await self.auto_join_rooms()

        await self._internal_event_bus.emit(LoginSuccessEvent())
        await self._event_bus.emit(
            LoginEvent(is_success=True, greeting=message.greeting))

    @on_message(Kicked.Response)
    async def _on_kicked(self, message: Kicked.Response, connection):
        await self._event_bus.emit(KickedEvent())

    @on_message(ChatRoomMessage.Response)
    async def _on_chat_room_message(self, message: ChatRoomMessage.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)
        room_message = RoomMessage(
            timestamp=int(time.time()),
            room=room,
            user=user,
            message=message.message
        )

        await self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(ChatUserJoinedRoom.Response)
    async def _on_user_joined_room(self, message: ChatUserJoinedRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.avg_speed = message.user_data.avg_speed
        user.downloads = message.user_data.download_num
        user.files = message.user_data.file_count
        user.directories = message.user_data.dir_count
        user.slots_free = message.slots_free
        user.country = message.country_code

        room = self._state.get_or_create_room(message.room)
        room.add_user(user)

        await self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))
        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(ChatUserLeftRoom.Response)
    async def _on_user_left_room(self, message: ChatUserLeftRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)

        room.remove_user(user)

        await self._event_bus.emit(UserLeftRoomEvent(room, user))

    @on_message(ChatJoinRoom.Response)
    async def _on_join_room(self, message: ChatJoinRoom.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = True

        for idx, name in enumerate(message.users):
            user_data = message.users_data[idx]

            user = self._state.get_or_create_user(name)
            user.status = UserStatus(message.users_status[idx])
            user.avg_speed = user_data.avg_speed
            user.downloads = user_data.download_num
            user.files = user_data.file_count
            user.directories = user_data.dir_count
            user.country = message.users_countries[idx]
            user.slots_free = message.users_slots_free[idx]

            room.add_user(user)
            await self._event_bus.emit(UserInfoEvent(user))

        if message.owner:
            room.owner = self._state.get_or_create_user(message.owner)
        for operator in message.operators or []:
            room.add_operator(self._state.get_or_create_user(operator))

        await self._event_bus.emit(RoomJoinedEvent(room=room))

    @on_message(ChatLeaveRoom.Response)
    async def _on_leave_room(self, message: ChatLeaveRoom.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = False

        await self._event_bus.emit(RoomLeftEvent(room=room))

    @on_message(ChatRoomTickers.Response)
    async def _on_chat_room_tickers(self, message: ChatRoomTickers.Response, connection):
        room = self._state.get_or_create_room(message.room)
        tickers = {}
        for ticker in message.tickers:
            self._state.get_or_create_user(ticker.username)
            tickers[ticker.username] = ticker.ticker

        # Just replace all tickers instead of modifying the existing dict
        room.tickers = tickers

        await self._event_bus.emit(RoomTickersEvent(room, tickers))

    @on_message(ChatRoomTickerAdded.Response)
    async def _on_chat_room_ticker_added(self, message: ChatRoomTickerAdded.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        room.tickers[user.name] = message.ticker

        await self._event_bus.emit(RoomTickerAddedEvent(room, user, message.ticker))

    @on_message(ChatRoomTickerRemoved.Response)
    async def _on_chat_room_ticker_removed(self, message: ChatRoomTickerRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        try:
            del room.tickers[user.name]
        except KeyError:
            logger.warning(
                f"attempted to remove room ticker for user {user.name} in room {room.name} "
                "but it wasn't present")

        await self._event_bus.emit(RoomTickerRemovedEvent(room, user))

    @on_message(TogglePrivateRooms.Response)
    async def _on_private_room_toggle(self, message, connection):
        logger.debug(f"private rooms enabled : {message.enabled}")

    @on_message(PrivateRoomAdded.Response)
    async def _on_private_room_added(self, message: PrivateRoomAdded.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        user = self._state.get_or_create_user(self._settings.get('credentials.username'))
        room.add_member(user)

        await self._event_bus.emit(AddedToPrivateRoomEvent(room))

    @on_message(PrivateRoomRemoved.Response)
    async def _on_private_room_removed(self, message: PrivateRoomRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        user = self._state.get_or_create_user(self._settings.get('credentials.username'))
        room.remove_member(user)

        await self._event_bus.emit(RemovedFromPrivateRoomEvent(room))

    @on_message(PrivateRoomUsers.Response)
    async def _on_private_room_users(self, message: PrivateRoomUsers.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        for username in message.usernames:
            room.add_member(self._state.get_or_create_user(username))

    @on_message(PrivateRoomAddUser.Response)
    async def _on_private_room_add_user(self, message: PrivateRoomAddUser.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        user = self._state.get_or_create_user(message.username)

        room.add_user(user)

    @on_message(PrivateRoomOperators.Response)
    async def _on_private_room_operators(self, message: PrivateRoomOperators.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        for operator in message.usernames:
            room.add_operator(self._state.get_or_create_user(operator))

    @on_message(PrivateRoomOperatorAdded.Response)
    async def _on_private_room_operator_added(self, message: PrivateRoomOperatorAdded.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        room.is_operator = True

    @on_message(PrivateRoomOperatorRemoved.Response)
    async def _on_private_room_operator_removed(self, message: PrivateRoomOperatorRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        room.is_operator = False

    @on_message(PrivateRoomAddOperator.Response)
    async def _on_private_room_add_operator(self, message: PrivateRoomAddOperator.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        user = self._state.get_or_create_user(message.username)
        room.add_operator(user)

    @on_message(PrivateRoomRemoveOperator.Response)
    async def _on_private_room_remove_operators(self, message: PrivateRoomRemoveOperator.Response, connection):
        room = self._state.get_or_create_room(message.room, private=True)
        user = self._state.get_or_create_user(message.username)
        room.remove_operator(user)

    @on_message(ChatPrivateMessage.Response)
    async def _on_private_message(self, message: ChatPrivateMessage.Response, connection):
        user = self._state.get_or_create_user(message.username)
        chat_message = ChatMessage(
            id=message.chat_id,
            timestamp=message.timestamp,
            user=user,
            message=message.message,
            is_admin=message.is_admin
        )
        self._state.private_messages[message.chat_id] = chat_message

        await self._network.send_server_messages(
            ChatAckPrivateMessage.Request(message.chat_id)
        )

        if message.is_admin and message.username.lower() == 'server':
            await self._event_bus.emit(ServerMessageEvent(message.message))

        await self._event_bus.emit(PrivateMessageEvent(user, chat_message))

    # State related messages
    @on_message(CheckPrivileges.Response)
    async def _on_check_privileges(self, message: CheckPrivileges.Response, connection):
        self._state.privileges_time_left = message.time_left

    @on_message(RoomList.Response)
    async def _on_room_list(self, message: RoomList.Response, connection):
        me = self._state.get_or_create_user(self._settings.get('credentials.username'))
        for idx, room_name in enumerate(message.rooms):
            room = self._state.get_or_create_room(room_name, private=False)
            room.user_count = message.rooms_user_count[idx]

        for idx, room_name in enumerate(message.rooms_private_owned):
            room = self._state.get_or_create_room(room_name, private=True)
            room.add_member(me)
            room.user_count = message.rooms_private_owned_user_count[idx]
            room.owner = me

        for idx, room_name in enumerate(message.rooms_private):
            room = self._state.get_or_create_room(room_name, private=True)
            room.add_member(me)
            room.user_count = message.rooms_private_user_count[idx]

        for room_name in message.rooms_private_operated:
            room = self._state.get_or_create_room(room_name, private=True)
            room.add_operator(me)
            room.is_operator = True

        await self._event_bus.emit(RoomListEvent(rooms=self._state.rooms.values()))

    @on_message(ParentMinSpeed.Response)
    async def _on_parent_min_speed(self, message: ParentMinSpeed.Response, connection):
        self._state.parent_min_speed = message.speed

    @on_message(ParentSpeedRatio.Response)
    async def _on_parent_speed_ratio(self, message: ParentSpeedRatio.Response, connection):
        self._state.parent_speed_ratio = message.ratio

    @on_message(MinParentsInCache.Response)
    async def _on_min_parents_in_cache(self, message: MinParentsInCache.Response, connection):
        self._state.min_parents_in_cache = message.amount

    @on_message(DistributedAliveInterval.Response)
    async def _on_ditributed_alive_interval(self, message: DistributedAliveInterval.Response, connection):
        self._state.distributed_alive_interval = message.interval

    @on_message(ParentInactivityTimeout.Response)
    async def _on_parent_inactivity_timeout(self, message: ParentInactivityTimeout.Response, connection):
        self._state.parent_inactivity_timeout = message.timeout

    @on_message(SearchInactivityTimeout.Response)
    async def _on_search_inactivity_timeout(self, message: SearchInactivityTimeout.Response, connection):
        self._state.search_inactivity_timeout = message.timeout

    @on_message(PrivilegedUsers.Response)
    async def _on_privileged_users(self, message: PrivilegedUsers.Response, connection):
        for username in message.users:
            user = self._state.get_or_create_user(username)
            user.privileged = True

    @on_message(AddPrivilegedUser.Response)
    async def _on_add_privileged_user(self, message: AddPrivilegedUser.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.privileged = True

    @on_message(WishlistInterval.Response)
    async def _on_wish_list_interval(self, message: WishlistInterval.Response, connection):
        self._state.wishlist_interval = message.interval
        self._cancel_wishlist_task()

        self._wishlist_task = asyncio.create_task(
            self._wishlist_job(message.interval),
            name=f'wishlist-job-{task_counter()}'
        )

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection):
        if message.exists:
            user = self._state.get_or_create_user(message.username)
            user.name = message.username
            user.status = UserStatus(message.status)
            user.avg_speed = message.avg_speed
            user.downloads = message.download_num
            user.files = message.file_count
            user.directories = message.dir_count
            user.country = message.country_code

            await self._event_bus.emit(UserInfoEvent(user))

    @on_message(GetUserStatus.Response)
    async def _on_get_user_status(self, message: GetUserStatus.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.privileged = message.privileged

        await self._event_bus.emit(UserStatusEvent(user))

    @on_message(GetUserStats.Response)
    async def _on_get_user_stats(self, message: GetUserStats.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.avg_speed = message.avg_speed
        user.downloads = message.download_num
        user.files = message.file_count
        user.directories = message.dir_count

        await self._event_bus.emit(UserInfoEvent(user))

    # Job methods

    async def _ping_job(self):
        while True:
            await asyncio.sleep(SERVER_PING_INTERVAL)
            try:
                await self.send_ping()
            except Exception as exc:
                logger.warning(f"failed to ping server. exception={exc!r}")

    def _cancel_ping_task(self):
        if self._ping_task is not None:
            self._ping_task.cancel()
            self._ping_task = None

    async def _connection_watchdog_job(self):
        """Reconnects to the server if it is closed. This should be started as a
        task and should be cancelled upon request.
        """
        while True:
            await asyncio.sleep(0.5)
            if self._network.server.state == ConnectionState.CLOSED:
                logger.info("will attempt to reconnect to server in 5 seconds")
                await asyncio.sleep(5)
                await self.reconnect()

    async def _cancel_connection_watchdog_task(self):
        if self._connection_watchdog_task is not None:
            self._connection_watchdog_task.cancel()
            self._connection_watchdog_task = None

    async def _wishlist_job(self, interval: int):
        while True:
            items = self._settings.get('search.wishlist')

            # Remove all current wishlist searches
            self._state.search_queries = {
                ticket: qry for ticket, qry in self._state.search_queries.items()
                if qry.search_type != SearchType.WISHLIST
            }

            logger.info(f"starting wishlist search of {len(items)} items")
            # Recreate
            for item in items:
                if not item['enabled']:
                    continue

                ticket = next(self._ticket_generator)
                self._state.search_queries[ticket] = SearchRequest(
                    ticket,
                    item['query'],
                    search_type=SearchType.WISHLIST
                )
                self._network.queue_server_messages(
                    WishlistSearch.Request(ticket, item['query'])
                )

            await asyncio.sleep(interval)

    def _cancel_wishlist_task(self):
        if self._wishlist_task is not None:
            self._wishlist_task.cancel()
            self._wishlist_task = None

    # Listeners

    async def _on_track_user(self, event: TrackUserEvent):
        await self.track_user(event.username)

    async def _on_untrack_user(self, event: UntrackUserEvent):
        await self.untrack_user(event.username)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            self._ping_task = asyncio.create_task(
                self._ping_job(),
                name=f'ping-task-{task_counter()}'
            )

            if self._settings.get('network.reconnect.auto'):
                if self._connection_watchdog_task is None:
                    self._connection_watchdog_task = asyncio.create_task(
                        self._connection_watchdog_job(),
                        name=f'watchdog-task-{task_counter()}'
                    )

        elif event.state == ConnectionState.CLOSING:

            self._cancel_wishlist_task()
            self._cancel_ping_task()
            # Cancel the watchdog only if we are closing up on request
            if event.close_reason == CloseReason.REQUESTED:
                self._cancel_connection_watchdog_task()

        elif event.state == ConnectionState.CLOSED:
            for user in self._state.users.values():
                user.is_tracking = False

            await self._event_bus.emit(ServerDisconnectedEvent())

    async def reconnect(self):
        try:
            await self._network.connect_server()
        except ConnectionFailedError:
            logger.warning("failed to reconnect to server")
        else:
            await self.login(
                self._settings.get('credentials.username'),
                self._settings.get('credentials.password')
            )
