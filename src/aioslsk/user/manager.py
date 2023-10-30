import asyncio
import logging
from typing import Dict, List, Optional, Union

from ..base_manager import BaseManager
from ..network.connection import ConnectionState, ServerConnection
from ..events import (
    build_message_map,
    on_message,
    AdminMessageEvent,
    ConnectionStateChangedEvent,
    EventBus,
    InternalEventBus,
    KickedEvent,
    MessageReceivedEvent,
    PrivateMessageEvent,
    PrivilegedUsersEvent,
    PrivilegedUserAddedEvent,
    UserInfoEvent,
    UserStatusEvent,
    SessionInitializedEvent,
    SessionDestroyedEvent,
)
from ..protocol.messages import (
    AddPrivilegedUser,
    AddUser,
    AdminMessage,
    ChatPrivateMessage,
    ChatAckPrivateMessage,
    CheckPrivileges,
    GetUserStatus,
    GetUserStats,
    Kicked,
    PrivilegedUsers,
    RemoveUser,
    SetStatus,
)
from .model import ChatMessage, User, UserStatus, TrackingFlag
from ..network.network import Network
from ..settings import Settings
from ..session import Session


logger = logging.getLogger(__name__)


class UserManager(BaseManager):
    """Class handling users"""

    def __init__(
            self, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._network: Network = network

        self._session: Optional[Session] = None

        self._MESSAGE_MAP = build_message_map(self)

        self.users: Dict[str, User] = {}

        self.register_listeners()

    def register_listeners(self):
        self._internal_event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._internal_event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)
        self._internal_event_bus.register(
            SessionDestroyedEvent, self._on_session_destroyed)

    def get_self(self) -> User:
        return self.get_or_create_user(self._session.user.name)

    def get_tracked_users(self) -> List[User]:
        return list(filter(lambda u: u.has_add_user_flag(), self.users.values()))

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
        """Starts tracking the users defined in the friends list"""
        tasks = []
        for friend in self._settings.users.friends:
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

    @on_message(AdminMessage.Response)
    async def _on_admin_message(self, message: AdminMessage.Response, connection: ServerConnection):
        await self._event_bus.emit(AdminMessageEvent(message.message))

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

        await self._event_bus.emit(PrivilegedUserAddedEvent(user))

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

    # Listeners

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    async def _on_state_changed(self, event: ConnectionStateChangedEvent):
        if not isinstance(event.connection, ServerConnection):
            return

        if event.state == ConnectionState.CLOSED:
            self.reset_users()

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        logger.debug(f"user : session initialized : {event.session}")
        self._session = event.session
        await self._network.send_server_messages(
            CheckPrivileges.Request(),
            SetStatus.Request(UserStatus.ONLINE.value),
        )

        await self.track_user(self._session.user.name, TrackingFlag.FRIEND)

        # Perform AddUser for all in the friendlist
        await self.track_friends()

    async def _on_session_destroyed(self, event: SessionDestroyedEvent):
        self._session = None
