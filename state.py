from dataclasses import dataclass


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

    search_queries = {}

    # TODO: remove
    branch_level = None
    branch_root = None
