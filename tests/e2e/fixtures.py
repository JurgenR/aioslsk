import asyncio
from async_timeout import timeout as atimeout
from collections.abc import AsyncGenerator
import os
from pathlib import Path
import pytest_asyncio
from pytest import FixtureRequest
import shutil

from aioslsk.client import SoulSeekClient
from aioslsk.events import SessionInitializedEvent
from aioslsk.shares.model import DirectoryShareMode
from aioslsk.settings import (
    CredentialsSettings,
    ListeningSettings,
    NetworkSettings,
    ReconnectSettings,
    ServerSettings,
    Settings,
    SharedDirectorySettingEntry,
    SharesSettings,
    UpnpSettings,
)
from .mock.server import MockServer


DEFAULT_SERVER_HOSTNAME = '0.0.0.0'
DEFAULT_SERVER_PORT = 4444
DEFAULT_PASSWORD = 'Password'
FILE_SHARES = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', 'unit', 'resources', 'shared')


def create_client(
        tmp_path: Path, username: str, port: int,
        server_port: int = DEFAULT_SERVER_PORT, password: str = DEFAULT_PASSWORD) -> SoulSeekClient:
    """Creates a new client object

    :param tmp_path: Path in which downloads and shared items are stored
    :param username: Username of the user to login with
    :param port: Listening port
    :param server_port: Server port to connect to
    :param password: Password of the user to login with
    """
    download_dir = tmp_path / username / 'downloads'
    download_dir.mkdir(parents=True, exist_ok=True)
    shared_dir = tmp_path / username / 'shared'
    shared_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FILE_SHARES, shared_dir, dirs_exist_ok=True)

    settings = Settings(
        credentials=CredentialsSettings(
            username=username,
            password=password
        ),
        network=NetworkSettings(
            server=ServerSettings(
                hostname='127.0.0.1',
                port=server_port,
                reconnect=ReconnectSettings(auto=False)
            ),
            listening=ListeningSettings(
                port=port,
                obfuscated_port=port + 1
            ),
            upnp=UpnpSettings(enabled=False)
        ),
        shares=SharesSettings(
            # Explicitly set to false as this would just schedule a scan in the
            # background. For the tests we want to make sure this scan is
            # complete and manually trigger it
            scan_on_start=False,
            download=str(download_dir),
            directories=[
                SharedDirectorySettingEntry(
                    path=str(shared_dir),
                    share_mode=DirectoryShareMode.EVERYONE
                )
            ]
        )
    )

    return SoulSeekClient(settings)


def create_clients(tmp_path: Path, amount: int) -> list[SoulSeekClient]:
    clients: list[SoulSeekClient] = []

    for idx in range(amount):
        username = 'user' + str(idx).zfill(3)
        port = 40000 + (idx * 10)
        clients.append(create_client(tmp_path, username, port))

    return clients


async def client_start_and_scan(client: SoulSeekClient, timeout: float = 3) -> SoulSeekClient:
    """Starts the client, logs in, scans the shares and waits for client to be
    logged on
    """
    init_event = asyncio.Event()

    def set_event(session_init_event):
        init_event.set()

    # Wait for the complete session initialization to be complete
    client.events.register(
        SessionInitializedEvent, set_event, priority=999999)

    await client.start()
    await client.login()
    await client.shares.scan()

    async with atimeout(timeout):
        await init_event.wait()

    return client


@pytest_asyncio.fixture
async def mock_server(request: FixtureRequest) -> AsyncGenerator[MockServer, None]:
    server = MockServer(
        hostname=DEFAULT_SERVER_HOSTNAME,
        ports={DEFAULT_SERVER_PORT},
        settings=getattr(request, 'param', None)
    )
    await server.connect(start_serving=False)
    await asyncio.gather(
        *[
            connection.start_serving()
            for connection in server.connections.values()
        ]
    )

    yield server

    await server.disconnect()


@pytest_asyncio.fixture
async def client_1(tmp_path: Path) -> AsyncGenerator[SoulSeekClient, None]:
    client = create_client(tmp_path, 'user0', 40000)

    try:
        await client_start_and_scan(client)
        yield client

    finally:
        await client.stop()


@pytest_asyncio.fixture
async def client_2(tmp_path: Path) -> AsyncGenerator[SoulSeekClient, None]:
    client = create_client(tmp_path, 'user1', 41000)

    try:
        await client_start_and_scan(client)
        yield client

    finally:
        await client.stop()


@pytest_asyncio.fixture
async def clients(tmp_path: Path, request) -> AsyncGenerator[list[SoulSeekClient], None]:
    client_list = create_clients(tmp_path, amount=request.param)

    stop_tasks = [client.stop() for client in client_list]

    start_results = await asyncio.gather(
        *[client_start_and_scan(client) for client in client_list],
        return_exceptions=True
    )

    if any(isinstance(result, Exception) for result in start_results):
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        raise Exception("a client failed to start")

    yield client_list

    await asyncio.gather(*stop_tasks, return_exceptions=True)
