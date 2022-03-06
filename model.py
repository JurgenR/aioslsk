from __future__ import annotations
from dataclasses import dataclass, field
import enum
from typing import List


class UserState(enum.Enum):
    UNKNOWN = -1
    OFFLINE = 0
    AWAY = 1
    ONLINE = 2


@dataclass
class User:
    name: str
    status: int = 0
    country: str = None
    avg_speed: int = 0
    downloads: int = 0
    files: int = 0
    directories: int = 0
    has_slots_free: bool = None

    def update(self, user):
        self.status = user.status
        self.country = user.country
        self.avg_speed = user.avg_speed
        self.downloads = user.downloads
        self.files = user.files
        self.directories = user.directories
        self.has_slots_free = user.has_slots_free


@dataclass
class ChatMessage:
    id: int
    timestamp: int
    user: User
    message: str
    is_admin: bool


@dataclass
class Room:
    name: str
    users: List[User] = field(default_factory=list)
    owner: str = None
    operators: List[str] = field(default_factory=list)
    messages: List[RoomMessage] = field(default_factory=list)
    is_private: bool = False
    joined: bool = False
    user_count: int = 0

    def update(self, room):
        self.users.extend(room.users)
        self.owner = room.owner
        self.operators = room.operators
        self.is_private = room.is_private
        self.messages.extend(room.messages)
        self.joined = room.joined
        self.user_count = room.user_count


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
