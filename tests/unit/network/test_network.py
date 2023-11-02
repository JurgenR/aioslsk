import pytest
from typing import Tuple
from unittest.mock import AsyncMock, Mock

from aioslsk.events import EventBus
from aioslsk.exceptions import ConnectionFailedError, ListeningConnectionFailedError
from aioslsk.network.network import Network, ListeningConnectionErrorMode
from aioslsk.settings import Settings


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0',
        'password': 'pw'
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
        },
        'limits': {
            'upload_speed_kbps': 0,
            'download_speed_kbps': 0
        }
    },
    'debug': {
        'ip_overrides': {}
    }
}


class TestNetworkManager:

    def _create_network(self, settings=None) -> Network:
        sett = settings or Settings(**DEFAULT_SETTINGS)
        network = Network(sett, EventBus())
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
        network._settings.network.peer.obfuscate = prefer_obfuscated
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
        settings = Settings(**DEFAULT_SETTINGS)
        settings.network.listening.obfuscated_port = 0
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock()
        assert network.listening_connections[1] is None

        await network.connect_listening_ports()
        network.listening_connections[0].connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeAll(self):
        settings = Settings(**DEFAULT_SETTINGS)
        settings.network.listening.error_mode = ListeningConnectionErrorMode.ALL
        network = self._create_network(settings)
        network.listening_connections[0].disconnect = AsyncMock()
        network.listening_connections[1].disconnect = AsyncMock()

        network.listening_connections[0].connect = AsyncMock(side_effect=ConnectionFailedError)
        network.listening_connections[1].connect = AsyncMock(side_effect=ConnectionFailedError)

        await self.verify_error_and_disconnect(network)

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeAny(self):
        settings = Settings(**DEFAULT_SETTINGS)
        settings.network.listening.error_mode = ListeningConnectionErrorMode.ANY
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock()
        network.listening_connections[1].connect = AsyncMock(side_effect=ConnectionFailedError)
        network.listening_connections[0].disconnect = AsyncMock()
        network.listening_connections[1].disconnect = AsyncMock()

        await self.verify_error_and_disconnect(network)

    @pytest.mark.asyncio
    async def test_connectListeningPorts_errorModeClear(self):
        settings = Settings(**DEFAULT_SETTINGS)
        settings.network.listening.error_mode = ListeningConnectionErrorMode.CLEAR
        network = self._create_network(settings)

        network.listening_connections[0].connect = AsyncMock(side_effect=ConnectionFailedError)
        network.listening_connections[1].connect = AsyncMock()
        network.listening_connections[0].disconnect = AsyncMock()
        network.listening_connections[1].disconnect = AsyncMock()

        await self.verify_error_and_disconnect(network)

    async def verify_error_and_disconnect(self, network: Network):
        with pytest.raises(ListeningConnectionFailedError):
            await network.connect_listening_ports()

        network.listening_connections[0].disconnect.assert_awaited_once()
        network.listening_connections[1].disconnect.assert_awaited_once()
