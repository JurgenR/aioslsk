from pyslsk.filemanager import extract_attributes, FileManager, SharedItem

import pytest

import os
import tempfile


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources')

MP3_FILENAME = 'Kevin_MacLeod-Galway.mp3'
FLAC_FILENAME = 'Kevin_MacLeod-Galway.flac'


DEFAULT_SETTINGS = {
    'directories': [
        RESOURCES
    ]
}


class TestFunctions:

    def test_whenExtractAttributesMP3File_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, MP3_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(0, 128), (1, 15)]

    def test_whenExtractAttributesFLACFile_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, FLAC_FILENAME)

        attributes = extract_attributes(filepath)

        attributes = [(1, 15), (4, 44100), (5, 16)]


class TestFileManager:

    def test_whenFetchSharedItems(self):
        manager = FileManager(DEFAULT_SETTINGS)

        assert sorted(manager.shared_items) == sorted([
            SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.flac'),
            SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.mp3'),
            SharedItem(root=RESOURCES, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')
        ])

    def test_whenGetStats_shouldReturnStats(self):
        manager = FileManager(DEFAULT_SETTINGS)

        dirs, files = manager.get_stats()

        assert dirs == 2
        assert files == 3

    def test_whenGetSharedItemMatches_shouldReturnSharedItem(self):
        manager = FileManager(DEFAULT_SETTINGS)

        filepath = os.path.join(RESOURCES, 'Cool_Test_Album', 'Strange_Drone_Impact.mp3')
        item = manager.get_shared_item(filepath)

        assert item == SharedItem(root=RESOURCES, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')

    def test_whenGetSharedItemDoesNotMatch_shouldRaiseException(self):
        manager = FileManager(DEFAULT_SETTINGS)

        filepath = os.path.join(RESOURCES, 'Cool_Test_Album', 'nonexistant.mp3')

        with pytest.raises(LookupError):
            manager.get_shared_item(filepath)

    def test_whenGetSharedItemDoesNotExistOnDisk_shouldRaiseException(self):
        manager = FileManager(DEFAULT_SETTINGS)

        item_not_on_disk = SharedItem(RESOURCES, '', 'InItemsButNotOnDisk.mp3')
        manager.shared_items.append(item_not_on_disk)
        filepath = os.path.join(RESOURCES, '', 'InItemsButNotOnDisk.mp3')

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
                    SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.flac'),
                    SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.mp3')
                ]
            ),
            # Words in different order
            (
                'Galway Kevin',
                [
                    SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.flac'),
                    SharedItem(root=RESOURCES, subdir='', filename='Kevin_MacLeod-Galway.mp3')
                ]
            ),
            # Subdir name + case sensitivity
            (
                'cOOL iMPACT',
                [
                    SharedItem(root=RESOURCES, subdir='Cool_Test_Album', filename='Strange_Drone_Impact.mp3')
                ]
            )
        ]
    )
    def test_whenQuery_shouldReturnMatches(self, query, expected_items):
        manager = FileManager(DEFAULT_SETTINGS)

        results = manager.query(query)

        assert sorted(expected_items) == sorted(results)

    def test_whenQueryNoMatches_shouldReturnEmptyList(self):
        manager = FileManager(DEFAULT_SETTINGS)

        results = manager.query("something")

        assert results == []

    def test_whenGetDownloadPath_shouldCreateDir(self):
        settings = dict(DEFAULT_SETTINGS)


        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = os.path.join(temp_dir, 'downloads')

            settings['download'] = download_dir

            manager = FileManager(settings)

            to_download_file = os.path.join(RESOURCES, 'Cool_Test_Album', 'Strange_Drone_Impact.mp3')
            download_path = manager.get_download_path(to_download_file)

            assert os.path.exists(download_dir)
            assert os.path.join(download_dir, 'Strange_Drone_Impact.mp3') == download_path
