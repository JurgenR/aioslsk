from dataclasses import dataclass

from utils import ticket_generator

from collections import namedtuple


ConnectionRequest = namedtuple('ConnectionRequest', ['ticket', 'username', 'ip', 'port', 'type'])


@dataclass
class State:
    logged_in = False

    net_info = {}
    privileges_time_left = 0
    privileged_users = []
    room_list = []
    parent_min_speed = 0
    parent_speed_ratio = 0
    wishlist_interval = 0

    has_parent = False
    branch_level = None
    branch_root = None

    connection_requests = []

    search_queries = {}

    ticket_generator = ticket_generator()

    def set_parent(self, branch_level, branch_root):
        self.has_parent = True
        self.branch_level = branch_level
        self.branch_root = branch_root

    def unset_parent(self):
        self.has_parent = False
        self.branch_level = None
        self.branch_root = None
