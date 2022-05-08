from __future__ import annotations
from dataclasses import dataclass
import inspect
import logging
from typing import Callable, Dict, List, Tuple, Type

from .model import ChatMessage, Room, RoomMessage, User
from .messages import DirectoryData


logger = logging.getLogger()


# Internal functions

def on_message(message_class):
    """Decorator for methods listening to specific L{Message} events"""
    def register(event_func):
        try:
            event_func._registered_messages.add(message_class)
        except AttributeError:
            event_func._registered_messages = set([message_class, ])
        return event_func

    return register


def get_listener_methods(obj, message_class) -> List[Callable]:
    """Gets a list of methods from given L{obj} which are registered to listen
    to L{message_class} (through the L{on_message} decorator)

    @return: List of listening methods
    """
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    listening_methods = []
    for _, method in methods:
        if message_class in getattr(method, '_registered_messages', []):
            listening_methods.append(method)
    return listening_methods


# External functions

class EventBus:

    def __init__(self):
        self._events: Dict[Type[BaseEvent], List[Callable[[BaseEvent], None]]] = dict()

    def register(self, event_class: Type[BaseEvent], listener: Callable[[BaseEvent], None]):
        try:
            self._events[event_class].append(listener)
        except KeyError:
            self._events[event_class] = [listener, ]

    def emit(self, event: BaseEvent):
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


class BaseEvent:
    pass


@dataclass(frozen=True)
class UserAddEvent(BaseEvent):
    user: User


@dataclass(frozen=True)
class RoomListEvent(BaseEvent):
    rooms: List[Room]


@dataclass(frozen=True)
class RoomMessageEvent(BaseEvent):
    message: RoomMessage


@dataclass(frozen=True)
class RoomJoinedEvent(BaseEvent):
    room: Room


@dataclass(frozen=True)
class RoomLeftEvent(BaseEvent):
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
class UserJoinedRoomEvent(BaseEvent):
    user: User
    room: Room


@dataclass(frozen=True)
class UserLeftRoomEvent(BaseEvent):
    user: User
    room: Room


@dataclass(frozen=True)
class PrivateMessageEvent(BaseEvent):
    user: User
    message: ChatMessage


@dataclass(frozen=True)
class PeerSharesReplyEvent(BaseEvent):
    username: str
    directories: List[DirectoryData]
