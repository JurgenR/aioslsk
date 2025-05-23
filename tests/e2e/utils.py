import asyncio
from unittest.mock import AsyncMock
import time
from typing import Optional
from aioslsk.client import SoulSeekClient
from aioslsk.network.connection import PeerConnection, PeerConnectionState
from aioslsk.transfer.model import Transfer, TransferState
from aioslsk.search.model import SearchRequest
from .mock.server import MockServer


async def wait_for_clients_connected(mock_server: MockServer, amount: int = 2, timeout: float = 10):
    """Waits until the ``amount`` of peers are registered on the server"""
    start_time = time.time()

    while time.time() < start_time + timeout:
        if len(mock_server.peers) == amount:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"timeout waiting for {amount} peers to have registered to server")


async def wait_for_peer_connection(
        client: SoulSeekClient, username: str, typ: str, timeout: float = 10) -> PeerConnection:
    """Waits until there is an active peer connection from given username and
    type and returns the first
    """
    start_time = time.time()
    while time.time() < start_time + timeout:
        connections = client.network.get_active_peer_connections(username, typ)
        if connections:
            return connections[0]
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"timeout waiting for peer connection from ({username=}, {typ=})")


async def wait_for_peer_connection_state(
        connection: PeerConnection, state: PeerConnectionState, timeout: float = 10):

    start_time = time.time()
    while time.time() < start_time + timeout:
        if connection.state == state:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"timeout waiting for peer connection state ({connection=}, {state=})")


async def wait_until_client_has_parent(client: SoulSeekClient, timeout: float = 10):
    start_time = time.time()
    while time.time() < start_time + timeout:
        if client.distributed_network.parent:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception("timeout waiting for client to have parent")


async def wait_until_client_has_no_parent(client: SoulSeekClient, timeout: float = 10):
    start_time = time.time()
    while time.time() < start_time + timeout:
        if not client.distributed_network.parent:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception("timeout waiting for client to have no parent")


async def wait_until_peer_has_parent(
        mock_server: MockServer, username: str, level: int, root: str,
        timeout: float = 10):
    """Waits until the peer with given ``username`` has reported its parent values
    """
    peer = mock_server.find_peer_by_name(username)

    expected = (level, root, False)

    start_time = time.time()
    while time.time() < start_time + timeout:
        actual = (
            mock_server.distributed_tree[username].root,
            mock_server.distributed_tree[username].level,
            peer.user.enable_parent_search
        )

        if actual != expected:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"timeout waiting for peer ({username=}) to have parent values {expected=}")


async def wait_for_room_owner(
        mock_server: MockServer, room_name: str, owner: Optional[str] = None,
        timeout: float = 10):

    room = mock_server.find_room_by_name(room_name)
    if not room:
        raise Exception(f"no room on the server with name {room_name!r}")

    start = time.time()
    while time.time() < start + timeout:
        if room.owner == owner:
            return
        await asyncio.sleep(0.1)
    raise Exception(f'timeout waiting for server room {room_name!r} to have owner {owner}')


async def wait_until_clients_initialized(mock_server: MockServer, amount: int = 2):
    """Waits until the `amount` of peers is reached and the peers are all
    set with branch values on the server
    """
    await wait_for_clients_connected(mock_server, amount)


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


async def wait_for_search_results(request: SearchRequest, timeout: float = 5):
    start = time.time()
    while time.time() < start + timeout:
        if request.results:
            return
        await asyncio.sleep(0.1)
    raise Exception('timeout waiting for search results')


async def wait_for_transfer_added(
        client: SoulSeekClient, initial_amount: Optional[int] = None, timeout: float = 3) -> Transfer:

    start = time.time()
    if initial_amount is None:
        initial_amount = len(client.transfers.transfers)

    while time.time() < start + timeout:
        if len(client.transfers.transfers) > initial_amount:
            return client.transfers.transfers[-1]
        else:
            await asyncio.sleep(0.01)
    else:
        raise Exception(
            f"transfer {client} did not have a transfer added in {timeout}s "
            f"(initial={initial_amount}, current={len(client.transfers.transfers)})")


async def wait_for_transfer_state(
        transfer: Transfer, state: TransferState.State,
        reason: Optional[str] = None, abort_reason: Optional[str] = None,
        timeout: int = 15):

    start = time.time()

    expected_state = (state, reason, abort_reason)
    current_state = (transfer.state.VALUE, transfer.fail_reason, transfer.abort_reason)
    while time.time() < start + timeout:
        current_state = (transfer.state.VALUE, transfer.fail_reason, transfer.abort_reason)
        if current_state == expected_state:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(
            f"transfer {transfer} did not go to expected state in {timeout}s"
            f"(current={current_state}, expected={expected_state})")


async def wait_for_transfer_to_finish(transfer: Transfer, timeout: int = 60):
    start = time.time()
    while time.time() < start + timeout:
        if transfer.is_finalized():
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"transfer {transfer} did not finish in {timeout}s")


async def wait_for_transfer_to_transfer(transfer: Transfer, timeout: int = 10):
    start = time.time()
    while time.time() < start + timeout:
        if transfer.is_transferring():
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(f"transfer {transfer} did not go into transferring state in {timeout}s")


async def wait_for_remotely_queued_state(
        transfer: Transfer, state: bool = True, timeout: int = 10):

    start = time.time()
    while time.time() < start + timeout:
        if transfer.remotely_queued is state:
            break
        else:
            await asyncio.sleep(0.05)
    else:
        raise Exception(
            f"transfer {transfer} did not have remotely_queued flag set to {state} in {timeout}s "
            f"(state={transfer.state.VALUE.name})")
