from __future__ import annotations
from dataclasses import dataclass
import inspect
import logging
from typing import Callable, Dict, List, Tuple, Type, TYPE_CHECKING

from .model import ChatMessage, Room, RoomMessage, User
from .messages import (
    DirectoryData,
    DistributedMessage,
    Message,
    PeerInitializationMessage,
    PeerMessage,
    ServerMessage,
)
from .search import SearchQuery, SearchResult

if TYPE_CHECKING:
    from .connection import (
        Connection,
        ConnectionState,
        CloseReason,
        PeerConnection,
        PeerConnectionState,
        ServerConnection,
    )
    from .transfer import Transfer, TransferState


logger = logging.getLogger()


# Internal functions

def on_message(message_class):
    """Decorator for methods listening to specific L{Message} events"""
    def register(event_func):
        event_func._registered_message = message_class
        return event_func

    return register


def build_message_map(obj) -> Dict[Type[Message], Callable]:
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    mapping = {}
    for _, method in methods:
        registered_message = getattr(method, '_registered_message', None)
        if registered_message:
            mapping[registered_message] = method
    return mapping


# External functions

class EventBus:

    def __init__(self):
        self._events: Dict[Type[Event], List[Callable[[Event], None]]] = dict()

    def register(self, event_class: Type[Event], listener: Callable[[Event], None]):
        try:
            self._events[event_class].append(listener)
        except KeyError:
            self._events[event_class] = [listener, ]

    def emit(self, event: Event):
        try:
            listeners = self._events[event.__class__]
        except KeyError:
            pass
        else:
            for listener in listeners:
                try:
                    listener(event)
                except Exception:
                    logger.exception(f"exception notifying listener {listener!r} of event {event!r}")


# Interal functions

class InternalEventBus(EventBus):

    pass


# High Level Events
class Event:
    pass


@dataclass(frozen=True)
class ServerDisconnectedEvent(Event):
    pass


@dataclass(frozen=True)
class UserAddEvent(Event):
    user: User


@dataclass(frozen=True)
class UserStatsEvent(Event):
    user: User


@dataclass(frozen=True)
class UserStatusEvent(Event):
    user: User


@dataclass(frozen=True)
class UserModifiedEvent(Event):
    user: User


@dataclass(frozen=True)
class RoomListEvent(Event):
    rooms: List[Room]


@dataclass(frozen=True)
class RoomMessageEvent(Event):
    message: RoomMessage


@dataclass(frozen=True)
class RoomJoinedEvent(Event):
    room: Room


@dataclass(frozen=True)
class RoomLeftEvent(Event):
    room: Room


@dataclass(frozen=True)
class RoomTickersEvent:
    room: Room
    tickers: List[Tuple[User, str]]


@dataclass(frozen=True)
class RoomTickerAddedEvent:
    room: Room
    user: User
    ticker: str


@dataclass(frozen=True)
class RoomTickerRemovedEvent:
    room: Room
    user: User


@dataclass(frozen=True)
class UserJoinedRoomEvent(Event):
    user: User
    room: Room


@dataclass(frozen=True)
class UserLeftRoomEvent(Event):
    user: User
    room: Room


@dataclass(frozen=True)
class UserJoinedPrivateRoomEvent(Event):
    room: Room


@dataclass(frozen=True)
class UserLeftPrivateRoomEvent(Event):
    room: Room


@dataclass(frozen=True)
class PrivateMessageEvent(Event):
    user: User
    message: ChatMessage


@dataclass(frozen=True)
class SearchResultEvent(Event):
    query: SearchQuery
    result: SearchResult

# Peer


@dataclass(frozen=True)
class UserInfoReplyEvent(Event):
    user: User


@dataclass(frozen=True)
class UserSharesReplyEvent(Event):
    user: User
    directories: List[DirectoryData]


# Transfer

@dataclass(frozen=True)
class TransferAddedEvent(Event):
    transfer: Transfer


@dataclass(frozen=True)
class TransferStateChanged(Event):
    transfer: Transfer
    state: TransferState


# Internal Events

class InternalEvent(Event):
    pass


@dataclass(frozen=True)
class ConnectionStateChangedEvent(InternalEvent):
    connection: Connection
    state: ConnectionState
    close_reason: CloseReason


@dataclass(frozen=True)
class PeerConnectionStateChangedEvent(InternalEvent):
    connection: PeerConnection
    state: PeerConnectionState
    previous_state: PeerConnectionState


@dataclass(frozen=True)
class PeerConnectionAcceptedEvent(InternalEvent):
    connection: PeerConnection


@dataclass(frozen=True)
class ServerMessageEvent(InternalEvent):
    message: ServerMessage
    connection: ServerConnection


@dataclass(frozen=True)
class PeerInitializationMessageEvent(InternalEvent):
    message: PeerInitializationMessage
    connection: PeerConnection


@dataclass(frozen=True)
class PeerMessageEvent(InternalEvent):
    message: PeerMessage
    connection: PeerConnection


@dataclass(frozen=True)
class DistributedMessageEvent(InternalEvent):
    message: DistributedMessage
    connection: PeerConnection


@dataclass(frozen=True)
class PeerInitializedEvent(InternalEvent):
    connection: PeerConnection


@dataclass(frozen=True)
class PeerInitializationFailedEvent(InternalEvent):
    ticket: int
    username: str
    type: str


@dataclass(frozen=True)
class TransferOffsetEvent(InternalEvent):
    connection: PeerConnection
    offset: int


@dataclass(frozen=True)
class TransferTicketEvent(InternalEvent):
    connection: PeerConnection
    ticket: int


@dataclass(frozen=True)
class TransferDataSentEvent(InternalEvent):
    connection: PeerConnection
    tokens_taken: int
    bytes_sent: int


@dataclass(frozen=True)
class TransferDataReceivedEvent(InternalEvent):
    connection: PeerConnection
    tokens_taken: int
    data: bytes


@dataclass(frozen=True)
class LoginEvent(InternalEvent):
    success: bool
