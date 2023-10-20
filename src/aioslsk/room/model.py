from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from ..user.model import User


@dataclass
class Room:
    name: str
    private: bool = False
    users: List[User] = field(default_factory=list)
    joined: bool = False
    user_count: int = 0
    tickers: Dict[str, str] = field(default_factory=dict)

    # Only for private rooms
    members: List[User] = field(default_factory=list)
    owner: Optional[User] = None
    operators: List[User] = field(default_factory=list)
    is_operator: bool = False

    def add_user(self, user: User):
        if user not in self.users:
            self.users.append(user)

    def remove_user(self, user: User):
        if user in self.users:
            self.users.remove(user)

    def add_operator(self, user: User):
        if user not in self.operators:
            self.operators.append(user)

    def remove_operator(self, user: User):
        if user in self.operators:
            self.operators.remove(user)

    def add_member(self, user: User):
        if user not in self.members:
            self.members.append(user)

    def remove_member(self, user: User):
        if user in self.members:
            self.members.remove(user)


@dataclass
class ChatMessage:
    id: int
    timestamp: int
    user: User
    message: str
    is_admin: bool

    def is_server_message(self) -> bool:
        return self.is_admin and self.user.name == 'server'


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
