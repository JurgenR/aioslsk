from __future__ import annotations
from dataclasses import dataclass, field
from enum import auto, Enum, Flag
from typing import Dict, List
from .protocol.primitives import UserStats


class UserStatus(Enum):
    """User status values, everything except the UNKNOWN status are used by the
    server
    """
    UNKNOWN = -1
    OFFLINE = 0
    AWAY = 1
    ONLINE = 2


class TrackingFlag(Flag):
    """Tracking flags hold information how the user is being tracked"""
    REQUESTED = auto()
    """Tracking was explicitly requested by the user"""
    TRANSFER = auto()
    """Tracking was requested through transfer manager"""
    FRIEND = auto()
    """Tracking because the user is a friend"""
    ROOM_USER = auto()
    """Tracking because the user is in a room we are in"""


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

    tracking_flags: TrackingFlag = TrackingFlag(0)

    def has_add_user_flag(self) -> bool:
        """Returns whether this user has any tracking flags set related to
        AddUser
        """
        add_user_flags = TrackingFlag.FRIEND | TrackingFlag.REQUESTED | TrackingFlag.TRANSFER
        return self.tracking_flags & add_user_flags != TrackingFlag(0)

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

    def is_server_message(self) -> bool:
        return self.is_admin and self.user.name == 'server'


@dataclass
class RoomMessage:
    timestamp: int
    user: User
    message: str
    room: Room
