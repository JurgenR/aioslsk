from __future__ import annotations
from dataclasses import dataclass
from enum import auto, Enum, Flag
from typing import Optional
from ..protocol.primitives import UserStats


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
    country: Optional[str] = None
    description: Optional[str] = None
    picture: Optional[str] = None

    status: UserStatus = UserStatus.UNKNOWN
    privileged: bool = False

    avg_speed: Optional[int] = None
    uploads: Optional[int] = None
    shared_file_count: Optional[int] = None
    shared_folder_count: Optional[int] = None
    has_slots_free: Optional[bool] = None
    slots_free: Optional[int] = None
    upload_slots: Optional[int] = None
    queue_length: Optional[int] = None

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
class ChatMessage:
    id: int
    timestamp: int
    user: User
    message: str
    is_admin: bool

    def is_server_message(self) -> bool:
        return self.is_admin and self.user.name == 'server'
