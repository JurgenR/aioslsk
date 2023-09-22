import copy
import os
import shutil
import pytest

from aioslsk.configuration import Configuration
from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.transfer.model import Transfer, TransferDirection

RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'resources')


@pytest.fixture
def configuration(tmpdir) -> Configuration:
    settings_dir = os.path.join(tmpdir, 'settings')
    data_dir = os.path.join(tmpdir, 'data')
    return Configuration(settings_dir, data_dir)


class TestTransferShelveCache:
    TRANSFERS = [
        Transfer('user0', '@abcdef\\file.mp3', TransferDirection.DOWNLOAD),
        Transfer('user1', '@abcdef\\file.flac', TransferDirection.UPLOAD)
    ]

    def test_read(self, configuration: Configuration):
        shutil.copytree(os.path.join(RESOURCES, 'data'), configuration.data_directory, dirs_exist_ok=True)
        cache = TransferShelveCache(configuration.data_directory)
        transfers = cache.read()
        assert 2 == len(transfers)
        assert self.TRANSFERS == transfers

    def test_write(self, configuration: Configuration):
        cache = TransferShelveCache(configuration.data_directory)
        cache.write(self.TRANSFERS)

    def test_write_withDeletedEntries_shouldRemove(self, configuration: Configuration):
        cache = TransferShelveCache(configuration.data_directory)
        cache.write(self.TRANSFERS)

        transfers_with_deleted = copy.deepcopy(self.TRANSFERS)
        transfers_with_deleted.pop()
        cache.write(transfers_with_deleted)

        transfers = cache.read()
        assert transfers_with_deleted == transfers
