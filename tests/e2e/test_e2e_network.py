from aioslsk.client import SoulSeekClient
from aioslsk.network.connection import PeerConnectionType, PeerConnectionState
from .mock.server import MockServer
from .fixtures import mock_server, client_1, client_2
from .utils import (
    wait_for_peer_connection,
    wait_until_clients_initialized,
)
import pytest


class TestNetwork:

    @pytest.mark.asyncio
    async def test_create_peer_connection_direct(
            self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=2)

        username_1 = client_1.session.user.name
        username_2 = client_2.session.user.name

        connection_1 = await client_1.network.create_peer_connection(
            username=username_2, typ=PeerConnectionType.PEER)

        assert connection_1.connection_state == PeerConnectionState.ESTABLISHED
        assert connection_1.connection_type == PeerConnectionType.PEER
        assert connection_1.incoming is False
        assert connection_1.username == username_2

        # Internally this will wait will use get_active_peer_connections which
        # will only return connections with state ESTABLISHED
        connection_2 = await wait_for_peer_connection(
            client_2, username=username_1, typ=PeerConnectionType.PEER)

        assert connection_2.connection_state == PeerConnectionState.ESTABLISHED
        assert connection_2.connection_type == PeerConnectionType.PEER
        assert connection_2.incoming is True
        assert connection_2.username == username_1

    @pytest.mark.asyncio
    async def test_create_peer_connection_indirect(
            self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=2)
        await client_2.network.disconnect_listening_ports()

        username_1 = client_1.session.user.name
        username_2 = client_2.session.user.name

        connection_1 = await client_1.network.create_peer_connection(
            username=username_2, typ=PeerConnectionType.PEER)

        assert connection_1.connection_state == PeerConnectionState.ESTABLISHED
        assert connection_1.connection_type == PeerConnectionType.PEER
        assert connection_1.incoming is True
        assert connection_1.username == username_2

        # Internally this will wait will use get_active_peer_connections which
        # will only return connections with state ESTABLISHED
        connection_2 = await wait_for_peer_connection(
            client_2, username=username_1, typ=PeerConnectionType.PEER)

        assert connection_2.connection_state == PeerConnectionState.ESTABLISHED
        assert connection_2.connection_type == PeerConnectionType.PEER
        assert connection_2.incoming is False
        assert connection_2.username == username_1

