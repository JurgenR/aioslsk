from .events import EventBus, InternalEventBus
from .network.network import Network
from .state import State

from typing import Dict, List


class SocialManager:

    def __init__(self, network: Network, event_bus: EventBus, internal_event_bus: InternalEventBus):
        self.users: Dict[] =
