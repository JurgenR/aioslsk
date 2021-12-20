from collections import namedtuple
from dataclasses import dataclass

from utils import ticket_generator


ConnectionRequest = namedtuple('ConnectionRequest', ['ticket', 'username', 'ip', 'port', 'type'])


@dataclass
class Parent:
    branch_level: int = None
    branch_root: str = None
    peer = None
    connection = None


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

    connection_requests = []

    search_queries = {}

    ticket_generator = ticket_generator()
