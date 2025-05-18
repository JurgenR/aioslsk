import asyncio
import copy
from dataclasses import dataclass
import logging
from typing import Optional
from weakref import WeakValueDictionary

from ..base_manager import BaseManager
from ..exceptions import InvalidSessionError
from ..network.connection import ConnectionState, PeerConnection, ServerConnection
from ..events import (
    build_message_map,
    on_message,
    AdminMessageEvent,
    BlockListChangedEvent,
    ConnectionStateChangedEvent,
    Event,
    EventBus,
    FriendListChangedEvent,
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
    BlockingFlag,
    ChatMessage,
    UploadPermissions,
    User,
    UserStatus,
    TrackingFlag,
)
from ..network.network import Network
from ..settings import Settings
from ..session import Session
from ..tasks import BackgroundTask


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


@dataclass
class UserManagementContext:
    friends: set[str]
    blocked: dict[str, BlockingFlag]


class UserManager(BaseManager):
    """Class responsible for handling user messages and storing users"""

    def __init__(self, settings: Settings, event_bus: EventBus, network: Network):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._network: Network = network

        self._session: Optional[Session] = None

        self._MESSAGE_MAP = build_message_map(self)

        self._users: WeakValueDictionary[str, User] = WeakValueDictionary()
        self._tracked_users: dict[str, TrackedUser] = dict()
        self._privileged_users: set[str] = set()

        self._management_task: BackgroundTask = BackgroundTask(
            interval=1.0,
            task_coro=self._management_job,
            name='user-management-task',
            context=UserManagementContext(
                friends=self._settings.users.friends.copy(),
                blocked=self._settings.users.blocked.copy()
            )
        )

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
        self._event_bus.register(
            FriendListChangedEvent, self._on_friend_list_changed)

    @property
    def users(self) -> dict[str, User]:
        return dict(self._users)

    @property
    def privileged_users(self) -> set[str]:
        return self._privileged_users

    async def start(self):
        self._management_task.start()

    async def stop(self) -> list[asyncio.Task]:
        cancel_tasks = []
        if task := self._management_task.cancel():
            cancel_tasks.append(task)

        return cancel_tasks

    def get_self(self) -> User:
        """Returns the user object for the current session"""
        if not self._session:  # pragma: no cover
            raise InvalidSessionError("user is not logged in")

        return self.get_user_object(self._session.user.name)

    def get_user_object(self, username: str) -> User:
        """Gets a :class:`.User` object for given ``username``, if the user is
        not stored it will be created and stored.

        A user will be stored only if there is a strong reference to the
        :class:`.User` object, otherwise it will be removed

        :param username: Name of the user
        :return: a :class:`.User` object
        """
        if username not in self._users:
            # Don't simplify this by assigning it directly to the dict; a strong
            # reference needs to be kept otherwise the object would be
            # immediatly removed
            user = User(
                name=username,
                privileged=username in self._privileged_users
            )
            self._users[username] = user
            return user

        return self._users[username]

    def is_tracked(self, username: str) -> bool:
        """Returns whether a user status is currently being tracked"""
        return username in self._tracked_users

    def reset_users(self):
        """Performs a reset on all users. This method is called when the
        connection with the server is disconnected and shouldn't be called
        directly
        """
        self._users = WeakValueDictionary()
        self._tracked_users = dict()
        self._privileged_users = set()

    async def track_user(self, username: str, flag: TrackingFlag = TrackingFlag.REQUESTED):
        """Starts tracking a user. The method sends a tracking request to the
        server if it is the first tracking flag being sent or the tracking flag
        is ``TrackingFlag.REQUESTED``

        :param username: user to track
        :param flag: tracking flag to add from the user
        """
        user = self.get_user_object(username)
        is_first_flag = self._set_tracking_flag(user, flag)
        if is_first_flag or flag == TrackingFlag.REQUESTED:
            try:
                await self._network.send_server_messages(AddUser.Request(username))
            except Exception:
                self._unset_tracking_flag(user, flag)
                raise

    async def untrack_user(self, username: str, flag: TrackingFlag = TrackingFlag.REQUESTED):
        """Removes the given flag from the user and untracks the user (send
        :class:`.RemoveUser` message) in case none of the AddUser tracking flags
        are set or the removed tracking flag is ``TrackingFlag.REQUESTED``.

        The user will be removed from the tracked users if there are no flags
        left, if there is still a reference left to the user it will remain
        stored

        :param username: user to untrack
        :param flag: tracking flag to remove from the user
        """
        if username not in self._tracked_users:
            return

        user = self._users[username]
        has_flags_left = self._unset_tracking_flag(user, flag)
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

    async def track_friend(self, username: str):
        """Request to track a friend with given username"""
        await self.track_user(username, TrackingFlag.FRIEND)

    async def track_friends(self):
        """Starts tracking the users defined in the friends list"""
        tasks = [
            self.track_friend(friend)
            for friend in self._settings.users.friends
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def untrack_friend(self, username: str):
        """Request to stop tracking a friend with given username"""
        await self.untrack_user(username, TrackingFlag.FRIEND)

    def get_tracking_flags(self, username: str) -> TrackingFlag:
        """Returns current tracking flags of the user with given username

        :param username: username of the user
        """
        if username in self._tracked_users:
            return self._tracked_users[username].flags
        return TrackingFlag(0)

    def _get_tracked_user_object(self, user: User) -> TrackedUser:
        """Gets or creates a tracked user object"""
        if user.name not in self._tracked_users:
            self._tracked_users[user.name] = TrackedUser(user)
        return self._tracked_users[user.name]

    def _set_tracking_flag(self, user: User, flag: TrackingFlag = TrackingFlag.REQUESTED) -> bool:
        """Set given tracking flag for the user. This method returns ``True`` if
        the user previously had no tracking flags set.
        """
        tracked_user = self._get_tracked_user_object(user)
        had_tracking_flag = tracked_user.flags != TrackingFlag(0)
        tracked_user.flags |= flag
        return not had_tracking_flag

    def _unset_tracking_flag(self, user: User, flag: TrackingFlag) -> bool:
        """Unset given tracking flag. This method returns ``True`` if the user
        still has tracking flags left
        """
        tracked_user = self._tracked_users[user.name]
        tracked_user.flags &= ~flag
        return tracked_user.flags != TrackingFlag(0)

    async def _management_job(self, context: UserManagementContext):
        events: list[Event] = []

        if context.friends != self._settings.users.friends:
            events.append(
                FriendListChangedEvent(
                    added=self._settings.users.friends - context.friends,
                    removed=context.friends - self._settings.users.friends
                )
            )

        if context.blocked != self._settings.users.blocked:
            changes = {}

            # Unblocked through removal
            for username in context.blocked.keys() - self._settings.users.blocked.keys():
                changes[username] = (context.blocked[username], BlockingFlag.NONE)

            # Changed flag or added
            for username, flags in self._settings.users.blocked.items():
                old_flags = context.blocked.get(username, BlockingFlag.NONE)
                if flags != old_flags:
                    changes[username] = (old_flags, flags)

            events.append(BlockListChangedEvent(changes=changes))

        if events:
            context.friends = self._settings.users.friends.copy()
            context.blocked = self._settings.users.blocked.copy()

        for event in events:
            await self._event_bus.emit(event)

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

        await self._network.send_server_messages(
            PrivateChatMessageAck.Request(message.chat_id)
        )

        # For blocked users, ack the message but don't emit an event
        if self._settings.users.is_blocked(message.username, BlockingFlag.PRIVATE_MESSAGES):
            return

        user = self.get_user_object(message.username)
        chat_message = ChatMessage(
            id=message.chat_id,
            timestamp=message.timestamp,
            user=user,
            message=message.message,
            is_direct=bool(message.is_direct)
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
        if not self._session:  # pragma: no cover
            raise InvalidSessionError("user is not logged in")

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
            user.status = UserStatus(message.status)
            if message.user_stats:
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
            SetStatus.Request(UserStatus.ONLINE.value)
        )
        # Due to a bug in the protocol a GetUserStatus message for ourself is
        # never returned and it needs to be set manually
        self.get_self().status = UserStatus.ONLINE

        # Tracking does not actually work for the self user from a server point
        # of view but is kept here for convenience
        await self.track_user(self._session.user.name, TrackingFlag.FRIEND)

        # Perform AddUser for all in the friendlist
        await self.track_friends()

    async def _on_session_destroyed(self, event: SessionDestroyedEvent):
        self._session = None

    async def _on_friend_list_changed(self, event: FriendListChangedEvent):
        if not self._session:  # pragma: no cover
            return

        tasks = []
        for added_friend in event.added:
            tasks.append(self.track_friend(added_friend))

        for removed_friend in event.removed:
            tasks.append(self.untrack_friend(removed_friend))

        await asyncio.gather(*tasks, return_exceptions=True)
