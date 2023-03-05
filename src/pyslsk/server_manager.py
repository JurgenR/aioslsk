import asyncio
import logging
import time

from .network.connection import ConnectionState, ServerConnection
from .constants import SERVER_RESPONSE_TIMEOUT
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
from .exceptions import LoginFailedError, NoSuchUserError
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
    FileSearch,
    GetPeerAddress,
    GetUserStatus,
    GetUserStats,
    ToggleParentSearch,
    Login,
    MinParentsInCache,
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
    WishlistSearch,
)
from .model import ChatMessage, RoomMessage, User, UserStatus
from .network.network import Network
from .shares import SharesManager
from .search import SearchQuery
from .settings import Settings
from .state import State
from .utils import task_counter, ticket_generator


logger = logging.getLogger()


LOGIN_TIMEOUT = 30
PING_INTERVAL = 1 * 60


class ServerManager:

    def __init__(self, state: State, settings: Settings, event_bus: EventBus, internal_event_bus: InternalEventBus, shares_manager: SharesManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self.shares_manager: SharesManager = shares_manager
        self.network: Network = network

        self._ticket_generator = ticket_generator()

        self._ping_task: asyncio.Task = None
        self._wishlist_task: asyncio.Task = None

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    @property
    def connection_state(self) -> ConnectionState:
        return self.network.server.state

    async def send_ping(self):
        """Send ping to the server"""
        await self.network.queue_server_messages(Ping.Request())

    async def report_shares(self):
        """Reports the shares amount to the server"""
        dir_count, file_count = self.shares_manager.get_stats()
        logger.debug(f"reporting shares to the server (dirs={dir_count}, file_count={file_count})")
        await self.network.queue_server_messages(
            SharedFoldersFiles.Request(
                directory_count=dir_count,
                file_count=file_count
            )
        )

    async def login(self, username: str, password: str, version: int = 157):
        logger.info(f"sending request to login: username={username}, password={password}")
        expected_response = self.network.wait_for_server_message(Login.Response)
        await self.network.send_server_messages(
            Login.Request(
                username=username,
                password=password,
                client_version=version,
                md5hash=calc_md5(username + password),
                minor_version=100
            )
        )
        try:
            _, response = await asyncio.wait_for(expected_response, SERVER_RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            raise LoginFailedError("login timed out waiting for response")

        # First value indicates success
        if response.success:
            self._state.logged_in = True
            logger.info("Successfully logged on")
        else:
            logger.error(f"Failed to login, reason: {response.reason!r}")
            raise LoginFailedError(response.reason)

        # Make setup calls
        dir_count, file_count = self.shares_manager.get_stats()
        logger.debug(f"Sharing {dir_count} directories and {file_count} files")

        await self.network.queue_server_messages(
            CheckPrivileges.Request(),
            SetListenPort.Request(
                self._settings.get('network.listening_port'),
                obfuscated_port_amount=1,
                obfuscated_port=self._settings.get('network.listening_port') + 1
            ),
            SetStatus.Request(UserStatus.ONLINE.value),
            ToggleParentSearch.Request(True),
            BranchRoot.Request(self._settings.get('credentials.username')),
            BranchLevel.Request(0),
            AcceptChildren.Request(False),
            SharedFoldersFiles.Request(dir_count, file_count),
            AddUser.Request(self._settings.get('credentials.username')),
            TogglePrivateRooms.Request(self._settings.get('chats.private_room_invites'))
        )

        # Perform AddUser for all in the friendlist
        await self.network.queue_server_messages(
            *[
                AddUser.Request(friend)
                for friend in self._settings.get('users.friends')
            ]
        )

        # Auto-join rooms
        if self._settings.get('chats.auto_join'):
            rooms = self._settings.get('chats.rooms')
            logger.info(f"automatically rejoining {len(rooms)} rooms")
            await self.network.queue_server_messages(
                *[ChatJoinRoom.Request(room) for room in rooms]
            )

        await self._internal_event_bus.emit(LoginEvent(success=response.success))

    async def search(self, query: str) -> SearchQuery:
        ticket = next(self._ticket_generator)
        await self.network.queue_server_messages(
            FileSearch.Request(ticket, query)
        )
        self._state.search_queries[ticket] = SearchQuery(ticket=ticket, query=query)
        return self._state.search_queries[ticket]

    async def add_user(self, username: str) -> User:
        """Request the server to track the user

        :raise asnycio.TimeoutError: raised when the timeout is reached before a
            response is received
        :raise NoSuchUserError: raised when user does not exist
        :return: `User` object
        """
        await self.network.send_server_messages(
            AddUser.Request(username)
        )
        _, response = await asyncio.wait_for(
            self.network.wait_for_server_message(AddUser.Response, username=username),
            SERVER_RESPONSE_TIMEOUT
        )
        if not response.exists:
            raise NoSuchUserError(f"user {username} does not exist")
        else:
            return await self._handle_add_user_response(response)

    async def remove_user(self, username: str):
        await self.network.send_server_messages(
            RemoveUser.Request(username)
        )
        # Reset user status, this is needed for the transfer manager who will
        # skip attempting to transfer for offline user. But if we don't know if
        # a user is online we will never know
        user = self._state.get_or_create_user(username)
        user.status = UserStatus.UNKNOWN

    async def get_user_stats(self, username: str) -> bool:
        await self.network.send_server_messages(
            GetUserStats.Request(username)
        )
        _, response = await asyncio.wait_for(
            self.network.wait_for_server_message(GetUserStats.Response, username=username),
            SERVER_RESPONSE_TIMEOUT
        )

    async def get_user_status(self, username: str):
        await self.network.send_server_messages(
            GetUserStatus.Request(username)
        )
        _, response = await asyncio.wait_for(
            self.network.wait_for_server_message(GetUserStatus.Response, username=username),
            SERVER_RESPONSE_TIMEOUT
        )

    async def get_room_list(self):
        await self.network.send_server_messages(RoomList.Request())
        _, response = await asyncio.wait_for(
            self.network.wait_for_server_message(RoomList.Response),
            SERVER_RESPONSE_TIMEOUT
        )

    async def join_room(self, name: str):
        await self.network.send_server_messages(
            ChatJoinRoom.Request(name)
        )

    async def leave_room(self, name: str):
        await self.network.send_server_messages(
            ChatLeaveRoom.Request(name)
        )

    async def set_room_ticker(self, room_name: str, ticker: str):
        # No need to update the ticker in the model, a ChatRoomTickerAdded will
        # be sent back to us
        await self.network.send_server_messages(
            ChatRoomTickerSet.Request(room=room_name, ticker=ticker)
        )

    async def send_private_message(self, username: str, message: str):
        await self.network.send_server_messages(
            ChatPrivateMessage.Request(username, message)
        )

    async def send_room_message(self, room_name: str, message: str):
        await self.network.send_server_messages(
            ChatRoomMessage.Request(room_name, message)
        )

    async def drop_private_room_ownership(self, room_name: str):
        await self.network.send_server_messages(
            PrivateRoomDropOwnership.Request(room_name)
        )

    async def drop_private_room_membership(self, room_name: str):
        await self.network.send_server_messages(
            PrivateRoomDropMembership.Request(room_name)
        )

    async def get_peer_address(self, username: str):
        """Requests the IP address/port of the peer from the server

        :param username: username of the peer
        """
        await self.network.send_server_messages(
            GetPeerAddress.Request(username)
        )
        response = await self.network.wait_for_server_message(
            GetPeerAddress.Response, username=username)

        return response.ip, response.port, response.obfuscated_port

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
        room.messages.append(room_message)

        await self._event_bus.emit(RoomMessageEvent(room_message))

    @on_message(ChatUserJoinedRoom.Response)
    async def _on_user_joined_room(self, message: ChatUserJoinedRoom.Response, connection):
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

        await self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))

    @on_message(ChatUserLeftRoom.Response)
    async def _on_user_left_room(self, message: ChatUserLeftRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)

        await self._event_bus.emit(UserLeftRoomEvent(user=user, room=room))

    @on_message(ChatJoinRoom.Response)
    async def _on_join_room(self, message: ChatJoinRoom.Response, connection):
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

        if message.owner:
            room.owner = message.owner
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
        room = self._state.get_or_create_room(message.room)
        room.joined = True
        room.is_private = True

        await self._event_bus.emit(UserJoinedPrivateRoomEvent(room))

    @on_message(PrivateRoomRemoved.Response)
    async def _on_private_room_removed(self, message: PrivateRoomRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = False
        room.is_private = True

        await self._event_bus.emit(UserLeftPrivateRoomEvent(room))

    @on_message(PrivateRoomUsers.Response)
    async def _on_private_room_users(self, message: PrivateRoomUsers.Response, connection):
        room = self._state.get_or_create_room(message.room)
        for username in message.usernames:
            room.add_user(self._state.get_or_create_user(username))

    @on_message(PrivateRoomAddUser.Response)
    async def _on_private_room_add_user(self, message: PrivateRoomAddUser.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)

        room.add_user(user)

    @on_message(PrivateRoomOperators.Response)
    async def _on_private_room_operators(self, message: PrivateRoomOperators.Response, connection):
        room = self._state.get_or_create_room(message.room)
        for operator in message.usernames:
            room.add_operator(self._state.get_or_create_user(operator))

    @on_message(PrivateRoomOperatorAdded.Response)
    async def _on_private_room_operator_added(self, message: PrivateRoomOperatorAdded.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.is_operator = True

    @on_message(PrivateRoomOperatorRemoved.Response)
    async def _on_private_room_operator_removed(self, message: PrivateRoomOperatorRemoved.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.is_operator = False

    @on_message(PrivateRoomAddOperator.Response)
    async def _on_private_room_add_operator(self, message: PrivateRoomAddOperator.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)
        room.add_operator(user)

    @on_message(PrivateRoomRemoveOperator.Response)
    async def _on_private_room_remove_operators(self, message: PrivateRoomRemoveOperator.Response, connection):
        room = self._state.get_or_create_room(message.room)
        user = self._state.get_or_create_user(message.username)
        room.operators.remove(user)

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

        await self.network.send_server_messages(
            ChatAckPrivateMessage.Request(message.chat_id)
        )

        await self._event_bus.emit(PrivateMessageEvent(user, chat_message))

    @on_message(ServerSearchRequest.Response)
    async def _on_server_search_request(self, message: ServerSearchRequest.Response, connection):
        message_to_send = message
        for child in self._state.children:
            child.connection.queue_messages(message_to_send)

    # State related messages
    @on_message(CheckPrivileges.Response)
    async def _on_check_privileges(self, message: CheckPrivileges.Response, connection):
        self._state.privileges_time_left = message.time_left

    @on_message(RoomList.Response)
    async def _on_room_list(self, message: RoomList.Response, connection):
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
        # Cancel the current task
        if self._wishlist_task is not None:
            self._wishlist_task.cancel()

        self._wishlist_task = asyncio.create_task(
            self._wishlist_job(message.interval),
            name=f'wishlist-job-{task_counter()}'
        )

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection):
        await self._handle_add_user_response(message)

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

        await self._event_bus.emit(UserStatsEvent(user))

    async def _handle_add_user_response(self, response: AddUser.Response) -> User:
        if response.exists:
            user = self._state.get_or_create_user(response.username)
            user.name = response.username
            user.status = UserStatus(response.status)
            user.avg_speed = response.avg_speed
            user.downloads = response.download_num
            user.files = response.file_count
            user.directories = response.dir_count
            user.country = response.country_code

            await self._event_bus.emit(UserAddEvent(user))
            return user

    # Job methods

    async def _ping_job(self):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await self.network.queue_server_messages(Ping.Request())

    async def _wishlist_job(self, interval: int):
        while True:
            items = self._settings.get('search.wishlist')

            # Remove all current wishlist searches
            self._state.search_queries = {
                ticket: qry for ticket, qry in self._state.search_queries.items()
                if not qry.is_wishlist_query
            }

            logger.info(f"starting wishlist search of {len(items)} items")
            # Recreate
            for item in items:
                if not item['enabled']:
                    continue

                ticket = next(self._ticket_generator)
                self._state.search_queries[ticket] = SearchQuery(
                    ticket,
                    item['query'],
                    is_wishlist_query=True
                )
                await self.network.queue_server_messages(
                    WishlistSearch.Request(ticket, item['query'])
                )

            await asyncio.sleep(interval)

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            self._ping_task = asyncio.create_task(
                self._ping_job(), name=f'ping-task-{task_counter()}')

        elif event.state == ConnectionState.CLOSING:
            self._state.logged_in = False

            if self._wishlist_task is not None:
                self._wishlist_task.cancel()
                self._wishlist_task = None

            if self._ping_task is not None:
                self._ping_task.cancel()
                self._ping_task = None

            await self._event_bus.emit(ServerDisconnectedEvent())
