from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from typing import Callable, Dict, List, Optional, Tuple, Type, TYPE_CHECKING

from .room.model import Room, RoomMessage
from .user.model import ChatMessage, User
from .protocol.primitives import (
    DirectoryData,
    MessageDataclass,
    Recommendation,
)
from .search.model import SearchRequest, SearchResult
from .session import Session

if TYPE_CHECKING:
    from .network.connection import (
        Connection,
        ConnectionState,
        CloseReason,
        PeerConnection,
    )
    from .transfer.model import Transfer


logger = logging.getLogger(__name__)


# Internal functions

def on_message(message_class: Type[MessageDataclass]):
    """Decorator for methods listening to specific `MessageData` events"""
    def register(event_func):
        event_func._registered_message = message_class
        return event_func

    return register


def build_message_map(obj: object) -> Dict[Type[MessageDataclass], Callable]:
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    mapping: Dict[Type[MessageDataclass], Callable] = {}
    for _, method in methods:
        registered_message = getattr(method, '_registered_message', None)
        if registered_message:
            mapping[registered_message] = method
    return mapping


# External functions

class EventBus:

    def __init__(self):
        self._events: Dict[Type[Event], List[Tuple[int, Callable[[Event], None]]]] = {}

    def register(self, event_class: Type[Event], listener: Callable[[Event], None], priority: int = 100):
        entry = (priority, listener)
        try:
            self._events[event_class].append(entry)
        except KeyError:
            self._events[event_class] = [entry, ]

        self._events[event_class].sort(key=lambda e: e[0])

    async def emit(self, event: Event):
        try:
            listeners = self._events[event.__class__]
        except KeyError:
            pass
        else:
            for _, listener in listeners:
                try:
                    if asyncio.iscoroutinefunction(listener):
                        await listener(event)
                    else:
                        listener(event)
                except Exception:
                    logger.exception(f"exception notifying listener {listener!r} of event {event!r}")


# Public events
class Event:
    """Base class for events"""


@dataclass(frozen=True)
class SessionInitializedEvent(Event):
    """Emitted after successful login"""
    session: Session


@dataclass(frozen=True)
class SessionDestroyedEvent(Event):
    """Emitted after the login session has been destroyed (this is always after
    disconnect)
    """
    session: Session


@dataclass(frozen=True)
class AdminMessageEvent(Event):
    """Emitted when a global admin message has been received"""
    message: str


@dataclass(frozen=True)
class KickedEvent(Event):
    """Emitted when we are kicked from the server"""


@dataclass(frozen=True)
class UserInfoEvent(Event):
    user: User


@dataclass(frozen=True)
class UserStatusEvent(Event):
    user: User


@dataclass(frozen=True)
class RoomListEvent(Event):
    rooms: List[Room]


@dataclass(frozen=True)
class RoomMessageEvent(Event):
    message: RoomMessage


@dataclass(frozen=True)
class RoomTickersEvent(Event):
    """Emitted when a list of tickers has been received for a room"""
    room: Room
    tickers: Dict[str, str]


@dataclass(frozen=True)
class RoomTickerAddedEvent(Event):
    """Emitted when a ticker has been added to the room by a user"""
    room: Room
    user: User
    ticker: str


@dataclass(frozen=True)
class RoomTickerRemovedEvent(Event):
    """Emitted when a ticker has been removed from the room by a user"""
    room: Room
    user: User


@dataclass(frozen=True)
class RoomJoinedEvent(Event):
    """Emitted after a user joined a chat room

    The value of `user` will be `None` in case it is us who has left the room
    """
    room: Room
    user: Optional[User] = None


@dataclass(frozen=True)
class RoomLeftEvent(Event):
    """Emitted after a user left a chat room

    The value of `user` will be `None` in case it is us who has left the room
    """
    room: Room
    user: Optional[User] = None


@dataclass(frozen=True)
class RoomMembershipGrantedEvent(Event):
    """Emitted when a member has been added to the private room

    The value of `user` will be `None` in case it is us who has been added to
    the room
    """
    room: Room
    member: Optional[User] = None


@dataclass(frozen=True)
class RoomMembershipRevokedEvent(Event):
    """Emitted when a member has been removed to the private room

    The value of `user` will be `None` in case it is us who has been removed
    from the room
    """
    room: Room
    member: Optional[User] = None


@dataclass(frozen=True)
class RoomOperatorGrantedEvent(Event):
    """Emitted when a member has been granted operator privileges on a private
    room

    The value of `user` will be `None` in case it is us who has been granted
    operator
    """
    room: Room
    member: Optional[User] = None


@dataclass(frozen=True)
class RoomOperatorRevokedEvent(Event):
    """Emitted when a member had operator privileges revoked on a private room

    The value of `user` will be `None` in case it is us who has been revoked
    operator
    """
    room: Room
    member: Optional[User] = None


@dataclass(frozen=True)
class RoomOperatorsEvent(Event):
    """Emitted when the server sends us a list of operators in a room"""
    room: Room
    operators: List[User]


@dataclass(frozen=True)
class RoomMembersEvent(Event):
    """Emitted when the server sends us a list of members of a room. The list
    of members always excludes the owner of the room
    """
    room: Room
    members: List[User]


@dataclass(frozen=True)
class PrivateMessageEvent(Event):
    """Emitted when a private message has been received"""
    message: ChatMessage


@dataclass(frozen=True)
class PublicMessageEvent(Event):
    message: RoomMessage


@dataclass(frozen=True)
class SearchResultEvent(Event):
    """Emitted when a search result has been received"""
    query: SearchRequest
    result: SearchResult


@dataclass(frozen=True)
class SearchRequestReceivedEvent(Event):
    """Emitted when a search request by another user has been received"""
    username: str
    query: str
    result_count: int


@dataclass(frozen=True)
class SimilarUsersEvent(Event):
    users: List[User]
    item: Optional[str] = None


@dataclass(frozen=True)
class RecommendationsEvent(Event):
    recommendations: List[Recommendation]
    unrecommendations: List[Recommendation]


@dataclass(frozen=True)
class GlobalRecommendationsEvent(Event):
    recommendations: List[Recommendation]
    unrecommendations: List[Recommendation]


@dataclass(frozen=True)
class ItemRecommendationsEvent(Event):
    item: str
    recommendations: List[Recommendation]


@dataclass(frozen=True)
class UserInterestsEvent(Event):
    user: User
    interests: List[str]
    hated_interests: List[str]


@dataclass(frozen=True)
class PrivilegedUsersEvent(Event):
    """Emitted when the list of privileged users has been received"""
    users: List[User]


@dataclass(frozen=True)
class PrivilegedUserAddedEvent(Event):
    """Emitted when a new privileged user has been added"""
    user: User


@dataclass(frozen=True)
class PrivilegesUpdate(Event):
    """Emitted when we receive a message containing how much time is left on the
    current user's privileges. If `time_left` is 0 the current user has no
    privileges
    """
    time_left: int


# Peer

@dataclass(frozen=True)
class UserSharesReplyEvent(Event):
    user: User
    directories: List[DirectoryData]
    locked_directories: List[DirectoryData] = field(default_factory=list)


@dataclass(frozen=True)
class UserDirectoryEvent(Event):
    user: User
    directory: str
    directories: List[DirectoryData]


# Transfer

@dataclass(frozen=True)
class TransferAddedEvent(Event):
    transfer: Transfer


# Internal Events

class InternalEvent(Event):
    """Base class for internal events"""


@dataclass(frozen=True)
class ConnectionStateChangedEvent(InternalEvent):
    """Indicates a state change in any type of connection"""
    connection: Connection
    state: ConnectionState
    close_reason: Optional[CloseReason] = None


@dataclass(frozen=True)
class ServerReconnectedEvent(InternalEvent):
    """Indicates server reconnected, used internally to automatically log back
    in
    """


@dataclass(frozen=True)
class MessageReceivedEvent(InternalEvent):
    """Emitted when a message was received on a connection"""
    message: MessageDataclass
    connection: Connection


@dataclass(frozen=True)
class PeerInitializedEvent(InternalEvent):
    """Emitted when a new peer connection has been established and the
    initialization message has been received or sent
    """
    connection: PeerConnection
    requested: bool
    """Indictes whether the connection was initialized by another user or opened
    on the client's request
    """


@dataclass(frozen=True)
class ScanCompleteEvent(InternalEvent):
    """Emitted when shares scan was completed"""
    folder_count: int
    file_count: int
