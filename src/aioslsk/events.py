from __future__ import annotations
import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
import inspect
import logging
import sys
from typing import Any, Optional, TypeVar, TYPE_CHECKING, Union
from types import MethodType
import weakref

from .room.model import Room, RoomMessage
from .user.model import BlockingFlag, ChatMessage, TrackingState, User
from .protocol.primitives import (
    DirectoryData,
    MessageDataclass,
    Recommendation,
)
from .protocol.messages import (
    AddUser,
    AdminMessage,
    CheckPrivileges,
    GetGlobalRecommendations,
    GetItemRecommendations,
    GetItemSimilarUsers,
    GetRecommendations,
    GetSimilarUsers,
    GetUserInterests,
    GetUserStats,
    GetUserStatus,
    JoinRoom,
    Kicked,
    LeaveRoom,
    Login,
    PeerDirectoryContentsReply,
    PeerSharesReply,
    PeerUserInfoReply,
    PrivateChatMessage,
    PrivateRoomGrantMembership,
    PrivateRoomGrantOperator,
    PrivateRoomMembers,
    PrivateRoomMembershipGranted,
    PrivateRoomMembershipRevoked,
    PrivateRoomOperatorGranted,
    PrivateRoomOperatorRevoked,
    PrivateRoomOperators,
    PrivateRoomRevokeMembership,
    PrivateRoomRevokeOperator,
    PrivilegedUsers,
    PublicChatMessage,
    RoomChatMessage,
    RoomList,
    RoomTickerAdded,
    RoomTickerRemoved,
    RoomTickers,
    UserJoinedRoom,
    UserLeftRoom,
)
from .search.model import SearchRequest, SearchResult
from .shares.model import SharedDirectory
from .session import Session

if TYPE_CHECKING:
    from .network.connection import (
        Connection,
        ConnectionState,
        CloseReason,
        PeerConnection,
    )
    from .transfer.model import Transfer, TransferProgressSnapshot


logger = logging.getLogger(__name__)

# There used to be a difference in older versions between using the inspect and
# asyncio functions. The inspect function was fixed in 3.13. The asyncio version
# will be removed in 3.16
if sys.version_info >= (3, 14):
    iscoroutinefunction = inspect.iscoroutinefunction

else:
    iscoroutinefunction = asyncio.iscoroutinefunction


E = TypeVar('E', bound='Event')


EventListener = Union[
    Callable[[E], None],
    Callable[[E], Coroutine[Any, Any, Any]]
]


# Internal functions

def on_message(message_class: type[MessageDataclass]):
    """Decorator for methods listening to specific :class:`.MessageData` events
    """
    def register(event_func):
        event_func._registered_message = message_class
        return event_func

    return register


def build_message_map(obj: object) -> dict[type[MessageDataclass], Callable]:
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    mapping: dict[type[MessageDataclass], Callable] = {}
    for _, method in methods:
        registered_message = getattr(method, '_registered_message', None)
        if registered_message:
            mapping[registered_message] = method
    return mapping


# External functions

class EventBus:

    def __init__(self):
        self._events: dict[
            type[Event],
            list[tuple[int, weakref.ReferenceType[EventListener]]]] = {}

    def register(self, event_class: type[E], listener: EventListener, priority: int = 100):
        """Registers an event listener to listen on an event class. The order in
        which the listeners are called can be managed using the ``priority``
        parameter
        """
        ref_factory: type[weakref.ReferenceType] = weakref.ref
        if isinstance(listener, MethodType):
            ref_factory = weakref.WeakMethod

        entry = (
            priority,
            ref_factory(listener, lambda ref: self._remove_callback(event_class, ref))
        )
        try:
            self._events[event_class].append(entry)
        except KeyError:
            self._events[event_class] = [entry, ]

        self._events[event_class].sort(key=lambda e: e[0])

    def unregister(self, event_class: type[E], listener: EventListener):
        """Unregisters the event listener from event bus"""
        if event_class not in self._events:
            return

        self._events[event_class] = [
            listener_def
            for listener_def in self._events[event_class]
            if listener != listener_def[1]()
        ]

    async def emit(self, event: Event):
        """Emit an event on the event bus. Listeners can be co-routines or
        regular functions

        :param event: the event instance to emit
        """
        for listener in self._get_listeners_for_event(event):
            try:
                if iscoroutinefunction(listener):
                    await listener(event)
                else:
                    listener(event)

            except Exception:
                logger.exception(
                    "exception notifying listener %r of event %r",
                    listener, event
                )

    def emit_sync(self, event: Event):
        """Emit an event on the event bus. Only listener functions are notified

        :param event: the event instance to emit
        """
        for listener in self._get_listeners_for_event(event):
            try:
                if iscoroutinefunction(listener):
                    logger.warning(
                        "attempted to emit synchronous event to an async listener : %r",
                        listener
                    )
                else:
                    listener(event)

            except Exception:
                logger.exception(
                    "exception notifying listener %r of event %r",
                    listener, event
                )

    def _get_listeners_for_event(self, event: Event) -> list[EventListener]:
        try:
            listeners_refs = self._events[event.__class__]
        except KeyError:
            return []

        listeners = []
        for _, listener_ref in listeners_refs:
            listener = listener_ref()
            # Should never be None, but checked for type compatibility
            if listener:  # pragma: no cover
                listeners.append(listener)

        return listeners

    def _remove_callback(
            self, event_class: type[E],
            listener_ref: weakref.ReferenceType[EventListener]):

        self._events[event_class] = [
            listener_def
            for listener_def in self._events[event_class]
            if listener_ref != listener_def[1]
        ]


# Public events
class Event:
    """Base class for events"""


@dataclass(frozen=True, slots=True)
class SessionInitializedEvent(Event):
    """Emitted after successful login"""
    session: Session
    raw_message: Login.Response


@dataclass(frozen=True, slots=True)
class SessionDestroyedEvent(Event):
    """Emitted after the login session has been destroyed (this is always after
    disconnect)
    """
    session: Session


@dataclass(frozen=True, slots=True)
class AdminMessageEvent(Event):
    """Emitted when a global admin message has been received"""
    message: str
    raw_message: AdminMessage.Response


@dataclass(frozen=True, slots=True)
class KickedEvent(Event):
    """Emitted when we are kicked from the server"""
    raw_message: Kicked.Response


@dataclass(frozen=True, slots=True)
class UserTrackingStateChangedEvent(Event):
    """Emitted when the tracking state of a user has changed.

    Possibly states for the ``state`` property will be defined in by the
    :class:`.TrackingState` flags
    """

    user: User
    state: TrackingState
    raw_message: Optional[AddUser.Response] = None


@dataclass(frozen=True, slots=True)
class UserTrackingEvent(Event):
    """Emitted when a user is now successfully by the library tracked. This will
    be triggered when:

    The ``user`` object will contain the tracked user. ``data`` will contain the
    data returned by the server

    .. deprecated:: 1.6
        Use :class:`.UserTrackingStateChangedEvent` instead
    """
    user: User
    raw_message: AddUser.Response


@dataclass(frozen=True, slots=True)
class UserTrackingFailedEvent(Event):
    """
    .. deprecated:: 1.6
        Use :class:`.UserTrackingStateChangedEvent` instead
    """
    username: str
    raw_message: AddUser.Response


@dataclass(frozen=True, slots=True)
class UserUntrackingEvent(Event):
    """Emitted when a user is no longer tracked by the library

    .. deprecated:: 1.6
        Use :class:`.UserTrackingStateChangedEvent` instead
    """
    user: User


@dataclass(frozen=True, slots=True)
class UserStatusUpdateEvent(Event):
    """Emitted when the server sends an update for the users status / privileges
    or a request for it
    """
    before: User
    current: User
    raw_message: GetUserStatus.Response


@dataclass(frozen=True, slots=True)
class UserStatsUpdateEvent(Event):
    """Emitted when the server send an update for the user's sharing statistics
    """
    before: User
    current: User
    raw_message: GetUserStats.Response


@dataclass(frozen=True, slots=True)
class UserInfoUpdateEvent(Event):
    """Emitted when user info has been received"""
    before: User
    current: User
    raw_message: PeerUserInfoReply.Request


@dataclass(frozen=True, slots=True)
class RoomListEvent(Event):
    rooms: list[Room]
    raw_message: RoomList.Response


@dataclass(frozen=True, slots=True)
class RoomMessageEvent(Event):
    message: RoomMessage
    raw_message: RoomChatMessage.Response


@dataclass(frozen=True, slots=True)
class RoomTickersEvent(Event):
    """Emitted when a list of tickers has been received for a room"""
    room: Room
    tickers: dict[str, str]
    raw_message: RoomTickers.Response


@dataclass(frozen=True, slots=True)
class RoomTickerAddedEvent(Event):
    """Emitted when a ticker has been added to the room by a user"""
    room: Room
    user: User
    ticker: str
    raw_message: RoomTickerAdded.Response


@dataclass(frozen=True, slots=True)
class RoomTickerRemovedEvent(Event):
    """Emitted when a ticker has been removed from the room by a user"""
    room: Room
    user: User
    raw_message: RoomTickerRemoved.Response


@dataclass(frozen=True, slots=True)
class RoomJoinedEvent(Event):
    """Emitted after a user joined a chat room

    The value of ``user`` will be ``None`` in case it is us who has joined the
    room
    """
    room: Room
    raw_message: Union[JoinRoom.Response, UserJoinedRoom.Response]
    user: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomLeftEvent(Event):
    """Emitted after a user left a chat room

    The value of ``user`` will be ``None`` in case it is us who has left the
    room
    """
    room: Room
    raw_message: Union[LeaveRoom.Response, UserLeftRoom.Response]
    user: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomMembershipGrantedEvent(Event):
    """Emitted when a member has been added to the private room

    The value of ``member`` will be ``None`` in case it is us who has been added
    to the room
    """
    room: Room
    raw_message: Union[PrivateRoomGrantMembership.Response, PrivateRoomMembershipGranted.Response]
    member: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomMembershipRevokedEvent(Event):
    """Emitted when a member has been removed to the private room

    The value of ``member`` will be ``None`` in case it is us who has been
    removed from the room
    """
    room: Room
    raw_message: Union[PrivateRoomRevokeMembership.Response, PrivateRoomMembershipRevoked.Response]
    member: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomOperatorGrantedEvent(Event):
    """Emitted when a member has been granted operator privileges on a private
    room

    The value of ``member`` will be ``None`` in case it is us who has been
    granted operator
    """
    room: Room
    raw_message: Union[PrivateRoomGrantOperator.Response, PrivateRoomOperatorGranted.Response]
    member: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomOperatorRevokedEvent(Event):
    """Emitted when a member had operator privileges revoked on a private room

    The value of ``user`` will be ``None`` in case it is us who has been revoked
    operator
    """
    room: Room
    raw_message: Union[PrivateRoomRevokeOperator.Response, PrivateRoomOperatorRevoked.Response]
    member: Optional[User] = None


@dataclass(frozen=True, slots=True)
class RoomOperatorsEvent(Event):
    """Emitted when the server sends us a list of operators in a room"""
    room: Room
    operators: list[User]
    raw_message: PrivateRoomOperators.Response


@dataclass(frozen=True, slots=True)
class RoomMembersEvent(Event):
    """Emitted when the server sends us a list of members of a room. The list
    of members always excludes the owner of the room
    """
    room: Room
    members: list[User]
    raw_message: PrivateRoomMembers.Response


@dataclass(frozen=True, slots=True)
class PrivateMessageEvent(Event):
    """Emitted when a private message has been received"""
    message: ChatMessage
    raw_message: PrivateChatMessage.Response


@dataclass(frozen=True, slots=True)
class PublicMessageEvent(Event):
    """Emitted when a message has been received from a public room and public
    chat has been enabled
    """
    timestamp: int
    user: User
    room: Room
    message: str
    raw_message: PublicChatMessage.Response


@dataclass(frozen=True, slots=True)
class SearchRequestSentEvent(Event):
    """Emitted when a search request has been sent out"""
    query: SearchRequest


@dataclass(frozen=True, slots=True)
class SearchRequestRemovedEvent(Event):
    """Emitted when a search request has been removed"""
    query: SearchRequest


@dataclass(frozen=True, slots=True)
class SearchResultEvent(Event):
    """Emitted when a search result has been received"""
    query: SearchRequest
    result: SearchResult


@dataclass(frozen=True, slots=True)
class SearchRequestReceivedEvent(Event):
    """Emitted when a search request by another user has been received"""
    username: str
    query: str
    result_count: int


@dataclass(frozen=True, slots=True)
class SimilarUsersEvent(Event):
    users: list[tuple[User, int]]
    raw_message: GetSimilarUsers.Response


@dataclass(frozen=True, slots=True)
class ItemSimilarUsersEvent(Event):
    item: str
    users: list[User]
    raw_message: GetItemSimilarUsers.Response


@dataclass(frozen=True, slots=True)
class RecommendationsEvent(Event):
    recommendations: list[Recommendation]
    unrecommendations: list[Recommendation]
    raw_message: GetRecommendations.Response


@dataclass(frozen=True, slots=True)
class GlobalRecommendationsEvent(Event):
    recommendations: list[Recommendation]
    unrecommendations: list[Recommendation]
    raw_message: GetGlobalRecommendations.Response


@dataclass(frozen=True, slots=True)
class ItemRecommendationsEvent(Event):
    item: str
    recommendations: list[Recommendation]
    raw_message: GetItemRecommendations.Response


@dataclass(frozen=True, slots=True)
class UserInterestsEvent(Event):
    user: User
    interests: list[str]
    hated_interests: list[str]
    raw_message: GetUserInterests.Response


@dataclass(frozen=True, slots=True)
class PrivilegedUsersEvent(Event):
    """Emitted when the list of privileged users has been received"""
    users: list[User]
    raw_message: PrivilegedUsers.Response


@dataclass(frozen=True, slots=True)
class PrivilegedUserAddedEvent(Event):
    """Emitted when a new privileged user has been added"""
    user: User


@dataclass(frozen=True, slots=True)
class PrivilegesUpdateEvent(Event):
    """Emitted when we receive a message containing how much time is left on the
    current user's privileges. If ``time_left`` is 0 the current user has no
    privileges
    """
    time_left: int
    raw_message: CheckPrivileges.Response


# Peer

@dataclass(frozen=True, slots=True)
class UserSharesReplyEvent(Event):
    user: User
    directories: list[DirectoryData]
    locked_directories: list[DirectoryData]
    raw_message: PeerSharesReply.Request


@dataclass(frozen=True, slots=True)
class UserDirectoryEvent(Event):
    user: User
    directory: str
    directories: list[DirectoryData]
    raw_message: PeerDirectoryContentsReply.Request


# Transfer

@dataclass(frozen=True, slots=True)
class TransferAddedEvent(Event):
    """Emitted when a transfer has been attached to the client"""
    transfer: Transfer


@dataclass(frozen=True, slots=True)
class TransferRemovedEvent(Event):
    """Emitted when a transfer has been detached from the client"""
    transfer: Transfer


@dataclass(frozen=True, slots=True)
class TransferProgressEvent(Event):
    """Called periodically to report progress. The interval is determined by the
    ``transfers.progress_interval`` settings parameter

    This event only includes transfers where the transfer state has been changed
    since the previous event. If there are no updates the event will no be
    called
    """
    updates: list[tuple[Transfer, TransferProgressSnapshot, TransferProgressSnapshot]]
    """List of progress updates: transfer instance, previous snapshot, current
    snapshot
    """


# Internal Events

class InternalEvent(Event):
    """Base class for internal events"""


@dataclass(frozen=True, slots=True)
class ConnectionStateChangedEvent(InternalEvent):
    """Indicates a state change in any type of connection"""
    connection: Connection
    state: ConnectionState
    close_reason: Optional[CloseReason] = None


@dataclass(frozen=True, slots=True)
class ServerReconnectedEvent(InternalEvent):
    """Indicates server reconnected, used internally to automatically log back
    in
    """


@dataclass(frozen=True, slots=True)
class MessageReceivedEvent(InternalEvent):
    """Emitted when a message was received on a connection"""
    message: MessageDataclass
    connection: Connection


@dataclass(frozen=True, slots=True)
class PeerInitializedEvent(InternalEvent):
    """Emitted when a new peer connection has been established and the
    initialization message has been received or sent
    """
    connection: PeerConnection
    requested: bool
    """Indictes whether the connection was initialized by another user or opened
    on the client's request
    """


@dataclass(frozen=True, slots=True)
class ScanCompleteEvent(InternalEvent):
    """Emitted when shares scan was completed"""
    folder_count: int
    file_count: int


@dataclass(frozen=True, slots=True)
class FriendListChangedEvent(InternalEvent):
    """Emitted when a change was detected in the friends list"""
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class BlockListChangedEvent(InternalEvent):
    """Emitted when a change was detected in the blocked list"""
    changes: dict[str, tuple[BlockingFlag, BlockingFlag]]
    """List of changes. The key contains the username, the value is a tuple
    containing the old and new flags.
    """


@dataclass(frozen=True, slots=True)
class SharedDirectoryChangeEvent(InternalEvent):
    shared_directory: SharedDirectory
