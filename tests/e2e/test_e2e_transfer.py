from aioslsk.client import SoulSeekClient
from aioslsk.events import TransferAddedEvent, TransferProgressEvent
from aioslsk.transfer.model import Transfer, TransferDirection, TransferState
from .mock.server import MockServer
from .fixtures import mock_server, client_1, client_2
from .utils import (
    wait_for_remotely_queued_state,
    wait_for_search_results,
    wait_for_transfer_added,
    wait_for_transfer_state,
    wait_until_clients_initialized,
)
import asyncio
import filecmp
import logging
import os
import pytest
from unittest.mock import AsyncMock


logger = logging.getLogger(__name__)


class TestE2ETransfer:

    @pytest.mark.asyncio
    async def test_transfer_happyFlow(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Happy path for performing a transfer"""
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(100)
        client_2.network.set_upload_speed_limit(100)

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

        upload = await wait_for_transfer_added(client_2)
        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)

        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

        # Verify download
        assert download.direction == TransferDirection.DOWNLOAD
        assert download.username == result.username
        assert download.bytes_transfered == download.filesize

        assert os.path.exists(download.local_path)
        assert filecmp.cmp(download.local_path, upload.local_path)

        # Verify upload
        assert upload.direction == TransferDirection.UPLOAD
        assert upload.username == client_1.session.user.name
        assert upload.bytes_transfered == upload.filesize

    @pytest.mark.asyncio
    async def test_transfer_events(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Happy path, test events"""
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(100)
        client_2.network.set_upload_speed_limit(100)

        # Register listeners
        downloader_add_listener = AsyncMock()
        downloader_progress_listener = AsyncMock()
        uploader_add_listener = AsyncMock()
        uploader_progress_listener = AsyncMock()
        client_1.events.register(TransferAddedEvent, downloader_add_listener)
        client_1.events.register(TransferProgressEvent, downloader_progress_listener)
        client_2.events.register(TransferAddedEvent, uploader_add_listener)
        client_2.events.register(TransferProgressEvent, uploader_progress_listener)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

        downloader_add_listener.assert_awaited_once()
        uploader_add_listener.assert_awaited_once()

        assert downloader_progress_listener.await_count > 0
        assert uploader_progress_listener.await_count > 0

    @pytest.mark.asyncio
    async def test_transfer_retryAfterDisconnect(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests retrying the download after the connection got disconnected"""
        await wait_until_clients_initialized(mock_server, amount=2)

        client_1.network.set_download_speed_limit(60)
        client_2.network.set_upload_speed_limit(60)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)
        await asyncio.sleep(1)

        for pconnection in client_1.network.peer_connections:
            if pconnection.connection_type == 'F':
                pconnection._reader = None

        await asyncio.sleep(1)

        for pconnection in client_2.network.peer_connections:
            if pconnection.connection_type == 'F':
                pconnection._writer = None

        # Downloader should bounce back
        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

    @pytest.mark.asyncio
    async def test_transfer_pauseAndResumeDownload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests pausing and resuming a download"""
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(50)
        client_2.network.set_upload_speed_limit(50)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)
        await asyncio.sleep(0.5)

        # Pause the transfer and wait for the correct states
        await client_1.transfers.pause(download)

        await wait_for_transfer_state(download, TransferState.PAUSED)
        await wait_for_transfer_state(upload, TransferState.FAILED)

        # Restart the transfer and wait for complete
        await client_1.transfers.queue(download)

        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

    @pytest.mark.asyncio
    async def test_transfer_pauseAndResumeUpload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests pausing and resuming a download"""
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(50)
        client_2.network.set_upload_speed_limit(50)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)
        await asyncio.sleep(0.5)

        # Pause the transfer and wait for the correct states
        await client_2.transfers.pause(upload)

        await wait_for_transfer_state(download, TransferState.FAILED)
        await wait_for_transfer_state(upload, TransferState.PAUSED)

        # Restart the transfer and wait for complete
        await client_2.transfers.queue(upload)

        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

    @pytest.mark.asyncio
    async def test_transfer_abortDownload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests aborting a download

        The download should end up in ABORTED state
        The upload should end up in FAILED state
        """
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(50)
        client_2.network.set_upload_speed_limit(50)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)
        await asyncio.sleep(0.5)

        # Check the path exists (store to check later if it is removed)
        assert os.path.exists(download.local_path) is True
        download_local_path = download.local_path

        # Finally abort the transfer
        await client_1.transfers.abort(download)

        # Verify download
        await wait_for_transfer_state(download, TransferState.ABORTED)
        await wait_for_transfer_state(upload, TransferState.FAILED)

        # Verify file
        assert download.local_path is None
        assert os.path.exists(download_local_path) is False
        assert os.path.exists(upload.local_path) is True

    @pytest.mark.asyncio
    async def test_transfer_abortUpload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests aborting an upload.

        The download should end up in FAILED state
        The upload should end up in ABORTED state
        """
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(50)
        client_2.network.set_upload_speed_limit(50)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)
        await asyncio.sleep(0.5)

        # Abort the upload
        await client_2.transfers.abort(upload)

        await wait_for_transfer_state(download, TransferState.FAILED)
        await wait_for_transfer_state(upload, TransferState.ABORTED)

        # Verify file
        assert os.path.exists(download.local_path) is True
        assert os.path.exists(upload.local_path) is True

    @pytest.mark.asyncio
    async def test_transfer_removeDownload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests removing a download

        The download should end up in ABORTED state (and be removed afterwards)
        The upload should end up in FAILED state
        """
        await wait_until_clients_initialized(mock_server, amount=2)
        client_1.network.set_download_speed_limit(50)
        client_2.network.set_upload_speed_limit(50)

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2, initial_amount=0)

        await wait_for_transfer_state(download, TransferState.DOWNLOADING)
        await wait_for_transfer_state(upload, TransferState.UPLOADING)
        await asyncio.sleep(0.5)

        # Check the path exists (store to check later if it is removed)
        download_local_path = download.local_path

        # Finally remove the transfer
        await client_1.transfers.remove(download)

        # Verify download is aborted
        await wait_for_transfer_state(download, TransferState.ABORTED)
        await wait_for_transfer_state(upload, TransferState.FAILED)

        # Verify file
        assert download.local_path is None
        assert os.path.exists(download_local_path) is False
        assert os.path.exists(upload.local_path) is True
        assert download not in client_1.transfers.transfers

    @pytest.mark.asyncio
    async def test_transfer_requeueWhenUserComesOnline(
            self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):

        await wait_until_clients_initialized(mock_server, amount=2)

        # Set the amount of upload slots to 0 to block transfer from starting
        client_2.settings.transfers.limits.upload_slots = 0

        download = await self._search_and_download(client_1)
        upload = await wait_for_transfer_added(client_2)

        assert download.remotely_queued is True

        # Disconnect the uploader, remove the upload and restart the uploader
        await client_2.stop()
        await client_2.transfers.remove(upload)
        await wait_for_remotely_queued_state(download, state=False)

        initial_amount = len(client_2.transfers.transfers)

        client_2.settings.transfers.limits.upload_slots = 1
        await client_2.start()
        await client_2.shares.scan()
        await client_2.login()

        upload = await wait_for_transfer_added(client_2, initial_amount=initial_amount)
        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

    async def _search_and_download(self, client_1: SoulSeekClient) -> Transfer:
        """Client 1 performs a search and starts a download of a file"""
        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)
        result = request.results[0]
        return await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )
