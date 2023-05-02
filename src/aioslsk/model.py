from __future__ import annotations
from dataclasses import dataclass, field
import enum
from typing import Dict, List
from .protocol.primitives import UserStats


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
    uploads: int = None
    shared_file_count: int = None
    shared_folder_count: int = None
    has_slots_free: bool = None
    slots_free: int = None
    upload_slots: int = None
    queue_length: int = None

    is_tracking: bool = False

    def update_from_user_stats(self, user_stats: UserStats):
        self.avg_speed = user_stats.avg_speed
        self.shared_file_count = user_stats.shared_file_count
        self.shared_folder_count = user_stats.shared_folder_count
        self.uploads = user_stats.uploads


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
    owner: User = None
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


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
