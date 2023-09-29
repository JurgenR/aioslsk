from aioslsk.configuration import Configuration
from aioslsk.shares.cache import SharesShelveCache
from aioslsk.shares.model import SharedDirectory, SharedItem

import pytest
import os
import shutil


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'resources')

SHARED_DIRECTORY = SharedDirectory('music', 'C:\\music', 'abcdef')
SHARED_ITEMS = {
    'item1': SharedItem(SHARED_DIRECTORY, 'folk\\folkalbum, release\\', 'simple band(contrib. singer) - isn\'t easy song.mp3', 0.0),
    'item2': SharedItem(SHARED_DIRECTORY, 'metal\\metalalbum release\\', 'simple band (contrib. singer)_-_don\'t easy song 片仮名.flac', 0.0),
    'item3': SharedItem(SHARED_DIRECTORY, 'rap\\rapalbum_release\\', 'simple_band(contributer. singer)-don\'t_easy_song 片仮名.mp3', 0.0),
}
SHARED_DIRECTORY.items = set(SHARED_ITEMS.values())


@pytest.fixture
def configuration(tmpdir) -> Configuration:
    settings_dir = os.path.join(tmpdir, 'settings')
    data_dir = os.path.join(tmpdir, 'data')
    return Configuration(settings_dir, data_dir)


class TestSharesShelveCache:

    def test_read(self, configuration: Configuration):
        shutil.copytree(os.path.join(RESOURCES, 'data'), configuration.data_directory, dirs_exist_ok=True)
        cache = SharesShelveCache(configuration.data_directory)
        directories = cache.read()
        assert [SHARED_DIRECTORY, ] == directories

    def test_write(self, configuration: Configuration):
        cache = SharesShelveCache(configuration.data_directory)
        cache.write([SHARED_DIRECTORY, ])
