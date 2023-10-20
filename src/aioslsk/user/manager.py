import asyncio
import logging
from typing import Dict, Union

from ..network.connection import ConnectionState, ServerConnection
from ..events import (
    build_message_map,
    on_message,
    ConnectionStateChangedEvent,
    EventBus,
    GlobalRecommendationsEvent,
    InternalEventBus,
    ItemRecommendationsEvent,
    KickedEvent,
    LoginEvent,
    MessageReceivedEvent,
    PrivateMessageEvent,
    PrivilegedUsersEvent,
    PrivilgedUserAddedEvent,
    RecommendationsEvent,
    ScanCompleteEvent,
    SimilarUsersEvent,
    ServerDisconnectedEvent,
    TrackUserEvent,
    UntrackUserEvent,
    UserInfoEvent,
    UserInterestsEvent,
    UserStatusEvent,
)
from ..exceptions import ConnectionFailedError
from ..protocol.primitives import calc_md5
from ..protocol.messages import (
    AddPrivilegedUser,
    AddHatedInterest,
    AddInterest,
    AddUser,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
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
    PrivilegedUsers,
    RemoveHatedInterest,
    RemoveInterest,
    RemoveUser,
    SetStatus,
)
from .model import ChatMessage, User, UserStatus, TrackingFlag
from ..network.network import Network
from ..settings import Settings


logger = logging.getLogger(__name__)


class UserManager:
    """Class handling server messages. users"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network

        self.MESSAGE_MAP = build_message_map(self)

        self.users: Dict[str, User] = {}

        self.register_listeners()

    def register_listeners(self):
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)

    def get_or_create_user(self, user: Union[str, User]) -> User:
        """Retrieves the user with given name or return the existing `User`
        object. If a `User` object is passed in it will be checked if it exists,
        otherwise it will get added
        """
        if isinstance(user, User):
            if user in self.users.values():
                return user
            else:
                self.users[user.name] = user
                return user

        try:
            return self.users[user]
        except KeyError:
            user_object = User(name=user)
            self.users[user] = user_object
            return user_object

    def reset_users(self):
        """Performs a reset on all users"""
        self.users = {}

    async def track_user(self, username: str, flag: TrackingFlag):
        """Starts tracking a user. The method sends an `AddUser` only if the
        `is_tracking` variable is set to False. Updates to the user will be
        emitted through the `UserInfoEvent` event

        :param user: user to track
        :param flag: tracking flag to add from the user
        """
        user = self.get_or_create_user(username)

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
        user = self.get_or_create_user(user)
        # Check if this is the last AddUser flag to be removed. If so send the
        # RemoveUser message
        had_user_add_flag = user.has_add_user_flag()
        user.tracking_flags &= ~flag
        if had_user_add_flag and not user.has_add_user_flag():
            await self._network.send_server_messages(RemoveUser.Request(user.name))

        # If there's no more tracking done reset the user status
        if user.tracking_flags == TrackingFlag(0):
            user.status = UserStatus.UNKNOWN

    async def get_user_stats(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStats.Request(username))

    async def get_user_status(self, username: str):  # pragma: no cover
        await self._network.send_server_messages(GetUserStatus.Request(username))

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

    async def get_similar_users(self):
        """Get similar users"""
        await self._network.send_server_messages(GetSimilarUsers.Request())

    async def get_similar_users_for_item(self, item: str):
        """Get similar users for an item"""
        await self._network.send_server_messages(
            GetItemSimilarUsers.Request(item)
        )

    async def get_similar_users(self, response=True):
        if response:
            response_future = self._network.create_server_response_future(
                GetSimilarUsers.Response
            )

            try:
                await self._network.send_server_messages(GetSimilarUsers.Request())
            except Exception:
                response_future.cancel()
                raise

            _, response = await asyncio.wait_for(response_future, timeout=10)
            return list(map(self.get_or_create_user, response.usernames))
            return UserStatus(response.status)
        else:
            await self._network.send_server_messages(GetSimilarUsers.Request())

    async def get_user_status(self, username: str, response=True):
        if response:
            response_future = self._network.create_server_response_future(
                GetUserStatus.Response,
                fields={
                    'username': username
                }
            )

            try:
                await self._network.send_server_messages(GetUserStatus.Request(username))
            except Exception:
                response_future.cancel()
                raise

            _, response = await asyncio.wait_for(response_future, timeout=10)
            return UserStatus(response.status)
        else:
            await self._network.send_server_messages(GetUserStatus.Request(username))

    @on_message(Login.Response)
    async def _on_login(self, message: Login.Response, connection: ServerConnection):
        if not message.success:
            logger.error(f"failed to login, reason: {message.reason!r}")
            await self._event_bus.emit(
                LoginEvent(is_success=False, reason=message.reason))
            return

        logger.info(f"successfully logged on, greeting : {message.greeting!r}")

        await self._network.send_server_messages(
            CheckPrivileges.Request(),
            SetStatus.Request(UserStatus.ONLINE.value),
        )

        await self.track_user(
            self._settings.get('credentials.username'), TrackingFlag.FRIEND)

        # Perform AddUser for all in the friendlist
        await self.track_friends()

        await self._event_bus.emit(
            LoginEvent(is_success=True, greeting=message.greeting))

    @on_message(Kicked.Response)
    async def _on_kicked(self, message: Kicked.Response, connection: ServerConnection):
        await self._event_bus.emit(KickedEvent())

    @on_message(ChatPrivateMessage.Response)
    async def _on_private_message(self, message: ChatPrivateMessage.Response, connection: ServerConnection):
        user = self.get_or_create_user(message.username)
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
    async def _on_check_privileges(self, message: CheckPrivileges.Response, connection: ServerConnection):
        self.privileges_time_left = message.time_left

    @on_message(PrivilegedUsers.Response)
    async def _on_privileged_users(self, message: PrivilegedUsers.Response, connection: ServerConnection):
        priv_users = []
        for username in message.users:
            user = self.get_or_create_user(username)
            user.privileged = True
            priv_users.append(user)

        for unpriv in set(self.users.keys()) - set(message.users):
            self.get_or_create_user(unpriv).privileged = False

        await self._event_bus.emit(PrivilegedUsersEvent(priv_users))

    @on_message(AddPrivilegedUser.Response)
    async def _on_add_privileged_user(self, message: AddPrivilegedUser.Response, connection: ServerConnection):
        user = self.get_or_create_user(message.username)
        user.privileged = True

        await self._event_bus.emit(PrivilgedUserAddedEvent(user))

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection: ServerConnection):
        if message.exists:
            user = self.get_or_create_user(message.username)
            user.name = message.username
            user.status = UserStatus(message.status)
            user.update_from_user_stats(message.user_stats)
            user.country = message.country_code

            await self._event_bus.emit(UserInfoEvent(user))

    @on_message(GetUserStatus.Response)
    async def _on_get_user_status(self, message: GetUserStatus.Response, connection: ServerConnection):
        user = self.get_or_create_user(message.username)
        user.status = UserStatus(message.status)
        user.privileged = message.privileged

        await self._event_bus.emit(UserStatusEvent(user))

    @on_message(GetUserStats.Response)
    async def _on_get_user_stats(self, message: GetUserStats.Response, connection: ServerConnection):
        user = self.get_or_create_user(message.username)
        user.update_from_user_stats(message.user_stats)

        await self._event_bus.emit(UserInfoEvent(user))

    # Recommendations / interests
    @on_message(GetRecommendations.Response)
    async def _on_get_recommendations(self, message: GetRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            RecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetGlobalRecommendations.Response)
    async def _on_get_global_recommendations(self, message: GetGlobalRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            GlobalRecommendationsEvent(
                recommendations=message.recommendations,
                unrecommendations=message.unrecommendations
            )
        )

    @on_message(GetItemRecommendations.Response)
    async def _on_get_item_recommendations(self, message: GetItemRecommendations.Response, connection: ServerConnection):
        await self._event_bus.emit(
            ItemRecommendationsEvent(
                item=message.item,
                recommendations=message.recommendations
            )
        )

    @on_message(GetUserInterests.Response)
    async def _on_get_user_interests(self, message: GetUserInterests.Response, connection: ServerConnection):
        await self._event_bus.emit(
            UserInterestsEvent(
                user=self.get_or_create_user(message.username),
                interests=message.interests,
                hated_interests=message.hated_interests
            )
        )

    @on_message(GetSimilarUsers.Response)
    async def _on_get_similar_users(self, message: GetSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                users=[
                    self.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

    @on_message(GetItemSimilarUsers.Response)
    async def _on_get_item_similar_users(self, message: GetItemSimilarUsers.Response, connection: ServerConnection):
        await self._event_bus.emit(
            SimilarUsersEvent(
                item=message.item,
                users=[
                    self.get_or_create_user(user.username)
                    for user in message.users
                ]
            )
        )

    # Listeners

    async def _on_track_user(self, event: TrackUserEvent):
        await self.track_user(event.username, event.flag)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CONNECTED:
            pass

        elif event.state == ConnectionState.CLOSED:
            self.reset_users()

            await self._event_bus.emit(ServerDisconnectedEvent())
