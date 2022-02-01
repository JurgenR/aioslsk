from cachetools import TTLCache
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List

from utils import ticket_generator


@dataclass
class Parent:
    branch_level: int = None
    branch_root: str = None
    peer: 'Peer' = None
    connection: 'PeerConnection' = None


@dataclass
class State:
    logged_in = False

    privileges_time_left: int = 0
    privileged_users: List[str] = field(default_factory=list)
    room_list: List[str] = field(default_factory=list)

    parent: Parent = None
    parent_min_speed: int = 0
    parent_speed_ratio: int = 0

    wishlist_interval: int = 0

    connection_requests: TTLCache = TTLCache(maxsize=1000, ttl=15 * 60)

    received_searches: Deque['ReceivedSearch'] = field(default_factory=lambda: deque(list(), 500))

    search_queries: Dict[int, 'SearchQuery'] = field(default_factory=dict)

    ticket_generator = ticket_generator()
