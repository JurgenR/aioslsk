from aioslsk.client import SoulSeekClient
from aioslsk.transfer.model import TransferState
from .mock.server import MockServer
from .fixtures import mock_server, client_1, client_2
from .utils import (
    wait_for_search_results,
    wait_for_transfer_to_finish,
    wait_for_transfer_to_transfer,
    wait_for_transfer_state,
    wait_until_clients_initialized,
)
import asyncio
import filecmp
import logging
import os
import pytest


logger = logging.getLogger(__name__)


class TestE2ETransfer:

    @pytest.mark.asyncio
    async def test_transfer(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
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
    async def test_transfer_abortDownload(self, mock_server: MockServer, client_1: SoulSeekClient, client_2: SoulSeekClient):
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
