from pyslsk.shares import extract_attributes, SharesManager, SharedItem
from pyslsk.settings import Settings

import pytest
from pytest_unordered import unordered
import os


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources', 'shared')

MP3_FILENAME = 'Kevin_MacLeod-Galway.mp3'
FLAC_FILENAME = 'Kevin_MacLeod-Galway.flac'


DEFAULT_SETTINGS = {
    'sharing': {
        'directories': [
            RESOURCES
        ]
    }
}


# A bit of a hacky way to get the alias
RESOURCES_ALIAS = list(
    SharesManager(Settings(DEFAULT_SETTINGS)).directory_aliases.keys())[0]


@pytest.fixture
def manager():
    return SharesManager(Settings(DEFAULT_SETTINGS))


class TestFunctions:

    def test_whenExtractAttributesMP3File_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, MP3_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(0, 128), (1, 15)]

    def test_whenExtractAttributesFLACFile_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, FLAC_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(1, 15), (4, 44100), (5, 16)]


class TestSharesManager:

    def test_whenLoadFromSettings(self, manager: SharesManager):
        assert manager.shared_items == unordered([
            SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.flac'),
            SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.mp3'),
            SharedItem(root=RESOURCES_ALIAS, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')
        ])

    def test_whenAddDirectory_shouldAddDirectory(self):
        manager = SharesManager(Settings({'sharing': {'directories': []}}))
        manager.add_shared_directory(RESOURCES)
        assert manager.shared_items == unordered([
            SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.flac'),
            SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.mp3'),
            SharedItem(root=RESOURCES_ALIAS, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')
        ])
        assert RESOURCES_ALIAS in manager.directory_aliases
        assert manager.directory_aliases[RESOURCES_ALIAS] == RESOURCES

    def test_whenRemoveDirectory_shouldRemoveSharedFilesAndAlias(self, manager: SharesManager):
        manager.remove_shared_directory(RESOURCES)
        assert len(manager.directory_aliases) == 0
        assert len(manager.shared_items) == 0

    def test_whenGetStats_shouldReturnStats(self, manager):
        dirs, files = manager.get_stats()

        assert dirs == 2
        assert files == 3

    def test_whenGetSharedItemMatches_shouldReturnSharedItem(self, manager: SharesManager):
        filepath = os.path.join('@@' + RESOURCES_ALIAS, 'Cool_Test_Album', 'Strange_Drone_Impact.mp3')
        item = manager.get_shared_item(filepath)

        assert item == SharedItem(root=RESOURCES_ALIAS, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')

    def test_whenGetSharedItemDoesNotMatch_shouldRaiseException(self, manager: SharesManager):
        filepath = os.path.join('@@' + RESOURCES_ALIAS, 'Cool_Test_Album', 'nonexistant.mp3')

        with pytest.raises(LookupError):
            manager.get_shared_item(filepath)

    def test_whenGetSharedItemDoesNotExistOnDisk_shouldRaiseException(self, manager: SharesManager):
        item_not_on_disk = SharedItem(RESOURCES_ALIAS, '', 'InItemsButNotOnDisk.mp3')
        manager.shared_items.append(item_not_on_disk)
        filepath = os.path.join('@@' + RESOURCES_ALIAS, '', 'InItemsButNotOnDisk.mp3')

        with pytest.raises(LookupError):
            manager.get_shared_item(filepath)

    @pytest.mark.parametrize(
        "query,expected_items",
        [
            (
                'nomatchhere', []
            ),
            # Single word match
            (
                'Kevin',
                [
                    SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.flac'),
                    SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.mp3')
                ]
            ),
            # Words in different order
            (
                'Galway Kevin',
                [
                    SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.flac'),
                    SharedItem(root=RESOURCES_ALIAS, subdir='', filename='Kevin_MacLeod-Galway.mp3')
                ]
            ),
            # Subdir name + case sensitivity
            (
                'cOOL iMPACT',
                [
                    SharedItem(root=RESOURCES_ALIAS, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')
                ]
            )
        ]
    )
    def test_whenQuery_shouldReturnMatches(self, query, expected_items, manager: SharesManager):
        results = manager.query(query)

        assert expected_items == unordered(results)

    @pytest.mark.parametrize(
        "query",
        [
            # Just spaces
            ('  '),
            # None matching at all
            ('something'),
            # Partial match
            ('kevin bacon')
        ]
    )
    def test_whenQueryNoMatches_shouldReturnEmptyList(self, query, manager: SharesManager):
        results = manager.query(query)

        assert results == []

    def test_whenGetDownloadPath_shouldCreateDir(self, manager: SharesManager, tmpdir):
        download_dir = os.path.join(tmpdir, 'downloads')
        manager._settings.set('sharing.download', download_dir)

        to_download_file = os.path.join(RESOURCES, 'Cool_Test_Album', 'Strange_Drone_Impact.mp3')
        download_path = manager.get_download_path(to_download_file)

        assert os.path.exists(download_dir)
        assert os.path.join(download_dir, 'Strange_Drone_Impact.mp3') == download_path
