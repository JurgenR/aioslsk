from __future__ import annotations
from dataclasses import dataclass, field
import enum
from typing import Dict, List


class UserStatus(enum.Enum):
    UNKNOWN = -1
    OFFLINE = 0
    AWAY = 1
    ONLINE = 2


@dataclass
class User:
    name: str
    country: str = None
    description: str = None
    picture: str = None

    status: UserStatus = UserStatus.UNKNOWN
    privileged: bool = False

    avg_speed: int = None
    downloads: int = None
    files: int = None
    directories: int = None
    has_slots_free: bool = None
    slots_free: int = None
    upload_slots: int = None
    queue_length: int = None

    is_tracking: bool = False


@dataclass
class Room:
    name: str
    users: List[User] = field(default_factory=list)
    owner: str = None
    operators: List[User] = field(default_factory=list)
    messages: List[RoomMessage] = field(default_factory=list)
    is_private: bool = False
    is_operator: bool = False
    joined: bool = False
    user_count: int = 0
    tickers: Dict[str, str] = field(default_factory=dict)

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


@dataclass
class ChatMessage:
    id: int
    timestamp: int
    user: User
    message: str
    is_admin: bool


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
