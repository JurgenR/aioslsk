from __future__ import annotations
from dataclasses import dataclass, field
from enum import auto, Enum, Flag, IntFlag
import sys
from typing import Optional

from ..protocol.primitives import UserStats


if sys.version_info >= (3, 11):
    slots_params = {'slots': True, 'weakref_slot': True}

else:
    slots_params = {}


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


class TrackingState(Enum):
    UNTRACKED = "untracked"
    TRACKED = "tracked"
    RETRY_PENDING = "retry_pending"


class BlockingFlag(IntFlag):
    NONE = 0
    PRIVATE_MESSAGES = 1
    """Blocks private messages sent by the user"""
    ROOM_MESSAGES = 2
    """Blocks room messages sent by the user"""
    SEARCHES = 4
    """Blocks incoming searches from the user"""
    SHARES = 8
    """Blocks shares, directory listing requests"""
    INFO = 16
    UPLOADS = 32
    """Blocks all uploads and upload requests"""

    # Aliases
    IGNORE = PRIVATE_MESSAGES | ROOM_MESSAGES
    """Ignore all messaging"""
    ALL = IGNORE | SEARCHES | SHARES | INFO | UPLOADS
    """Fully blocks the user: includes messaging, shares requests, uploads"""


@dataclass(**slots_params)
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


@dataclass(**slots_params)
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
