from aioslsk.client import SoulSeekClient
from .mock.server import MockServer, ChainParentsStrategy
from .fixtures import mock_server, clients
from .utils import (
    wait_until_clients_initialized,
    wait_until_client_has_parent,
    wait_for_search_request,
)
import pytest
from typing import List


def set_upload_speed_for_client(mock_server: MockServer, client: SoulSeekClient, value: int = 10000):
    username = client.settings.credentials.username
    mock_server.set_upload_speed(username, uploads=10, speed=value)


def set_upload_speed_for_clients(mock_server: MockServer, clients: List[SoulSeekClient], value: int = 10000):
    """Sets a dummy upload speed on the mock server for all clients"""
    for client in clients:
        set_upload_speed_for_client(mock_server, client, value=value)


class TestE2EDistributed:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clients", [2], indirect=True)
    async def test_root_user(self, mock_server: MockServer, clients: List[SoulSeekClient]):
        """Tests when a user gets a search request directly from the server the
        peer becomes root
        """
        await wait_until_clients_initialized(mock_server, amount=len(clients))

        client1, client2 = clients
        client1_user = client1.settings.credentials.username
        client2_user = client2.settings.credentials.username

        # Send a search request to make client1 root
        await mock_server.send_search_request(
            username=client1_user,
            sender=client2_user,
            query='this should not match anything',
            ticket=1
        )

        await wait_until_client_has_parent(client1)

        assert client1.distributed_network.parent is not None
        assert client1.distributed_network.parent.username == client1_user
        assert client1.distributed_network.parent.branch_root == client1_user
        assert client1.distributed_network.parent.branch_level == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clients", [2], indirect=True)
    async def test_level1_user(self, mock_server: MockServer, clients: List[SoulSeekClient]):
        """Tests when a user gets a search request directly from the server the
        peer becomes root
        """
        mock_server.distributed_strategy = ChainParentsStrategy(mock_server.peers)
        set_upload_speed_for_clients(mock_server, clients)
        await wait_until_clients_initialized(mock_server, amount=len(clients))

        client1, client2 = clients
        client1_user = client1.settings.credentials.username
        client2_user = client2.settings.credentials.username

        # Send a search request to make client1 root
        await mock_server.send_search_request(
            username=client1_user,
            sender=client2_user,
            query='this should not match anything',
            ticket=1
        )

        await wait_until_client_has_parent(client1)

        await mock_server.send_potential_parents(client2_user)

        await wait_until_client_has_parent(client2)

        # Verify CLIENT 1
        assert len(client1.distributed_network.children) == 1
        assert client1.distributed_network.children[0].username == client2_user

        # Verify CLIENT 2
        assert client2.distributed_network.parent is not None
        assert client2.distributed_network.parent.username == client1_user
        assert client2.distributed_network.parent.branch_root == client1_user
        assert client2.distributed_network.parent.branch_level == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clients", [3], indirect=True)
    async def test_level2_user(self, mock_server: MockServer, clients: List[SoulSeekClient]):
        """Tests when a user gets a search request directly from the server the
        peer becomes root
        """
        mock_server.distributed_strategy = ChainParentsStrategy(mock_server.peers)
        set_upload_speed_for_clients(mock_server, clients)
        await wait_until_clients_initialized(mock_server, amount=len(clients))

        client1, client2, client3 = clients
        client1_user = client1.settings.credentials.username
        client2_user = client2.settings.credentials.username
        client3_user = client3.settings.credentials.username

        ### Make CLIENT 1 root
        await mock_server.send_search_request(
            username=client1_user,
            sender=client2_user,
            query='this should not match anything',
            ticket=1
        )

        await wait_until_client_has_parent(client1)

        ### Make CLIENT 1 parent of CLIENT 2

        await mock_server.send_potential_parents(client2_user)

        await wait_until_client_has_parent(client2)

        ### Make CLIENT 2 parent of CLIENT 3

        await mock_server.send_potential_parents(client3_user)

        await wait_until_client_has_parent(client3)

        # Verify CLIENT 1
        assert client1.distributed_network.parent is not None
        assert client1.distributed_network.parent.username == client1_user
        assert client1.distributed_network.parent.branch_root == client1_user
        assert client1.distributed_network.parent.branch_level == 0

        assert len(client1.distributed_network.children) == 1
        assert client1.distributed_network.children[0].username == client2_user

        # Verify CLIENT 2
        assert client2.distributed_network.parent is not None
        assert client2.distributed_network.parent.username == client1_user
        assert client2.distributed_network.parent.branch_root == client1_user
        assert client2.distributed_network.parent.branch_level == 0

        assert len(client2.distributed_network.children) == 1
        assert client2.distributed_network.children[0].username == client3_user

        # Verify CLIENT 3
        assert client3.distributed_network.parent is not None
        assert client3.distributed_network.parent.username == client2_user
        assert client3.distributed_network.parent.branch_root == client1_user
        # Our parent should be at 1 (meaning we are at 2)
        assert client3.distributed_network.parent.branch_level == 1

        assert len(client3.distributed_network.children) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clients", [4], indirect=True)
    async def test_level2_sendSearchRequest(self, mock_server: MockServer, clients: List[SoulSeekClient]):
        """Tests if clients on multiple levels in the network receive a search
        request
        """
        mock_server.distributed_strategy = ChainParentsStrategy(mock_server.peers)
        set_upload_speed_for_clients(mock_server, clients)
        await wait_until_clients_initialized(mock_server, amount=len(clients))

        client1, client2, client3, client4 = clients
        client1_user = client1.settings.credentials.username
        client2_user = client2.settings.credentials.username
        client3_user = client3.settings.credentials.username
        client4_user = client4.settings.credentials.username

        # Register mock event listeners

        ### Make CLIENT 1 root
        await mock_server.send_search_request(
            username=client1_user,
            sender=client2_user,
            query='this should not match anything',
            ticket=1
        )
        await wait_until_client_has_parent(client1)
        # Remove the query made to make client1 root
        client1.searches.received_searches.clear()

        ### Make CLIENT 1 parent of CLIENT 2
        await mock_server.send_potential_parents(client2_user)
        await wait_until_client_has_parent(client2)

        ### Make CLIENT 2 parent of CLIENT 3
        await mock_server.send_potential_parents(client3_user)
        await wait_until_client_has_parent(client3)

        # Perform search
        await client4.searches.search('bogus')

        await wait_for_search_request(client1)
        await wait_for_search_request(client2)
        await wait_for_search_request(client3)

        for client in [client1, client2, client3]:
            rec_search = client.searches.received_searches.pop()
            assert rec_search.username == client4_user
            assert rec_search.query == 'bogus'
