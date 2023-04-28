from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Union

from .model import ChatMessage, Room, User
from .search import ReceivedSearch, SearchRequest


@dataclass
class State:
    privileges_time_left: int = 0

    # Chat related
    rooms: Dict[str, Room] = field(default_factory=dict)
    users: Dict[str, User] = field(default_factory=dict)
    private_messages: Dict[int, ChatMessage] = field(default_factory=dict)

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
    search_queries: Dict[int, SearchRequest] = field(default_factory=dict)

    def get_or_create_user(self, user: Union[str, User]) -> User:
        """Retrieves the user with given name or return the existing `User`
        object. If a `User` object is passed in it will be checked if it exists,
        otherwise it will get added
        """
        if isinstance(user, User):
            if user in self.users.values():
                return user
            else:
                self.users[user.name] = user
                return user

        try:
            return self.users[user]
        except KeyError:
            user_object = User(name=user)
            self.users[user] = user_object
            return user_object

    def get_or_create_room(self, room_name: str, private: bool = False) -> Room:
        try:
            return self.rooms[room_name]
        except KeyError:
            room = Room(name=room_name, private=private)
            self.rooms[room_name] = room
            return room
