from __future__ import annotations
from dataclasses import dataclass, field
from enum import auto, Enum, Flag, IntFlag
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


class UploadPermissions(Enum):
    """Upload permissions returned / sent by PeerUserInfoReply message"""
    UNKNOWN = -1
    NOONE = 0
    """Don't allow uploads from anyone"""
    EVERYONE = 1
    """Allow uploads from anyone"""
    USER_LIST = 2
    """Only allow uploads from users in the users list"""
    PERMITTED_LIST = 3
    """Only allow uploads from users in a specific list"""


class TrackingFlag(Flag):
    """Tracking flags hold information how the user is being tracked"""
    REQUESTED = auto()
    """Tracking was explicitly requested by the user"""
    TRANSFER = auto()
    """Tracking was requested through transfer manager"""
    FRIEND = auto()
    """Tracking because the user is a friend"""


class BlockingFlag(IntFlag):
    MESSAGE_USER = 1
    MESSAGE_ROOM = 2

    SEARCH_RESULTS = 4

    TRANSFER_UPLOAD = 8

    PEER_INFO = 16
    PEER_SHARES = 32

    CONNECTION_DISTRIBUTED = 64

    # Aliases
    MESSAGE_ALL = MESSAGE_USER | MESSAGE_ROOM
    PEER_ALL = PEER_INFO | PEER_SHARES

    ALL = MESSAGE_ALL | SEARCH_RESULTS | TRANSFER_UPLOAD | PEER_ALL
    COMPLETE = ALL | CONNECTION_DISTRIBUTED


@dataclass
class User:
    name: str

    # Status info
    status: UserStatus = UserStatus.UNKNOWN
    privileged: bool = False

    # User info
    description: Optional[str] = None
    picture: Optional[bytes] = None
    country: Optional[str] = None

    # User stats
    avg_speed: Optional[int] = None
    uploads: Optional[int] = None
    shared_file_count: Optional[int] = None
    shared_folder_count: Optional[int] = None

    # Upload status
    has_slots_free: Optional[bool] = None
    slots_free: Optional[int] = None
    upload_slots: Optional[int] = None
    queue_length: Optional[int] = None
    upload_permissions: UploadPermissions = UploadPermissions.UNKNOWN

    # Interests
    interests: set[str] = field(default_factory=set)
    hated_interests: set[str] = field(default_factory=set)

    def update_from_user_stats(self, user_stats: UserStats):
        self.avg_speed = user_stats.avg_speed
        self.shared_file_count = user_stats.shared_file_count
        self.shared_folder_count = user_stats.shared_folder_count
        self.uploads = user_stats.uploads

    def clear_all(self):
        """Clears all user data except user status and privileges info and
        country
        """
        self.clear(info=True, interests=True, stats=True, upload_info=True)

    def clear(
            self, info: bool = False, interests: bool = False,
            stats: bool = False, upload_info: bool = False):
        """Resets selected fields"""

        if info:
            self.picture = None
            self.description = None

        if interests:
            self.interests = set()
            self.hated_interests = set()

        if stats:
            self.avg_speed = None
            self.has_slots_free = None
            self.slots_free = None
            self.queue_length = None
            self.uploads = None

        if upload_info:
            self.upload_permissions = UploadPermissions.UNKNOWN
            self.upload_slots = None
            self.has_slots_free = None
            self.queue_length = None
            self.slots_free = None


@dataclass
class ChatMessage:
    """Represents a private chat message"""
    id: int
    timestamp: int
    user: User
    message: str
    is_direct: bool

    def is_server_message(self) -> bool:
        return self.user.name == 'server'

    @property
    def is_admin(self) -> bool:
        """Only kept to keep backward compatibility. Use ``is_direct``

        This property does not actually represent whether the message was sent
        by an admin. Instead it represents whether the message was sent directly
        or was queued on the server before being sent (example, when user was
        offline and came back online)
        """
        return self.is_direct

    @is_admin.setter
    def is_admin(self, value: bool):
        self.is_direct = value
