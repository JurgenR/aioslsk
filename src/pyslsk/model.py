from __future__ import annotations
from dataclasses import dataclass, field
import enum
from typing import List


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

    status: int = UserStatus.OFFLINE.value
    privileged: bool = False

    avg_speed: int = None
    downloads: int = None
    files: int = None
    directories: int = None
    has_slots_free: bool = None
    queue_length: int = None
    total_uploads: int = None

    def update(self, user):
        self.status = user.status
        self.country = user.country
        self.avg_speed = user.avg_speed
        self.downloads = user.downloads
        self.files = user.files
        self.directories = user.directories
        self.has_slots_free = user.has_slots_free


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
