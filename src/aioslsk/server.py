import asyncio
import logging
import time
from typing import Optional, Union

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
    GlobalRecommendationsEvent,
    InternalEventBus,
    ItemRecommendationsEvent,
    KickedEvent,
    LoginEvent,
    LoginSuccessEvent,
    MessageReceivedEvent,
    PrivateMessageEvent,
    RecommendationsEvent,
    RemovedFromPrivateRoomEvent,
    RoomJoinedEvent,
    RoomLeftEvent,
    RoomListEvent,
    RoomMessageEvent,
    RoomTickerAddedEvent,
    RoomTickerRemovedEvent,
    RoomTickersEvent,
    ScanCompleteEvent,
    SimilarUsersEvent,
    ServerDisconnectedEvent,
    TrackUserEvent,
    UntrackUserEvent,
    UserInfoEvent,
    UserInterestsEvent,
    UserJoinedRoomEvent,
    UserLeftRoomEvent,
    UserStatusEvent,
)
from .exceptions import ConnectionFailedError
from .protocol.primitives import calc_md5
from .protocol.messages import (
    AddPrivilegedUser,
    AddHatedInterest,
    AddInterest,
    AddUser,
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
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetPeerAddress,
    GetRecommendations,
    GetSimilarUsers,
    GetUserInterests,
    GetUserStatus,
    GetUserStats,
    Kicked,
    Login,
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
    RemoveHatedInterest,
    RemoveInterest,
    RemoveUser,
    RoomList,
    SetListenPort,
    SetStatus,
    SharedFoldersFiles,
)
from .model import ChatMessage, RoomMessage, User, UserStatus, TrackingFlag
from .network.network import Network
from .shares.manager import SharesManager
from .settings import Settings
from .state import State
from .utils import task_counter, ticket_generator


logger = logging.getLogger(__name__)


class ServerManager:
    """Class handling server messages. This class is mostly responsible for
    messages received from the server regarding rooms, users and state variables
    """

    def __init__(
            self, state: State, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, network: Network):
        self._state: State = state
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network

        self._ticket_generator = ticket_generator()

        self._ping_task: Optional[asyncio.Task] = None
        self._post_login_task: Optional[asyncio.Task] = None
        self._connection_watchdog_task: Optional[asyncio.Task] = None

        self.MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    @property
    def connection_state(self) -> ConnectionState:
        return self._network.server_connection.state

    def register_listeners(self):
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            TrackUserEvent, self._on_track_user)
        self._internal_event_bus.register(
            UntrackUserEvent, self._on_untrack_user)

    async def send_ping(self):
        """Send ping to the server"""
        await self._network.send_server_messages(Ping.Request())

    async def report_shares(self):
        """Reports the shares amount to the server"""
        folder_count, file_count = self._shares_manager.get_stats()
        logger.debug(f"reporting shares to the server (folder_count={folder_count}, file_count={file_count})")
        await self._network.send_server_messages(
            SharedFoldersFiles.Request(
                shared_folder_count=folder_count,
                shared_file_count=file_count
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

    async def track_user(self, username: str, flag: TrackingFlag):
        """Starts tracking a user. The method sends an `AddUser` only if the
        `is_tracking` variable is set to False. Updates to the user will be
        emitted through the `UserInfoEvent` event

        :param user: user to track
        :param flag: tracking flag to add from the user
        """
        user = self._state.get_or_create_user(username)

        had_add_user_flag = user.has_add_user_flag()
        user.tracking_flags |= flag
        if not had_add_user_flag:
            await self._network.send_server_messages(AddUser.Request(username))

    async def track_friends(self):
        """Starts tracking the users defined defined in the friends list"""
        tasks = []
        for friend in self._settings.get('users.friends'):
            tasks.append(self.track_user(friend, TrackingFlag.FRIEND))

        asyncio.gather(*tasks, return_exceptions=True)

    async def untrack_user(self, user: Union[str, User], flag: TrackingFlag):
        """Removes the given flag from the user and untracks the user (send
        `RemoveUser` message) in case none of the AddUser tracking flags are
        set

        :param user: user to untrack
        :param flag: tracking flag to remove from the user
        """
        user = self._state.get_or_create_user(user)
        # Check if this is the last AddUser flag to be removed. If so send the
        # RemoveUser message
        had_user_add_flag = user.has_add_user_flag()
        user.tracking_flags &= ~flag
        if had_user_add_flag and not user.has_add_user_flag():
            await self._network.send_server_messages(RemoveUser.Request(user.name))

        # If there's no more tracking done reset the user status
        if user.tracking_flags == TrackingFlag(0):
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

    async def get_user_stats(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStats.Request(username))

    async def get_user_status(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStatus.Request(username))

    async def get_room_list(self):  # pragma: no cover
        """Request the list of chat rooms from the server"""
        await self._network.send_server_messages(RoomList.Request())

    async def join_room(self, room: str, private: bool = False):  # pragma: no cover
        await self._network.send_server_messages(
            ChatJoinRoom.Request(room, is_private=private)
        )

    async def leave_room(self, room: str):  # pragma: no cover
        await self._network.send_server_messages(ChatLeaveRoom.Request(room))

    async def add_user_to_room(self, room: str, username: str):  # pragma: no cover
        """Adds a user to a private room"""
        await self._network.send_server_messages(
            PrivateRoomAddUser.Request(room=room, username=username)
        )

    async def remove_user_from_room(self, room: str, username: str):  # pragma: no cover
        """Removes a user from a private room"""
        await self._network.send_server_messages(
            PrivateRoomRemoveUser.Request(room=room, username=username)
        )

    async def grant_operator(self, room: str, username: str):  # pragma: no cover
        """Grant operator privileges to the given `username` in `room`. This is
        only applicable to private rooms
        """
        await self._network.send_server_messages(
            PrivateRoomAddOperator.Request(room=room, username=username)
        )

    async def revoke_operator(self, room: str, username: str):  # pragma: no cover
        await self._network.send_server_messages(
            PrivateRoomRemoveOperator.Request(room=room, username=username)
        )

    async def set_room_ticker(self, room: str, ticker: str):  # pragma: no cover
        # No need to update the ticker in the model, a ChatRoomTickerAdded will
        # be sent back to us
        await self._network.send_server_messages(
            ChatRoomTickerSet.Request(room=room, ticker=ticker)
        )

    async def send_private_message(self, username: str, message: str):  # pragma: no cover
        await self._network.send_server_messages(
            ChatPrivateMessage.Request(username, message)
        )

    async def send_room_message(self, room: str, message: str):  # pragma: no cover
        await self._network.send_server_messages(
            ChatRoomMessage.Request(room, message)
        )

    async def drop_room_ownership(self, room: str):  # pragma: no cover
        """Drop ownership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropOwnership.Request(room)
        )

    async def drop_room_membership(self, room: str):  # pragma: no cover
        """Drop membership of the private room"""
        await self._network.send_server_messages(
            PrivateRoomDropMembership.Request(room)
        )

    async def get_peer_address(self, username: str):  # pragma: no cover
        """Requests the IP address/port of the peer from the server

        :param username: username of the peer
        """
        await self._network.send_server_messages(
            GetPeerAddress.Request(username)
        )

    # Recommendations / interests
    async def get_recommendations(self):  # pragma: no cover
        await self._network.send_server_messages(
            GetRecommendations.Request()
        )

    async def get_global_recommendations(self):  # pragma: no cover
        await self._network.send_server_messages(
            GetGlobalRecommendations.Request()
        )

    async def get_item_recommendations(self, item: str):  # pragma: no cover
        await self._network.send_server_messages(
            GetItemRecommendations.Request(item=item)
        )

    async def get_user_interests(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(
            GetUserInterests.Request(username)
        )

    async def add_hated_interest(self, hated_interest: str):  # pragma: no cover
        await self._network.send_server_messages(
            AddHatedInterest.Request(hated_interest)
        )

    async def remove_hated_interest(self, hated_interest: str):  # pragma: no cover
        await self._network.send_server_messages(
            RemoveHatedInterest.Request(hated_interest)
        )

    async def add_interest(self, interest: str):  # pragma: no cover
        await self._network.send_server_messages(
            AddInterest.Request(interest)
        )

    async def remove_interest(self, interest: str):  # pragma: no cover
        await self._network.send_server_messages(
            RemoveInterest.Request(interest)
        )

    async def get_similar_users(self, item: Optional[str] = None):
        """Get similar users for an item or globally"""
        if item:
            message = GetItemSimilarUsers.Request(item)
        else:
            message = GetSimilarUsers.Request()

        await self._network.send_server_messages(message)

    @on_message(Login.Response)
    async def _on_login(self, message: Login.Response, connection):
        if not message.success:
            logger.error(f"failed to login, reason: {message.reason!r}")
            await self._event_bus.emit(
                LoginEvent(is_success=False, reason=message.reason))
            return

        logger.info(f"successfully logged on, greeting : {message.greeting!r}")

        port, obfuscated_port = self._network.get_listening_ports()

        self._network.queue_server_messages(
            CheckPrivileges.Request(),
            SetListenPort.Request(
                port,
                obfuscated_port_amount=1 if obfuscated_port else 0,
                obfuscated_port=obfuscated_port
            ),
            SetStatus.Request(UserStatus.ONLINE.value),
            TogglePrivateRooms.Request(self._settings.get('chats.private_room_invites'))
        )

        await self.report_shares()
        await self.track_user(
            self._settings.get('credentials.username'), TrackingFlag.FRIEND)

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
        user.update_from_user_stats(message.user_stats)
        user.slots_free = message.slots_free
        user.country = message.country_code
        await self.track_user(user.name, TrackingFlag.ROOM_USER)

        room = self._state.get_or_create_room(message.room)
        room.add_user(user)

        await self._event_bus.emit(UserJoinedRoomEvent(user=user, room=room))
        await self._event_bus.emit(UserInfoEvent(user))

    @on_message(ChatUserLeftRoom.Response)
    async def _on_user_left_room(self, message: ChatUserLeftRoom.Response, connection):
        user = self._state.get_or_create_user(message.username)
        room = self._state.get_or_create_room(message.room)

        # Remove tracking flag if there's no room left which the user is in
        for joined_room in self._state.get_joined_rooms():
            if joined_room != room and user in joined_room.users:
                break
        else:
            await self.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.remove_user(user)

        await self._event_bus.emit(UserLeftRoomEvent(room, user))

    @on_message(ChatJoinRoom.Response)
    async def _on_join_room(self, message: ChatJoinRoom.Response, connection):
        room = self._state.get_or_create_room(message.room)
        room.joined = True

        for idx, name in enumerate(message.users):
            user = self._state.get_or_create_user(name)
            user.status = UserStatus(message.users_status[idx])
            user.update_from_user_stats(message.users_stats[idx])
            user.country = message.users_countries[idx]
            user.slots_free = message.users_slots_free[idx]
            await self.track_user(user.name, TrackingFlag.ROOM_USER)

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

        # Remove tracking flag from users (that are no longer in other rooms)
        for user in room.users:
            for joined_room in self._state.get_joined_rooms():
                if joined_room == room:
                    continue
                if user in joined_room.users:
                    break
            else:
                await self.untrack_user(user.name, TrackingFlag.ROOM_USER)

        room.joined = False
        room.users = []

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

        await self._network.send_server_messages(
            ChatAckPrivateMessage.Request(message.chat_id)
        )
        await self._event_bus.emit(PrivateMessageEvent(chat_message))

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

    @on_message(PrivilegedUsers.Response)
    async def _on_privileged_users(self, message: PrivilegedUsers.Response, connection):
        for username in message.users:
            user = self._state.get_or_create_user(username)
            user.privileged = True

    @on_message(AddPrivilegedUser.Response)
    async def _on_add_privileged_user(self, message: AddPrivilegedUser.Response, connection):
        user = self._state.get_or_create_user(message.username)
        user.privileged = True

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection):
        if message.exists:
            user = self._state.get_or_create_user(message.username)
            user.name = message.username
            user.status = UserStatus(message.status)
            user.update_from_user_stats(message.user_stats)
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
        user.update_from_user_stats(message.user_stats)

        await self._event_bus.emit(UserInfoEvent(user))

    # Recommendations / interests
    @on_message(GetRecommendations.Response)
    async def _on_get_recommendations(self, message: GetRecommendations.Response, connection):
        await self._event_bus.emit(
            RecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetGlobalRecommendations.Response)
    async def _on_get_global_recommendations(self, message: GetGlobalRecommendations.Response, connection):
        await self._event_bus.emit(
            GlobalRecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetItemRecommendations.Response)
    async def _on_get_item_recommendations(self, message: GetItemRecommendations.Response, connection):
        await self._event_bus.emit(
            ItemRecommendationsEvent(
                item=message.item,
                recommendations=message.recommendations
            )
        )

    @on_message(GetUserInterests.Response)
    async def _on_get_user_interests(self, message: GetUserInterests.Response, connection):
        await self._event_bus.emit(
            UserInterestsEvent(
                user=self._state.get_or_create_user(message.username),
                interests=message.interests,
                hated_interests=message.hated_interests
            )
        )

    @on_message(GetSimilarUsers.Response)
    async def _on_get_similar_users(self, message: GetSimilarUsers.Response, connection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                users=[
                    self._state.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

    @on_message(GetItemSimilarUsers.Response)
    async def _on_get_item_similar_users(self, message: GetItemSimilarUsers.Response, connection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                item=message.item,
                users=[
                    self._state.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

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
        timeout = self._settings.get('network.reconnect.timeout')
        logger.info("starting server connection watchdog")
        while True:
            await asyncio.sleep(0.5)
            if self._network.server_connection.state == ConnectionState.CLOSED:
                logger.info(f"will attempt to reconnect to server in {timeout} seconds")
                await asyncio.sleep(timeout)
                await self._reconnect()

    def _cancel_connection_watchdog_task(self):
        if self._connection_watchdog_task is not None:
            self._connection_watchdog_task.cancel()
            self._connection_watchdog_task = None

    # Listeners

    async def _on_track_user(self, event: TrackUserEvent):
        await self.track_user(event.username, event.flag)

    async def _on_untrack_user(self, event: UntrackUserEvent):
        await self.untrack_user(event.username, event.flag)

    async def _on_scan_completed(self, event: ScanCompleteEvent):
        await self.report_shares()

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

            self._cancel_ping_task()
            # When `disconnect` is called on the connection it will always first
            # go into the CLOSING state. The watchdog will only attempt to
            # reconnect if the server is in CLOSED state. So the code needs to
            # make a decision here whether we want to reconnect or not before it
            # goes into CLOSED state.
            # Cancel the watchdog only if we are closing up on request or the
            # server sends an EOF. The server sends an EOF as soon as you are
            # connected if your IP address is banned, this happens when you make
            # too many connections in a short period of time. Making any more
            # connections will only extend your ban period. Possibly the server
            # will also EOF when the login message is not sent
            if event.close_reason == CloseReason.REQUESTED:
                self._cancel_connection_watchdog_task()

            elif event.close_reason == CloseReason.EOF:
                logger.warning(
                    "server closed connection, will not attempt to reconnect")
                self._cancel_connection_watchdog_task()

        elif event.state == ConnectionState.CLOSED:
            self._state.reset_users_and_rooms()

            await self._event_bus.emit(ServerDisconnectedEvent())

    async def _reconnect(self):
        """Reconnect after disconnecting"""
        try:
            await self._network.connect_server()
        except ConnectionFailedError:
            logger.warning("failed to reconnect to server")
        else:
            await self.login(
                self._settings.get('credentials.username'),
                self._settings.get('credentials.password')
            )
