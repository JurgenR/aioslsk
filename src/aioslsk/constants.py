import re

DEFAULT_LISTENING_HOST: str = '0.0.0.0'
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
SERVER_RESPONSE_TIMEOUT: float = 30
DISCONNECT_TIMEOUT: float = 10
PATH_SEPERATOR_PATTERN = re.compile(r"[\\/]+")
"""Pattern for splitting/normalizing remote paths"""
UPNP_SEARCH_TIMEOUT: int = 10
POTENTIAL_PARENTS_CACHE_SIZE: int = 20
"""Maximum amount of potential parents stored"""
DEFAULT_COMMAND_TIMEOUT: float = 10
