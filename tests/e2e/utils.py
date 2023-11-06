import asyncio
from unittest.mock import AsyncMock
import time
from aioslsk.client import SoulSeekClient
from aioslsk.transfer.model import Transfer, TransferState
from aioslsk.search.model import SearchRequest
from .mock.server import MockServer


async def wait_for_clients_connected(mock_server: MockServer, amount: int = 2, timeout: float = 10):
    """Waits until the `amount` of peers are registered on the server"""
    start_time = time.time()

    while time.time() < start_time + timeout:
        if len(mock_server.peers) == amount:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"timeout waiting for {amount} peers to have registered to server")


async def wait_for_peers_distributed_advertised(mock_server: MockServer, timeout: float = 10):
    """Waits for all peers connected the server to have advertised their place
    in the distributed network

    These values are one of the last one's sent and indicate that the client is
    more or less done initializing
    """
    start_time = time.time()
    while time.time() < start_time + timeout:
        if all(
            peer.branch_root is not None and peer.branch_level is not None
            for peer in mock_server.peers
        ):
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception("timeout waiting for peers to have branch values")


async def wait_until_client_has_parent(client: SoulSeekClient, timeout: float = 10):
    start_time = time.time()
    while time.time() < start_time + timeout:
        if client.distributed_network.parent:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception("timeout waiting for client to have parent")


async def wait_until_clients_initialized(mock_server: MockServer, amount: int = 2):
    """Waits until the `amount` of peers is reached and the peers are all
    set with branch values on the server
    """
    await wait_for_clients_connected(mock_server, amount)
    await wait_for_peers_distributed_advertised(mock_server)


async def wait_for_listener_awaited(listener: AsyncMock, timeout: float = 10):
    """Waits for an event to be triggered and returns the first event"""
    start = time.time()
    while time.time() < start + timeout:
        if listener.await_count == 0:
            await asyncio.sleep(0.05)
        else:
            return listener.await_args.args[0]
    else:
        raise Exception(f"timeout reached of {timeout}s waiting for listener to be awaited")


async def wait_for_listener_awaited_events(listener: AsyncMock, amount: int = 1, timeout: float = 10):
    """Waits for multiple events to be triggered and returns events"""
    start = time.time()
    while time.time() < start + timeout:
        if listener.await_count != amount:
            await asyncio.sleep(0.05)
        else:
            return [
                await_arg.args[0]
                for await_arg in listener.await_args_list
            ]
    else:
        raise Exception(f"timeout reached of {timeout}s waiting for listener to be awaited")


async def wait_for_search_request(client: SoulSeekClient, timeout: float = 10):
    """Waits until the client has received a search request"""
    start = time.time()
    while time.time() < start + timeout:
        if len(client.searches.received_searches) > 0:
            return
        await asyncio.sleep(0.1)
    raise Exception('timeout waiting for search results')


async def wait_for_search_results(request: SearchRequest, timeout=5):
    start = time.time()
    while time.time() < start + timeout:
        if request.results:
            return
        await asyncio.sleep(0.1)
    raise Exception('timeout waiting for search results')


async def wait_for_transfer_state(transfer: Transfer, state: TransferState.State, timeout: int = 60):
    start = time.time()
    current_state = transfer.state.VALUE
    while time.time() < start + timeout:
        current_state = transfer.state.VALUE
        if current_state == state:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"transfer {transfer} did not go to state {state} in {timeout}s (was {current_state})")


async def wait_for_transfer_to_finish(transfer: Transfer, timeout: int = 60):
    start = time.time()
    while time.time() < start + timeout:
        if transfer.is_finalized():
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"transfer {transfer} did not finish in {timeout}s")


async def wait_for_transfer_to_transfer(transfer: Transfer, timeout: int = 60):
    start = time.time()
    while time.time() < start + timeout:
        if transfer.is_transferring():
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"transfer {transfer} did not go into transferring state in {timeout}s")
