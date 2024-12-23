import re


DEFAULT_LISTENING_HOST: str = '0.0.0.0'
DEFAULT_PARENT_MIN_SPEED: int = 1
DEFAULT_PARENT_SPEED_RATIO: int = 50
DEFAULT_WISHLIST_INTERVAL: int = 600
DEFAULT_READ_TIMEOUT: float = 60
PEER_CONNECT_TIMEOUT: float = 10
"""Direct connection timeout"""
PEER_INDIRECT_CONNECT_TIMEOUT: float = 60
"""Indirect connection timeout"""
PEER_INIT_TIMEOUT: float = 5
"""Timeout waiting for Peer Initialization message"""
PEER_READ_TIMEOUT: float = 60
"""Timeout waiting for message on a peer or distributed connection"""
TRANSFER_TIMEOUT: float = 180
"""Timeout waiting for new data on a file connection"""
TRANSFER_REPLY_TIMEOUT = 30
SERVER_CONNECT_TIMEOUT: float = 30
SERVER_LOGIN_TIMEOUT: float = 30
SERVER_PING_INTERVAL: float = 5 * 60
SERVER_READ_TIMEOUT: float = SERVER_PING_INTERVAL * 2
DISCONNECT_TIMEOUT: float = 5
PATH_SEPERATOR_PATTERN = re.compile(r"[\\/]+")
"""Pattern for splitting/normalizing remote paths"""
UPNP_DEFAULT_CHECK_INTERVAL: int = 600
UPNP_DEFAULT_LEASE_DURATION: int = 6 * 60 * 60
UPNP_DEFAULT_SEARCH_TIMEOUT: int = 10
UPNP_MAPPING_SERVICES: list[str] = ["WANIPC", "WANPPP"]
POTENTIAL_PARENTS_CACHE_SIZE: int = 20
"""Maximum amount of potential parents stored"""
DEFAULT_COMMAND_TIMEOUT: float = 10
MIN_TRANSFER_MGMT_INTERVAL: float = 0.05
MAX_TRANSFER_MGMT_INTERVAL: float = 0.25
