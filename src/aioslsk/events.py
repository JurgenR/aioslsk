from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from typing import Callable, Dict, List, Type, TYPE_CHECKING

from .model import ChatMessage, Room, RoomMessage, User
from .protocol.primitives import DirectoryData, MessageDataclass
from .search import SearchRequest, SearchResult

if TYPE_CHECKING:
    from .network.connection import (
        Connection,
        ConnectionState,
        CloseReason,
        PeerConnection,
    )
    from .transfer import Transfer, TransferState


logger = logging.getLogger(__name__)


# Internal functions

def on_message(message_class):
    """Decorator for methods listening to specific L{Message} events"""
    def register(event_func):
        event_func._registered_message = message_class
        return event_func

    return register


def build_message_map(obj) -> Dict[Type[MessageDataclass], Callable]:
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

    async def emit(self, event: Event):
        try:
            listeners = self._events[event.__class__]
        except KeyError:
            pass
        else:
            for listener in listeners:
                try:
                    if asyncio.iscoroutinefunction(listener):
                        await listener(event)
                    else:
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
class ServerConnectedEvent(Event):
    pass


@dataclass(frozen=True)
class ServerDisconnectedEvent(Event):
    pass


@dataclass(frozen=True)
class LoginEvent:
    is_success: bool
    greeting: str = None
    reason: str = None


@dataclass(frozen=True)
class KickedEvent(Event):
    pass


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
class RoomTickersEvent:
    room: Room
    tickers: Dict[str, str]


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
    room: Room
    user: User


@dataclass(frozen=True)
class UserLeftRoomEvent(Event):
    room: Room
    user: User


@dataclass(frozen=True)
class RoomJoinedEvent(Event):
    room: Room


@dataclass(frozen=True)
class RoomLeftEvent(Event):
    room: Room


@dataclass(frozen=True)
class AddedToPrivateRoomEvent(Event):
    """Emitted when we are added to a private room"""
    room: Room


@dataclass(frozen=True)
class RemovedFromPrivateRoomEvent(Event):
    """Emitted when we were removed from a private room"""
    room: Room


@dataclass
class ServerMessageEvent(Event):
    """Emitted when the server sends us a message. This is usually a response
    to an action you tried to perform (adding someone to a private room...)
    """
    message: str


@dataclass(frozen=True)
class PrivateMessageEvent(Event):
    user: User
    message: ChatMessage


@dataclass(frozen=True)
class SearchResultEvent(Event):
    query: SearchRequest
    result: SearchResult

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
class MessageReceivedEvent(InternalEvent):
    message: MessageDataclass
    connection: Connection


@dataclass(frozen=True)
class PeerInitializedEvent(InternalEvent):
    connection: PeerConnection
    requested: bool


@dataclass(frozen=True)
class TrackUserEvent(InternalEvent):
    username: str


@dataclass(frozen=True)
class UntrackUserEvent(InternalEvent):
    username: str


@dataclass(frozen=True)
class LoginSuccessEvent(InternalEvent):
    pass
