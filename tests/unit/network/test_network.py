from asyncio import Event
import pytest
from typing import Tuple
from unittest.mock import Mock

from aioslsk.events import InternalEventBus
from aioslsk.network.network import Network
from aioslsk.state import State
from aioslsk.settings import Settings


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'pw'
    },
    'sharing': {
        'limits': {
            'upload_speed_kbps': 0,
            'download_speed_kbps': 0
        }
    },
    'network': {
        'server_hostname': 'server.slsk.org',
        'server_port': 2234,
        'listening_port': 10000,
        'use_upnp': False,
        'peer': {
            'obfuscate': False
        }
    },
    'debug': {
        'user_ip_overrides': {}
    }
}


class TestNetworkManager:

    def _create_network(self, settings=None) -> Network:
        settings = settings or DEFAULT_SETTINGS
        state = State()
        network = Network(state, Settings(settings), InternalEventBus(), Event())
        network.server = Mock()

        return network

    @pytest.mark.parametrize(
        'clear_port,obfuscated_port,prefer_obfuscated,expected',
        [
            # No ports should raise an error before the method is ever called
            (1, 0, False, (1, False)),
            (1, 0, True, (1, False)),
            (0, 2, False, (2, True)),
            (0, 2, True, (2, True)),
            (1, 2, False, (1, False)),
            (1, 2, True, (2, True)),
        ]
    )
    def test_selectPort(self, clear_port: int, obfuscated_port: int, prefer_obfuscated: bool, expected: Tuple[int, bool]):
        network = self._create_network()
        network._settings.set('network.peer.obfuscate', prefer_obfuscated)
        actual = network.select_port(clear_port, obfuscated_port)
        assert expected == actual
