from asyncio import Event
import copy
import pytest
from typing import Tuple
from unittest.mock import AsyncMock, Mock

from aioslsk.events import InternalEventBus
from aioslsk.exceptions import ConnectionFailedError, ListeningConnectionFailedError
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
        'server': {
            'hostname': 'server.slsk.org',
            'port': 2234
        },
        'listening': {
            'error_mode': 'all',
            'port': 10000,
            'obfuscated_port': 10001
        },
        'upnp': {
            'enabled': False
        },
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
        settings = settings or copy.deepcopy(DEFAULT_SETTINGS)
        state = State()
        network = Network(state, Settings(settings), InternalEventBus(), Event())
        network.server_connection = Mock()

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

    @pytest.mark.asyncio
    async def test_connectListeningPorts(self):
        network = self._create_network()
        network.listening_connections[0].connect = AsyncMock()
        network.listening_connections[1].connect = AsyncMock()

        await network.connect_listening_ports()
        network.listening_connections[0].connect.assert_awaited_once()
        network.listening_connections[1].connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connectListeningPorts_onePort(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['network']['listening']['obfuscated_port'] = 0
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock()
        assert network.listening_connections[1] is None

        await network.connect_listening_ports()
        network.listening_connections[0].connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeAll(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['network']['listening']['error_mode'] = 'all'
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock(side_effect=ConnectionFailedError)
        network.listening_connections[1].connect = AsyncMock(side_effect=ConnectionFailedError)

        with pytest.raises(ListeningConnectionFailedError):
            await network.connect_listening_ports()

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeAny(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['network']['listening']['error_mode'] = 'any'
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock()
        network.listening_connections[1].connect = AsyncMock(side_effect=ConnectionFailedError)

        with pytest.raises(ListeningConnectionFailedError):
            await network.connect_listening_ports()

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeClear(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings['network']['listening']['error_mode'] = 'clear'
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock(side_effect=ConnectionFailedError)
        network.listening_connections[1].connect = AsyncMock()

        with pytest.raises(ListeningConnectionFailedError):
            await network.connect_listening_ports()
