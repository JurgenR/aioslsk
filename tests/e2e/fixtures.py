import asyncio
import os
import pytest_asyncio
import shutil
from typing import List

from aioslsk.client import SoulSeekClient
from aioslsk.shares.model import DirectoryShareMode
from aioslsk.settings import (
    Settings,
    SharedDirectorySettingEntry,
    CredentialsSettings,
)
from .mock.server import MockServer


DEFAULT_SERVER_HOSTNAME = '0.0.0.0'
DEFAULT_SERVER_PORT = 4444
DEFAULT_PASSWORD = 'Password'
FILE_SHARES = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', 'unit', 'resources', 'shared')


def create_client(tmp_path, username: str, port: int) -> SoulSeekClient:
    download_dir = tmp_path / username / 'downloads'
    download_dir.mkdir(parents=True, exist_ok=True)
    shared_dir = tmp_path / username / 'shared'
    shared_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FILE_SHARES, shared_dir, dirs_exist_ok=True)

    settings = Settings(
        credentials=CredentialsSettings(
            username=username,
            password=DEFAULT_PASSWORD
        )
    )

    # settings.set('credentials.username', username)
    # settings.set('credentials.password', DEFAULT_PASSWORD)
    settings.network.server.hostname = 'localhost'
    settings.network.server.port = DEFAULT_SERVER_PORT
    settings.network.server.reconnect.auto = False
    settings.network.listening.port = port
    settings.network.listening.obfuscated_port = port + 1
    settings.network.upnp.enabled = False

    # Explicitly set to false as this would just schedule a scan in the
    # background. For the tests we want to make sure this scan is complete and
    # manually trigger it
    settings.shares.scan_on_start = False
    settings.shares.download = str(download_dir)
    settings.shares.directories.append(
        SharedDirectorySettingEntry(
            path=str(shared_dir),
            share_mode=DirectoryShareMode.EVERYONE
        )
    )

    client = SoulSeekClient(settings)

    return client


@pytest_asyncio.fixture
async def mock_server():
    server = MockServer(hostname=DEFAULT_SERVER_HOSTNAME, port=DEFAULT_SERVER_PORT)
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
async def client_1(tmp_path):
    client = create_client(tmp_path, 'user0', 40000)

    try:
        await client.start()
        await client.login()
        await client.shares.scan()
    except Exception:
        await client.stop()
        raise

    yield client

    await client.stop()


@pytest_asyncio.fixture
async def client_2(tmp_path):
    client = create_client(tmp_path, 'user1', 41000)

    try:
        await client.start()
        await client.login()
        await client.shares.scan()
    except Exception:
        await client.stop()
        raise

    yield client

    await client.stop()


@pytest_asyncio.fixture
async def clients(tmp_path, request) -> List[SoulSeekClient]:
    async def client_start_and_scan(client: SoulSeekClient):
        await client.start()
        await client.login()
        await client.shares.scan()

    clients: List[SoulSeekClient] = []

    for idx in range(request.param):
        username = 'user' + str(idx).zfill(3)
        port = 40000 + (idx * 10)
        clients.append(
            create_client(tmp_path, username, port)
        )

    start_results = await asyncio.gather(*[
        client_start_and_scan(client) for client in clients])

    if any(isinstance(result, Exception) for result in start_results):
        for client in clients:
            await client.stop()

        raise Exception("a client failed to start")

    yield clients

    asyncio.gather(*[client.stop() for client in clients])
