from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Dict, List

from .scheduler import Scheduler
from .model import ChatMessage, Room, User

if TYPE_CHECKING:
    from .network.connection import PeerConnection
    from .search import ReceivedSearch, SearchQuery


@dataclass
class DistributedPeer:
    username: str
    connection: PeerConnection
    branch_level: int = None
    branch_root: int = None


@dataclass
class State:
    logged_in = False

    privileges_time_left: int = 0

    # Chat related
    rooms: Dict[str, Room] = field(default_factory=dict)
    users: Dict[str, User] = field(default_factory=dict)
    private_messages: Dict[int, ChatMessage] = field(default_factory=dict)

    # Distributed network related
    potential_parents: List[str] = field(default_factory=list)
    """List of the last potential parents received by the PotentialParents
    commands
    """
    parent: DistributedPeer = None
    children: List[DistributedPeer] = field(default_factory=list)

    # Server vars
    parent_min_speed: int = 0
    parent_speed_ratio: int = 0
    min_parents_in_cache: int = 0
    parent_inactivity_timeout: int = 0
    search_inactivity_timeout: int = 0
    distributed_alive_interval: int = 0
    wishlist_interval: int = 0

    # Search related
    received_searches: Deque[ReceivedSearch] = field(default_factory=lambda: deque(list(), 500))
    search_queries: Dict[int, SearchQuery] = field(default_factory=dict)

    # Global state
    scheduler: Scheduler = None

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
