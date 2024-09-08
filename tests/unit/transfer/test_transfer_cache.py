import copy
import os
from pytest_unordered import unordered
import shutil

from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.state import (
    CompleteState,
    FailedState,
    UploadingState,
)


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'resources')


def create_transfers() -> list[Transfer]:
    download = Transfer('user0', '@abcdef\\file.mp3', TransferDirection.DOWNLOAD)
    download.state = CompleteState(download)
    download.start_time = 1.0
    download.complete_time = 3.0
    download.filesize = 100
    download.bytes_transfered = 100

    upload = Transfer('user1', '@abcdef\\file.flac', TransferDirection.UPLOAD)
    upload.state = FailedState(upload)
    upload.start_time = 1.0
    upload.complete_time = 3.0
    upload.filesize = 100
    upload.bytes_transfered = 50

    upload2 = Transfer('user1', '@abcdef\\subdir\\file.flac', TransferDirection.UPLOAD)
    upload2.state = UploadingState(upload2)
    upload2.start_time = 1.0
    upload2.complete_time = None
    upload2.filesize = 100
    upload2.bytes_transfered = 50

    return [download, upload, upload2]


class TestTransferShelveCache:
    TRANSFERS = [
        Transfer('user0', '@abcdef\\file.mp3', TransferDirection.DOWNLOAD),
        Transfer('user1', '@abcdef\\file.flac', TransferDirection.UPLOAD)
    ]

    def test_read(self, tmpdir: str):
        shutil.copytree(os.path.join(RESOURCES, 'data'), tmpdir, dirs_exist_ok=True)
        cache = TransferShelveCache(tmpdir)
        transfers = cache.read()
        assert 2 == len(transfers)
        assert self.TRANSFERS == transfers

    def test_write(self, tmpdir: str):
        cache = TransferShelveCache(tmpdir)
        cache.write(self.TRANSFERS)

    def test_write_withDeletedEntries_shouldRemove(self, tmpdir: str):
        cache = TransferShelveCache(tmpdir)
        cache.write(self.TRANSFERS)

        transfers_with_deleted = copy.deepcopy(self.TRANSFERS)
        transfers_with_deleted.pop()
        cache.write(transfers_with_deleted)

        transfers = cache.read()
        assert transfers_with_deleted == transfers

    def test_writeRead(self, tmpdir: str):
        expected_transfers = create_transfers()
        cache = TransferShelveCache(tmpdir)

        # Write
        cache.write(expected_transfers)

        # Read and compare
        transfers = cache.read()
        assert transfers == unordered(expected_transfers)
