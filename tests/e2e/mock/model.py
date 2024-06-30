from collections import OrderedDict
from dataclasses import dataclass, field
from enum import auto, Enum
from aioslsk.protocol.messages import PrivateChatMessage
from aioslsk.user.model import UserStatus
import typing
from typing import List, Set, Optional
from weakref import WeakValueDictionary


@dataclass
class Settings:
    parent_min_speed: int = 1
    parent_speed_ratio: int = 50
    min_parents_in_cache: int = 10
    parent_inactivity_timeout: int = 300
    search_inactivity_timeout: int = 0
    distributed_alive_interval: int = 0
    wishlist_interval: int = 720


@dataclass(frozen=True)
class QueuedPrivateMessage:
    chat_id: int
    username: str
    message: str
    timestamp: int

    def to_protocol_message(self, is_direct: bool = False) -> PrivateChatMessage:
        return PrivateChatMessage.Response(
            chat_id=self.chat_id,
            timestamp=self.timestamp,
            username=self.username,
            message=self.message,
            is_direct=is_direct
        )


@dataclass
class User:
    name: str
    password: str = ''
    privileges_time_left: int = 0
    is_admin: bool = False

    status: UserStatus = UserStatus.OFFLINE
    avg_speed: int = 0
    uploads: int = 0
    shared_folder_count: int = 0
    shared_file_count: int = 0
    slots_free: int = 0
    country: str = ''

    port: Optional[int] = None
    obfuscated_port: Optional[int] = None

    interests: Set[str] = field(default_factory=set)
    hated_interests: Set[str] = field(default_factory=set)

    queued_private_messages: List[QueuedPrivateMessage] = field(default_factory=list)
    added_users: WeakValueDictionary[str, 'User'] = field(default_factory=WeakValueDictionary)

    # TODO: Investigate what the default values are
    enable_private_rooms: bool = False
    enable_parent_search: bool = False
    enable_public_chat: bool = False
    accept_children: bool = False

    @property
    def privileged(self) -> bool:
        return self.privileges_time_left > 0

    def reset(self):
        """Sets the user to offline and resets all values"""
        self.status = UserStatus.OFFLINE
        self.added_users = WeakValueDictionary()

        self.port = None
        self.obfuscated_port = None

        self.enable_parent_search = False
        self.enable_private_rooms = False

        self.interests = set()
        self.hated_interests = set()


class RoomStatus(Enum):
    PUBLIC = auto()
    PRIVATE = auto()
    UNCLAIMED = auto()


@dataclass
class Room:
    name: str
    joined_users: List[User] = field(default_factory=list)
    tickers: typing.OrderedDict[str, str] = field(default_factory=OrderedDict)
    registered_as_public: bool = False

    # Only for private rooms
    owner: Optional[User] = None
    members: List[User] = field(default_factory=list)
    operators: List[User] = field(default_factory=list)

    @property
    def status(self) -> RoomStatus:
        if self.owner:
            return RoomStatus.PRIVATE
        elif self.joined_users:
            return RoomStatus.PUBLIC
        else:
            return RoomStatus.UNCLAIMED

    @property
    def all_members(self) -> List[User]:
        return self.members + [self.owner, ] if self.owner else []

    def can_join(self, user: User) -> bool:
        return user in self.members or self.owner == user

    def can_add(self, user: User) -> bool:
        """Checks if given `user` can add another user to this room"""
        return user == self.owner or user in self.operators

    def can_remove(self, user: User, target: User) -> bool:
        """Checks if given `user` can remove `target` from this room

        owner can remove: operators, members
        operators can remove: members
        """
        if user == self.owner:
            return True

        if user in self.operators:
            if target != self.owner and target not in self.operators:
                return True

        return False
