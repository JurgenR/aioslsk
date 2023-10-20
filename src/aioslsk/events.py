from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from typing import Callable, Dict, List, Optional, Tuple, Type, TYPE_CHECKING

from .room.model import Room, RoomMessage
from .user.model import ChatMessage, User, TrackingFlag
from .protocol.primitives import (
    DirectoryData,
    MessageDataclass,
    ItemRecommendation,
)
from .search.model import SearchRequest, SearchResult

if TYPE_CHECKING:
    from .network.connection import (
        Connection,
        ConnectionState,
        CloseReason,
        PeerConnection,
    )
    from .transfer.model import Transfer
    from .transfer.state import TransferState


logger = logging.getLogger(__name__)


# Internal functions

def on_message(message_class: Type[MessageDataclass]):
    """Decorator for methods listening to specific L{Message} events"""
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


class InternalEventBus(EventBus):

    pass


# Public events
class Event:
    pass


@dataclass(frozen=True)
class ServerConnectedEvent(Event):
    """Emitted when server got connected"""


@dataclass(frozen=True)
class ServerDisconnectedEvent(Event):
    """Emitted when server got disconnected"""


@dataclass(frozen=True)
class LoginEvent(Event):
    """Emitted when we got a response to a login call"""
    is_success: bool
    greeting: Optional[str] = None
    reason: Optional[str] = None


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
    room: Room
    tickers: Dict[str, str]


@dataclass(frozen=True)
class RoomTickerAddedEvent(Event):
    room: Room
    user: User
    ticker: str


@dataclass(frozen=True)
class RoomTickerRemovedEvent(Event):
    room: Room
    user: User


@dataclass(frozen=True)
class RoomJoinedEvent(Event):
    """Emitted after a user joined a chat room

    The value of `user` will be `None` in case it is us who has left the room
    """
    room: Room
    user: User = None


@dataclass(frozen=True)
class RoomLeftEvent(Event):
    """Emitted after a user left a chat room

    The value of `user` will be `None` in case it is us who has left the room
    """
    room: Room
    user: User = None


@dataclass(frozen=True)
class RoomMembershipGrantedEvent(Event):
    """Emitted when a member has been added to the private room

    The value of `user` will be `None` in case it is us who has been added to
    the room
    """
    room: Room
    member: User = None


@dataclass(frozen=True)
class RoomMembershipRevokedEvent(Event):
    """Emitted when a member has been removed to the private room

    The value of `user` will be `None` in case it is us who has been removed
    from the room
    """
    room: Room
    member: User = None


@dataclass(frozen=True)
class RoomOperatorGrantedEvent(Event):
    """Emitted when a member has been granted operator privileges on a private
    room

    The value of `user` will be `None` in case it is us who has been granted
    operator
    """
    room: Room
    member: User = None


@dataclass(frozen=True)
class RoomOperatorRevokedEvent(Event):
    """Emitted when a member had operator privileges revoked on a private room

    The value of `user` will be `None` in case it is us who has been revoked
    operator
    """
    room: Room
    member: User = None


@dataclass(frozen=True)
class PrivateMessageEvent(Event):
    """Emitted when a private message has been received"""
    message: ChatMessage


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
    recommendations: List[ItemRecommendation]
    unrecommendations: List[ItemRecommendation]


@dataclass(frozen=True)
class GlobalRecommendationsEvent(Event):
    recommendations: List[ItemRecommendation]
    unrecommendations: List[ItemRecommendation]


@dataclass(frozen=True)
class ItemRecommendationsEvent(Event):
    item: str
    recommendations: List[ItemRecommendation]


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
class PrivilgedUserAddedEvent(Event):
    """Emitted when a new privileged user has been added"""
    users: List[User]


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


@dataclass(frozen=True)
class TransferStateChanged(Event):
    transfer: Transfer
    state: TransferState.State


# Internal Events

class InternalEvent(Event):
    pass


@dataclass(frozen=True)
class ConnectionStateChangedEvent(InternalEvent):
    connection: Connection
    state: ConnectionState
    close_reason: CloseReason


@dataclass(frozen=True)
class MessageReceivedEvent(InternalEvent):
    """Emitted when a message was received on a connection"""
    message: MessageDataclass
    connection: Connection


@dataclass(frozen=True)
class PeerInitializedEvent(InternalEvent):
    """Emitted when a new connection has been established and the initialization
    message has been received
    """
    connection: PeerConnection
    requested: bool


@dataclass(frozen=True)
class TrackUserEvent(InternalEvent):
    username: str
    flag: TrackingFlag


@dataclass(frozen=True)
class UntrackUserEvent(InternalEvent):
    username: str
    flag: TrackingFlag


@dataclass(frozen=True)
class ScanCompleteEvent(InternalEvent):
    """Emitted when shares scan was completed"""
    folder_count: int
    file_count: int
