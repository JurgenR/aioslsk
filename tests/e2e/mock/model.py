from dataclasses import dataclass, field
from enum import auto, Enum
from aioslsk.user.model import UserStatus
from typing import Dict, List, Set, Optional


@dataclass
class Settings:
    parent_min_speed: int = 1
    parent_speed_ratio: int = 50
    min_parents_in_cache: int = 10
    parent_inactivity_timeout: int = 300
    search_inactivity_timeout: int = 0
    distributed_alive_interval: int = 0
    wishlist_interval: int = 720


@dataclass
class User:
    name: str
    password: str = None
    privileges_time_left: int = 0
    is_admin: bool = False

    status: UserStatus = UserStatus.OFFLINE
    avg_speed: int = 0
    uploads: int = 0
    shared_folder_count: int = 0
    shared_file_count: int = 0
    slots_free: int = 0
    country: str = ''

    port: int = None
    obfuscated_port: int = None

    interests: Set[str] = field(default_factory=set)
    hated_interests: Set[str] = field(default_factory=set)

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
    tickers: Dict[str, str] = field(default_factory=dict)
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
