from __future__ import annotations
from dataclasses import dataclass, field
import sys
from typing import Optional

from ..user.model import User


if sys.version_info >= (3, 11):
    slots_params = {'slots': True, 'weakref_slot': True}

else:
    slots_params = {}


@dataclass(**slots_params)
class Room:
    name: str
    private: bool = False
    users: list[User] = field(default_factory=list)
    """Current list of joined users"""
    joined: bool = False
    user_count: int = 0
    tickers: dict[str, str] = field(default_factory=dict)
    """Room tickers (room wall)"""

    # Only for private rooms
    members: set[str] = field(default_factory=set)
    """For private rooms, names of members of the room (excludes owner)"""
    owner: Optional[str] = None
    """For private rooms, name of the room owner"""
    operators: set[str] = field(default_factory=set)
    """For private rooms, names of operators"""

    def add_user(self, user: User):
        if user not in self.users:
            self.users.append(user)

    def remove_user(self, user: User):
        if user in self.users:
            self.users.remove(user)


@dataclass(**slots_params)
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
