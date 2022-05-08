from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Dict, List, Tuple

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
class Child:
    peer: Peer
    connection: PeerConnection


@dataclass
class State:
    logged_in = False

    privileges_time_left: int = 0

    rooms: Dict[str, Room] = field(default_factory=dict)
    users: Dict[str, User] = field(default_factory=dict)
    private_messages: Dict[int, ChatMessage] = field(default_factory=dict)

    potential_parents: List[Tuple[str, str, int]] = field(default_factory=list)
    """List of the last potential parents received by the NetInfo commands (username, ip, port)"""
    parent: Parent = None
    children: List[Child] = field(default_factory=list)

    parent_min_speed: int = 0
    parent_speed_ratio: int = 0
    min_parents_in_cache: int = 0
    search_inactivity_timeout: int = 0
    distributed_alive_interval: int = 0

    wishlist_interval: int = 0

    received_searches: Deque[ReceivedSearch] = field(default_factory=lambda: deque(list(), 500))
    search_queries: Dict[int, SearchQuery] = field(default_factory=dict)

    scheduler: Scheduler = None
    ticket_generator = ticket_generator()

    def upsert_room(self, room: Room) -> Room:
        try:
            existing_room = self.rooms[room.name]
        except KeyError:
            self.rooms[room.name] = room
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
