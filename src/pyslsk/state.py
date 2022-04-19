from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Dict, List

from .scheduler import Scheduler
from .model import ChatMessage, Room, User
from .utils import ticket_generator

if TYPE_CHECKING:
    from .connection import PeerConnection
    from .peer import Peer
    from .search import ReceivedSearch, SearchQuery


@dataclass
class Parent:
    branch_level: int = None
    branch_root: str = None
    peer: Peer = None
    connection: PeerConnection = None


@dataclass
class State:
    logged_in = False

    privileges_time_left: int = 0
    privileged_users: List[str] = field(default_factory=list)

    rooms: Dict[str, Room] = field(default_factory=dict)
    users: Dict[str, User] = field(default_factory=dict)
    private_messages: Dict[int, ChatMessage] = field(default_factory=dict)

    parent: Parent = None
    parent_min_speed: int = 0
    parent_speed_ratio: int = 0

    wishlist_interval: int = 0

    received_searches: Deque[ReceivedSearch] = field(default_factory=lambda: deque(list(), 500))
    search_queries: Dict[int, SearchQuery] = field(default_factory=dict)

    scheduler: Scheduler = None
    ticket_generator = ticket_generator()

    def upsert_user(self, user: User) -> User:
        try:
            existing_user = self.users[user.name]
        except KeyError:
            self.users[user.name] = user
            return user
        else:
            existing_user.update(user)
            return existing_user

    def upsert_room(self, room: Room) -> Room:
        try:
            existing_room = self.users[room.name]
        except KeyError:
            self.users[room.name] = room
            return room
        else:
            existing_room.update(room)
            return existing_room

    def get_or_create_user(self, username) -> User:
        try:
            return self.users[username]
        except KeyError:
            user = User(name=username)
            self.users[username] = user
            return user

    def get_or_create_room(self, room_name) -> Room:
        try:
            return self.rooms[room_name]
        except KeyError:
            room = Room(name=room_name)
            self.rooms[room_name] = room
            return room
