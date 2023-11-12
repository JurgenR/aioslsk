import asyncio
import copy
from dataclasses import dataclass
import logging
from typing import Dict, Optional, Set
from weakref import WeakValueDictionary

from ..base_manager import BaseManager
from ..network.connection import ConnectionState, PeerConnection, ServerConnection
from ..events import (
    build_message_map,
    on_message,
    AdminMessageEvent,
    ConnectionStateChangedEvent,
    EventBus,
    KickedEvent,
    MessageReceivedEvent,
    PrivateMessageEvent,
    PrivilegedUsersEvent,
    PrivilegedUserAddedEvent,
    PrivilegesUpdateEvent,
    UserInfoUpdateEvent,
    UserStatsUpdateEvent,
    UserStatusUpdateEvent,
    UserTrackingEvent,
    UserUntrackingEvent,
    SessionInitializedEvent,
    SessionDestroyedEvent,
)
from ..protocol.messages import (
    AddPrivilegedUser,
    AddUser,
    AdminMessage,
    PrivateChatMessage,
    PrivateChatMessageAck,
    CheckPrivileges,
    GetUserStatus,
    GetUserStats,
    Kicked,
    PeerSearchReply,
    PeerUserInfoReply,
    PrivilegedUsers,
    RemoveUser,
    SetStatus,
)
from .model import (
    ChatMessage,
    UploadPermissions,
    User,
    UserStatus,
    TrackingFlag,
)
from ..network.network import Network
from ..settings import Settings
from ..session import Session


logger = logging.getLogger(__name__)


@dataclass
class TrackedUser:
    user: User
    flags: TrackingFlag = TrackingFlag(0)

    def has_add_user_flag(self) -> bool:
        """Returns whether this user has any tracking flags set related to
        AddUser
        """
        add_user_flags = TrackingFlag.FRIEND | TrackingFlag.REQUESTED | TrackingFlag.TRANSFER
        return self.flags & add_user_flags != TrackingFlag(0)


class UserManager(BaseManager):
    """Class responsible for handling user messages and storing users"""

    def __init__(self, settings: Settings, event_bus: EventBus, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network

        self._session: Optional[Session] = None

        self._MESSAGE_MAP = build_message_map(self)

        self._users: WeakValueDictionary[str, User] = WeakValueDictionary()
        self._tracked_users: Dict[str, TrackedUser] = dict()
        self._privileged_users: Set[str] = set()

        self.register_listeners()

    def register_listeners(self):
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._event_bus.register(
            ConnectionStateChangedEvent, self._on_state_changed)
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)
        self._event_bus.register(
            SessionDestroyedEvent, self._on_session_destroyed)

    @property
    def users(self) -> Dict[str, User]:
        return dict(self._users)

    @property
    def privileged_users(self) -> Set[str]:
        return self._privileged_users

    def get_self(self) -> User:
        """Returns the user object for the current session"""
        return self.get_user_object(self._session.user.name)

    def get_user_object(self, username: str) -> User:
        """Gets a `User` object for given `username`, if the user is not stored
        it will be created and stored

        :param username: Name of the user
        :return: a `User` object
        """
        if username not in self._users:
            user = User(
                name=username,
                privileged=username in self._privileged_users
            )
            self._users[username] = user
        return self._users[username]

    def is_tracked(self, username: str) -> bool:
        return username in self._tracked_users

    def _get_or_create_user(self, username: str) -> User:
        if username not in self._users:
            self._users[username] = User(username)
        return self._users[username]

    def _get_tracked_user_object(self, user: User) -> TrackedUser:
        if user.name not in self._tracked_users:
            self._tracked_users[user.name] = TrackedUser(user)
        return self._tracked_users[user.name]

    def reset_users(self):
        """Performs a reset on all users"""
        self._users = WeakValueDictionary()
        self._tracked_users = dict()
        self._privileged_users = set()

    def set_tracking_flag(self, user: User, flag: TrackingFlag = TrackingFlag.REQUESTED) -> bool:
        """Set given tracking flag for the user. This method returns `True` if
        the user previously had not tracking flags set.
        """
        tracked_user = self._get_tracked_user_object(user)
        had_tracking_flag = tracked_user.flags != TrackingFlag(0)
        tracked_user.flags |= flag
        return not had_tracking_flag

    def unset_tracking_flag(self, user: User, flag: TrackingFlag) -> bool:
        """Unset given tracking flag. This method return `True` if the user has
        not tracking flags left
        """
        tracked_user = self._tracked_users[user.name]
        tracked_user.flags &= ~flag
        return tracked_user.flags != TrackingFlag(0)

    async def track_user(self, username: str, flag: TrackingFlag = TrackingFlag.REQUESTED):
        """Starts tracking a user. The method sends a tracking request to the
        server if it is the first tracking flag being sent or the tracking flag
        is `TrackingFlag.REQUESTED`

        :param username: user to track
        :param flag: tracking flag to add from the user
        """
        user = self.get_user_object(username)
        is_first_flag = self.set_tracking_flag(user, flag)
        if is_first_flag or flag == TrackingFlag.REQUESTED:
            try:
                await self._network.send_server_messages(AddUser.Request(username))
            except Exception:
                self.unset_tracking_flag(user, flag)
                raise

    async def track_friends(self):
        """Starts tracking the users defined in the friends list"""
        tasks = []
        for friend in self._settings.users.friends:
            tasks.append(self.track_user(friend, TrackingFlag.FRIEND))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def untrack_user(self, username: str, flag: TrackingFlag):
        """Removes the given flag from the user and untracks the user (send
        `RemoveUser` message) in case none of the AddUser tracking flags are
        set or the removed tracking flag is `TrackingFlag.REQUESTED`.

        The user will be removed from the tracked users if there are no flags
        left, if there is still a reference left to the user it will remain
        stored

        :param username: user to untrack
        :param flag: tracking flag to remove from the user
        """
        if username not in self._tracked_users:
            return

        user = self._users[username]
        has_flags_left = self.unset_tracking_flag(user, flag)
        if not has_flags_left or flag == TrackingFlag.REQUESTED:
            try:
                await self._network.send_server_messages(RemoveUser.Request(user.name))
            finally:
                # If there's no more tracking done reset the user status and
                # remove the user from the list
                user.status = UserStatus.UNKNOWN

                if username in self._tracked_users:
                    del self._tracked_users[username]
                await self._event_bus.emit(UserUntrackingEvent(user=user))

    @on_message(AdminMessage.Response)
    async def _on_admin_message(self, message: AdminMessage.Response, connection: ServerConnection):
        await self._event_bus.emit(
            AdminMessageEvent(
                message.message,
                raw_message=message
            )
        )

    @on_message(Kicked.Response)
    async def _on_kicked(self, message: Kicked.Response, connection: ServerConnection):
        await self._event_bus.emit(KickedEvent(raw_message=message))

    @on_message(PrivateChatMessage.Response)
    async def _on_private_message(self, message: PrivateChatMessage.Response, connection: ServerConnection):
        user = self.get_user_object(message.username)
        chat_message = ChatMessage(
            id=message.chat_id,
            timestamp=message.timestamp,
            user=user,
            message=message.message,
            is_admin=bool(message.is_admin)
        )

        await self._network.send_server_messages(
            PrivateChatMessageAck.Request(message.chat_id)
        )
        await self._event_bus.emit(
            PrivateMessageEvent(
                message=chat_message,
                raw_message=message
            )
        )

    # State related messages
    @on_message(CheckPrivileges.Response)
    async def _on_check_privileges(self, message: CheckPrivileges.Response, connection: ServerConnection):
        self.privileges_time_left = message.time_left
        self._session.privileges_time_left = message.time_left

        await self._event_bus.emit(
            PrivilegesUpdateEvent(
                time_left=message.time_left,
                raw_message=message
            )
        )

    @on_message(PrivilegedUsers.Response)
    async def _on_privileged_users(self, message: PrivilegedUsers.Response, connection: ServerConnection):
        for user in self._users.values():
            user.privileged = user.name in message.users

        self._privileged_users = set(message.users)

        await self._event_bus.emit(
            PrivilegedUsersEvent(
                users=list(map(self.get_user_object, message.users)),
                raw_message=message
            )
        )

    @on_message(AddPrivilegedUser.Response)
    async def _on_add_privileged_user(self, message: AddPrivilegedUser.Response, connection: ServerConnection):
        user = self.get_user_object(message.username)
        user.privileged = True

        await self._event_bus.emit(PrivilegedUserAddedEvent(user))

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection: ServerConnection):
        user = self.get_user_object(message.username)
        tracked_user = self._get_tracked_user_object(user)
        if message.exists:
            user.name = message.username
            user.status = UserStatus(message.status)
            user.update_from_user_stats(message.user_stats)
            user.country = message.country_code

            await self._event_bus.emit(
                UserTrackingEvent(
                    user=user,
                    raw_message=message
                )
            )

        else:
            tracked_user.flags = TrackingFlag(0)
            if user.name in self._tracked_users:
                del self._tracked_users[user.name]
            await self._event_bus.emit(UserUntrackingEvent(user=user))

    @on_message(GetUserStatus.Response)
    async def _on_get_user_status(self, message: GetUserStatus.Response, connection: ServerConnection):
        user = self.get_user_object(message.username)

        before = copy.deepcopy(user)

        user.status = UserStatus(message.status)
        user.privileged = message.privileged

        await self._event_bus.emit(
            UserStatusUpdateEvent(
                before=before,
                current=user,
                raw_message=message
            )
        )

    @on_message(GetUserStats.Response)
    async def _on_get_user_stats(self, message: GetUserStats.Response, connection: ServerConnection):
        user = self.get_user_object(message.username)

        before = copy.deepcopy(user)

        user.update_from_user_stats(message.user_stats)

        await self._event_bus.emit(
            UserStatsUpdateEvent(
                before=before,
                current=user,
                raw_message=message
            )
        )

    @on_message(PeerUserInfoReply.Request)
    async def _on_peer_user_info_reply(self, message: PeerUserInfoReply.Request, connection: PeerConnection):
        if not connection.username:
            logger.warning(
                "got PeerUserInfoReply for a connection that wasn't properly initialized")
            return

        user = self.get_user_object(connection.username)

        before = copy.deepcopy(user)

        user.description = message.description
        user.picture = message.picture
        user.upload_slots = message.upload_slots
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free
        if message.upload_permissions is None:
            user.upload_permissions = UploadPermissions.UNKNOWN
        else:
            user.upload_permissions = UploadPermissions(message.upload_permissions)

        await self._event_bus.emit(
            UserInfoUpdateEvent(
                before=before,
                current=user,
                raw_message=message
            )
        )

    @on_message(PeerSearchReply.Request)
    async def _on_peer_search_reply(self, message: PeerSearchReply.Request, connection: PeerConnection):
        user = self.get_user_object(message.username)
        user.avg_speed = message.avg_speed
        user.queue_length = message.queue_size
        user.has_slots_free = message.has_slots_free

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
