from cachetools import TTLCache
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List

from messages import Message
from utils import ticket_generator


@dataclass
class ConnectionRequest:
    ticket: int
    username: str
    ip: str
    port: int
    typ: str
    connection: 'PeerConnection'
    is_requested_by_us: bool
    messages: List[Message] = field(default_factory=lambda: [])


@dataclass
class Parent:
    branch_level: int = None
    branch_root: str = None
    peer: 'Peer' = None
    connection: 'PeerConnection' = None


@dataclass
class State:
    logged_in = False

    privileges_time_left = 0
    privileged_users = []
    room_list = []

    parent: Parent = None
    parent_min_speed = 0
    parent_speed_ratio = 0

    wishlist_interval = 0

    connection_requests = TTLCache(maxsize=1000, ttl=15 * 60)

    search_queries = {}
    transfers = []

    ticket_generator = ticket_generator()

    def expire_caches(self, cache_lock):
        with cache_lock:
            self.connection_requests.expire()
