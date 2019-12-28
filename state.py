class State:
    def __init__(self):
        self.logged_in = False
        self.net_info = {}
        self.privileges_time_left = 0
        self.privileged_users = []
        self.room_list = []
        self.parent_min_speed = 0
        self.parent_speed_ratio = 0
        self.wishlist_interval = 0
