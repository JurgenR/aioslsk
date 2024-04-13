from aioslsk.client import SoulSeekClient
from aioslsk.events import TransferAddedEvent, TransferProgressEvent
from aioslsk.transfer.model import TransferState
from aioslsk.transfer.manager import Reasons
from .mock.server import MockServer
from .fixtures import mock_server, client_1, client_2
from .utils import (
    wait_for_search_results,
    wait_for_transfer_to_finish,
    wait_for_transfer_to_transfer,
    wait_for_transfer_state,
    wait_until_clients_initialized,
    wait_for_transfer_added,
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
    async def test_transfer(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Happy path for performing a transfer"""
        await wait_until_clients_initialized(mock_server, amount=2)

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

        await wait_for_transfer_state(download, TransferState.COMPLETE)

        # Verify download
        assert TransferState.COMPLETE == download.state.VALUE
        assert result.username == download.username
        assert download.bytes_transfered == download.filesize

        # Verify upload
        assert 1 == len(client_2.transfers.get_uploads())

        upload = client_2.transfers.get_uploads()[0]
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

        assert TransferState.COMPLETE == upload.state.VALUE
        assert upload.bytes_transfered == upload.filesize

        # Verify file
        assert os.path.exists(download.local_path)
        assert filecmp.cmp(download.local_path, upload.local_path)

    @pytest.mark.asyncio
    async def test_transfer_events(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Happy path, test events"""
        await wait_until_clients_initialized(mock_server, amount=2)

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        # Lower speeds so the transfer isn't instantaneous (file is +-200kb)
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

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

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

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        # Lower speeds so the transfer isn't instantaneous (file is +-200kb)
        client_1.network.set_download_speed_limit(60)
        client_2.network.set_upload_speed_limit(60)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

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

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        # Lower speeds so the transfer isn't instantaneous (file is +-200kb)
        client_1.network.set_download_speed_limit(30)
        client_2.network.set_upload_speed_limit(30)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

        upload = await wait_for_transfer_added(client_2)
        await asyncio.sleep(1)

        # Pause the transfer and wait for the correct states
        await client_1.transfers.pause(download)

        await wait_for_transfer_state(download, TransferState.PAUSED)
        await wait_for_transfer_state(upload, TransferState.FAILED)

        # Restart the transfer and wait for complete
        await client_1.transfers.queue(download)

        await wait_for_transfer_state(download, TransferState.COMPLETE)
        await wait_for_transfer_state(upload, TransferState.COMPLETE)

    @pytest.mark.asyncio
    async def test_transfer_abortDownload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests aborting a download

        The download should end up in ABORTED state
        The upload should end up in FAILED state
        """
        await wait_until_clients_initialized(mock_server, amount=2)

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        # Slow down the download speed
        client_1.network.set_download_speed_limit(5)
        client_2.network.set_upload_speed_limit(4)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

        # Wait for the transfer to be transfering, then wait a couple of seconds
        # to receive some data
        await wait_for_transfer_to_transfer(download)
        await asyncio.sleep(2)

        # Check the path exists
        assert os.path.exists(download.local_path) is True

        # Finally abort the transfer
        await client_1.transfers.abort(download)

        # Verify download
        assert TransferState.ABORTED == download.state.VALUE
        assert result.username == download.username

        # Verify upload
        assert 1 == len(client_2.transfers.get_uploads())
        upload = client_2.transfers.get_uploads()[0]

        # Wait for the transfer to finish on uploader side
        await wait_for_transfer_to_finish(upload)

        assert TransferState.FAILED == upload.state.VALUE

        # Verify file
        assert os.path.exists(download.local_path) is False
        assert os.path.exists(upload.local_path) is True

    @pytest.mark.asyncio
    async def test_transfer_abortUpload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
        """Tests aborting an upload.

        The download should end up in FAILED state
        The upload should end up in ABORTED state
        """
        await wait_until_clients_initialized(mock_server, amount=2)

        request = await client_1.searches.search('Strange')
        await wait_for_search_results(request)

        # Slow down the download speed
        client_1.network.set_download_speed_limit(5)
        client_2.network.set_upload_speed_limit(4)

        result = request.results[0]
        download = await client_1.transfers.download(
            result.username,
            result.shared_items[0].filename
        )

        # Wait for the transfer to be transfering, then wait a couple of seconds
        # to receive some data
        await wait_for_transfer_to_transfer(download)
        await asyncio.sleep(2)

        # Finally abort the transfer
        assert 1 == len(client_2.transfers.get_uploads())
        upload = client_2.transfers.get_uploads()[0]
        await client_2.transfers.abort(upload)

        # Wait for the download to reach failed state. Internally the download
        # will first go into INCOMPLETE state and try again. The uploader should
        # reject the new queue request
        await wait_for_transfer_state(download, TransferState.FAILED)

        assert TransferState.FAILED == download.state.VALUE
        assert TransferState.ABORTED == upload.state.VALUE

        # Verify file
        assert os.path.exists(download.local_path) is True
        assert os.path.exists(upload.local_path) is True
