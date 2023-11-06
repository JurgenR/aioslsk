from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from ..user.model import User


@dataclass
class Room:
    name: str
    private: bool = False
    users: List[User] = field(default_factory=list)
    """Current list of joined users"""
    joined: bool = False
    user_count: int = 0
    tickers: Dict[str, str] = field(default_factory=dict)
    """Room tickers (room wall)"""

    # Only for private rooms
    members: Set[str] = field(default_factory=set)
    """For private rooms, names of members of the room (excludes owner)"""
    owner: Optional[str] = None
    """For private rooms, name of the room owner"""
    operators: Set[str] = field(default_factory=set)
    """For private rooms, names of operators"""

    def add_user(self, user: User):
        if user not in self.users:
            self.users.append(user)

    def remove_user(self, user: User):
        if user in self.users:
            self.users.remove(user)


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
