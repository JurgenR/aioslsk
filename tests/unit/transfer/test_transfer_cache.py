import copy
import os
import shutil

from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.transfer.model import Transfer, TransferDirection

RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'resources')


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
