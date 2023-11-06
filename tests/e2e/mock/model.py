from dataclasses import dataclass, field
from aioslsk.user.model import UserStatus
from typing import Dict, List, Set


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


@dataclass
class Room:
    name: str
    joined_users: List[User] = field(default_factory=list)
    is_private: bool = False
    tickers: Dict[str, str] = field(default_factory=dict)

    # Only for private rooms
    owner: User = None
    members: List[User] = field(default_factory=list)
    operators: List[User] = field(default_factory=list)

    def get_members(self, exclude_owner: bool = True, exclude_operators: bool = True) -> List[User]:
        """Returns non-owner and non-operator members"""
        exlusions = [self.owner, ] if exclude_owner else []
        exlusions += self.operators if exclude_operators else []

        return [
            member for member in self.members
            if member not in exlusions
        ]

    def can_add(self, user: User):
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